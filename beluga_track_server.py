# beluga_track_server.py

import sys
import os
import cv2
import numpy as np
import pandas as pd
import requests
from ultralytics import YOLO

# ========= CONFIG =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Model will be stored in /tmp so it's writeable in cloud envs
MODEL_DIR = os.environ.get("BELUGA_MODEL_DIR", "/tmp/beluga_models")
MODEL_PATH = os.path.join(MODEL_DIR, "best.pt")

# Tracker YAML (small) can be committed to your repo
TRACKER_PATH = os.path.join(BASE_DIR, "models", "bytetrack_whales.yaml")

CLASS_NAMES = ["Adult", "Calf"]
SMOOTHING_ALPHA = 0.30
CSV_EVERY_N_FRAMES = 100

# === Colors (BGR) ===
ADULT_GREEN = (147, 205, 108)
CALF_BLUE   = (180, 163, 117)
TEXT_COLOR = (0, 0, 0)
FONT       = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.6
TEXT_THICK = 1
PAD_X      = 8
PAD_Y      = 6
LABEL_ALPHA = 0.85

# ========= HELPERS =========
def smooth(old, new, alpha=SMOOTHING_ALPHA):
    return int(alpha * new + (1 - alpha) * old)

def alpha_rect(img, p1, p2, color, alpha=LABEL_ALPHA):
    x1, y1 = p1; x2, y2 = p2
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(img.shape[1] - 1, x2); y2 = min(img.shape[0] - 1, y2)
    if x2 <= x1 or y2 <= y1:
        return
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, dst=img)

def draw_box_with_label(img, box, label_text, box_color):
    x1, y1, x2, y2 = box
    cv2.rectangle(img, (x1, y1), (x2, y2), box_color, 2)
    (tw, th), _ = cv2.getTextSize(label_text, FONT, FONT_SCALE, TEXT_THICK)
    top = max(0, y1 - th - 2 * PAD_Y)
    left = x1
    right = min(img.shape[1] - 1, x1 + tw + 2 * PAD_X)
    bottom = y1
    alpha_rect(img, (left, top), (right, bottom), box_color, alpha=LABEL_ALPHA)
    cv2.putText(img, label_text, (left + PAD_X, bottom - PAD_Y),
                FONT, FONT_SCALE, TEXT_COLOR, TEXT_THICK, cv2.LINE_AA)

def safe_class_name(class_id):
    return CLASS_NAMES[class_id] if 0 <= class_id < len(CLASS_NAMES) else str(class_id)

def ensure_model_downloaded():
    """Download best.pt into MODEL_PATH if it doesn't exist yet."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(MODEL_PATH):
        print(f"🔹 Model already present at {MODEL_PATH}", flush=True)
        return

    model_url = os.environ.get("BELUGA_MODEL_URL")
    if not model_url:
        raise RuntimeError(
            "BELUGA_MODEL_URL environment variable is not set. "
            "Set it on Render to a direct-download URL for best.pt."
        )

    print(f"🔹 Downloading model from {model_url} to {MODEL_PATH} ...", flush=True)
    resp = requests.get(model_url, stream=True)
    resp.raise_for_status()

    tmp_path = MODEL_PATH + ".download"
    with open(tmp_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    os.replace(tmp_path, MODEL_PATH)
    print("✅ Model download complete.", flush=True)

def main():
    # Expect: python beluga_track_server.py input_video.mp4 output_video.mp4 output_csv.csv
    if len(sys.argv) != 4:
        print("Usage: python beluga_track_server.py <input_video> <output_video> <output_csv>", file=sys.stderr)
        sys.exit(1)

    input_video = sys.argv[1]
    output_video = sys.argv[2]
    output_csv = sys.argv[3]

    if not os.path.exists(input_video):
        print(f"❌ Input video does not exist: {input_video}", file=sys.stderr)
        sys.exit(1)

    # Ensure output folders exist
    os.makedirs(os.path.dirname(output_video), exist_ok=True)
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)

    # Make sure we have the model
    try:
        ensure_model_downloaded()
    except Exception as e:
        print(f"❌ Failed to prepare model: {e}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(TRACKER_PATH):
        print(f"❌ Tracker config not found at {TRACKER_PATH}", file=sys.stderr)
        sys.exit(1)

    print("🔹 Loading YOLO model...", flush=True)
    model = YOLO(MODEL_PATH)

    print(f"🔹 Opening video: {input_video}", flush=True)
    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {input_video}", file=sys.stderr)
        sys.exit(1)

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps = float(fps)

    print(f"Video properties: {width}x{height} @ {fps:.2f} fps", flush=True)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_video, fourcc, fps, (width, height))
    if not writer.isOpened():
        print(f"❌ Could not open writer for output video: {output_video}", file=sys.stderr)
        cap.release()
        sys.exit(1)

    frame_idx = 0
    smoothing_buffer = {}
    tracking_rows = []

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            frame_idx += 1
            t_sec = frame_idx / fps

            results = model.track(frame, persist=True, tracker=TRACKER_PATH)

            if results:
                for r in results:
                    if not hasattr(r, 'boxes') or r.boxes is None or len(r.boxes) == 0:
                        continue
                    for box in r.boxes:
                        class_id = int(box.cls[0]) if box.cls is not None else 0
                        track_id = int(box.id[0])  if box.id is not None else -1
                        if track_id == -1:
                            continue

                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        # Smooth boxes per track id
                        if track_id in smoothing_buffer:
                            px1, py1, px2, py2 = smoothing_buffer[track_id]
                            x1 = smooth(px1, x1); y1 = smooth(py1, y1)
                            x2 = smooth(px2, x2); y2 = smooth(py2, y2)
                        smoothing_buffer[track_id] = [x1, y1, x2, y2]

                        whale_class = safe_class_name(class_id)
                        beh_name = 'surfacing' if whale_class == 'Adult' else 'nursing'
                        conf_val = float(box.conf[0]) if hasattr(box, "conf") and box.conf is not None else 0.0

                        label_text = f"{whale_class} ID:{track_id}"
                        box_color = CALF_BLUE if whale_class == "Calf" else ADULT_GREEN

                        draw_box_with_label(frame, (x1, y1, x2, y2), label_text, box_color=box_color)

                        tracking_rows.append([
                            frame_idx, t_sec, track_id, whale_class,
                            x1, y1, x2, y2, beh_name, conf_val
                        ])

            writer.write(frame)

            # Periodic CSV write to avoid losing everything if something crashes
            if frame_idx % CSV_EVERY_N_FRAMES == 0 and tracking_rows:
                df = pd.DataFrame(
                    tracking_rows,
                    columns=["Frame", "Time (s)", "Track_ID", "Class",
                             "X1", "Y1", "X2", "Y2", "Behavior", "Conf"]
                )
                df.to_csv(output_csv, index=False)

            if frame_idx % 50 == 0:
                print(f"Processed frame {frame_idx}...", flush=True)

        # Final CSV write
        if tracking_rows:
            df = pd.DataFrame(
                tracking_rows,
                columns=["Frame", "Time (s)", "Track_ID", "Class",
                         "X1", "Y1", "X2", "Y2", "Behavior", "Conf"]
            )
            df.to_csv(output_csv, index=False)

        print("✅ Tracking complete.")
        print(f"✅ Annotated video saved: {output_video}")
        print(f"✅ Tracking CSV saved:   {output_csv}")

    except Exception as e:
        print(f"❌ Error during tracking: {e}", file=sys.stderr)
        cap.release()
        writer.release()
        sys.exit(1)

    cap.release()
    writer.release()
    sys.exit(0)

if __name__ == "__main__":
    main()
