# beluga_track_server.py

import os
import sys
import cv2
import numpy as np
import datetime
import pandas as pd
from ultralytics import YOLO

# ========= CONFIG =========
# Change these to wherever the model + tracker live on the server
MODEL_PATH = r"/app/models/best.pt"          # example for Render
TRACKER_PATH = r"/app/models/bytetrack_whales.yaml"

CLASS_NAMES = ["Adult", "Calf"]
SMOOTHING_ALPHA = 0.30
CSV_EVERY_N_FRAMES = 100

# === Colors (BGR) ===
ADULT_GREEN = (147, 205, 108)   # light green
CALF_BLUE   = (180, 163, 117)   # light blue in BGR
TEXT_COLOR = (0, 0, 0)
FONT       = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.6
TEXT_THICK = 1
PAD_X      = 8
PAD_Y      = 6
LABEL_ALPHA = 0.85


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
    cv2.putText(
        img, label_text,
        (left + PAD_X, bottom - PAD_Y),
        FONT, FONT_SCALE, TEXT_COLOR, TEXT_THICK, cv2.LINE_AA
    )


def safe_class_name(class_id):
    return CLASS_NAMES[class_id] if 0 <= class_id < len(CLASS_NAMES) else str(class_id)


def run_beluga_tracking(input_video_path, output_video_path, output_csv_path):
    model = YOLO(MODEL_PATH)

    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_video_path}")

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps    = float(fps)

    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

    writer = cv2.VideoWriter(
        output_video_path,
        cv2.VideoWriter_fourcc(*'mp4v'),
        fps,
        (width, height)
    )

    frame_idx = 0
    smoothing_buffer = {}
    tracking_rows = []

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

                    draw_box_with_label(frame, (x1, y1, x2, y2), label_text, box_color)

                    tracking_rows.append([
                        frame_idx, t_sec, track_id, whale_class,
                        x1, y1, x2, y2, beh_name, conf_val
                    ])

        writer.write(frame)

        if frame_idx % CSV_EVERY_N_FRAMES == 0 and tracking_rows:
            pd.DataFrame(
                tracking_rows,
                columns=[
                    "Frame","Time (s)","Track_ID","Class",
                    "X1","Y1","X2","Y2","Behavior","Conf"
                ]
            ).to_csv(output_csv_path, index=False)

    if tracking_rows:
        pd.DataFrame(
            tracking_rows,
            columns=[
                "Frame","Time (s)","Track_ID","Class",
                "X1","Y1","X2","Y2","Behavior","Conf"
            ]
        ).to_csv(output_csv_path, index=False)

    cap.release()
    writer.release()


def main():
    if len(sys.argv) != 4:
        print("Usage: python beluga_track_server.py <input_video> <output_video> <output_csv>", file=sys.stderr)
        sys.exit(1)

    input_video = sys.argv[1]
    output_video = sys.argv[2]
    output_csv = sys.argv[3]

    run_beluga_tracking(input_video, output_video, output_csv)

    # For debugging/logging
    print(f"VIDEO_OUT={output_video}")
    print(f"CSV_OUT={output_csv}")


if __name__ == "__main__":
    main()
