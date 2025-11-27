# app.py
import os
import uuid
import datetime

from flask import Flask, render_template, request, jsonify, Response, abort
from flask_cors import CORS
from werkzeug.utils import secure_filename

import cv2
import pandas as pd
from ultralytics import YOLO

# ========= BASE DIR & PATHS =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH = os.path.join(BASE_DIR, "models", "best.pt")
TRACKER_PATH = os.path.join(BASE_DIR, "trackers", "bytetrack_whales.yaml")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "tracking_results")
UPLOAD_FOLDER = os.path.join(OUTPUT_FOLDER, "uploads")

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ========= CONFIG =========
CLASS_NAMES = ["Adult", "Calf"]
SMOOTHING_ALPHA = 0.30
CSV_EVERY_N_FRAMES = 100

# Colors (BGR)
ADULT_GREEN = (147, 205, 108)  # light green
CALF_BLUE   = (180, 163, 117)  # light blue
TEXT_COLOR  = (0, 0, 0)
FONT        = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE  = 0.6
TEXT_THICK  = 1
PAD_X       = 8
PAD_Y       = 6
LABEL_ALPHA = 0.85

# ========= FLASK APP =========
app = Flask(__name__)
# In production, replace "*" with your frontend origin, e.g. "https://yourname.github.io"
CORS(app, resources={r"/*": {"origins": "*"}})
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Load YOLO model once at startup
print(f"Loading YOLO model from {MODEL_PATH} ...")
model = YOLO(MODEL_PATH)
print("✅ YOLO model loaded.")

# Keep track of stream metadata in memory
STREAMS = {}  # stream_id -> {"video_path": ..., "csv_path": ...}


# ========= HELPERS =========
def smooth(old, new, alpha=SMOOTHING_ALPHA):
    return int(alpha * new + (1 - alpha) * old)


def alpha_rect(img, p1, p2, color, alpha=LABEL_ALPHA):
    x1, y1 = p1
    x2, y2 = p2

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(img.shape[1] - 1, x2)
    y2 = min(img.shape[0] - 1, y2)

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
        img,
        label_text,
        (left + PAD_X, bottom - PAD_Y),
        FONT,
        FONT_SCALE,
        TEXT_COLOR,
        TEXT_THICK,
        cv2.LINE_AA,
    )


def safe_class_name(class_id):
    return CLASS_NAMES[class_id] if 0 <= class_id < len(CLASS_NAMES) else str(class_id)


# ========= TRACKING / STREAMING =========
def generate_tracked_stream(video_path, csv_path):
    """Generator that yields MJPEG frames with YOLO tracking overlay."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps = float(fps)

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

            # YOLO + tracker
            results = model.track(frame, persist=True, tracker=TRACKER_PATH)

            if results:
                for r in results:
                    if not hasattr(r, "boxes") or r.boxes is None or len(r.boxes) == 0:
                        continue

                    for box in r.boxes:
                        class_id = int(box.cls[0]) if box.cls is not None else 0
                        track_id = int(box.id[0]) if box.id is not None else -1
                        if track_id == -1:
                            continue

                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        # Smooth bounding box positions per track_id
                        if track_id in smoothing_buffer:
                            px1, py1, px2, py2 = smoothing_buffer[track_id]
                            x1 = smooth(px1, x1)
                            y1 = smooth(py1, y1)
                            x2 = smooth(px2, x2)
                            y2 = smooth(py2, y2)
                        smoothing_buffer[track_id] = [x1, y1, x2, y2]

                        whale_class = safe_class_name(class_id)
                        beh_name = "surfacing" if whale_class == "Adult" else "nursing"
                        conf_val = (
                            float(box.conf[0])
                            if hasattr(box, "conf") and box.conf is not None
                            else 0.0
                        )

                        label_text = f"{whale_class} ID:{track_id}"
                        box_color = CALF_BLUE if whale_class == "Calf" else ADULT_GREEN

                        draw_box_with_label(
                            frame, (x1, y1, x2, y2), label_text, box_color
                        )

                        tracking_rows.append(
                            [
                                frame_idx,
                                t_sec,
                                track_id,
                                whale_class,
                                x1,
                                y1,
                                x2,
                                y2,
                                beh_name,
                                conf_val,
                            ]
                        )

            # Periodic CSV write
            if frame_idx % CSV_EVERY_N_FRAMES == 0 and tracking_rows:
                pd.DataFrame(
                    tracking_rows,
                    columns=[
                        "Frame",
                        "Time (s)",
                        "Track_ID",
                        "Class",
                        "X1",
                        "Y1",
                        "X2",
                        "Y2",
                        "Behavior",
                        "Conf",
                    ],
                ).to_csv(csv_path, index=False)

            # Encode frame as JPEG and yield as MJPEG chunk
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue

            frame_bytes = buffer.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )

    finally:
        cap.release()
        # Final CSV write
        if tracking_rows:
            pd.DataFrame(
                tracking_rows,
                columns=[
                    "Frame",
                    "Time (s)",
                    "Track_ID",
                    "Class",
                    "X1",
                    "Y1",
                    "X2",
                    "Y2",
                    "Behavior",
                    "Conf",
                ],
            ).to_csv(csv_path, index=False)
        print(f"✅ Tracking CSV saved: {csv_path}")


# ========= ROUTES =========
@app.route("/")
def index():
    """Landing page: renders templates/index.html (optional)."""
    try:
        return render_template("index.html")
    except Exception:
        # If you deploy as API only and have no templates, return a simple JSON.
        return jsonify({"status": "ok", "message": "WhaleWatch backend running"})


@app.route("/tracking")
def tracking_page():
    """Tracking upload page: renders templates/tracking.html (optional)."""
    try:
        return render_template("tracking.html")
    except Exception:
        return jsonify(
            {
                "status": "ok",
                "message": "WhaleWatch tracking page not configured; backend API is running.",
            }
        )


@app.route("/track", methods=["POST"])
def track():
    """
    Accept a video upload, save it to disk, and register a new stream.
    Returns JSON: { "stream_url": "/stream/<id>" }.
    """
    if "video" not in request.files:
        return "No video file part", 400

    file = request.files["video"]
    if file.filename == "":
        return "No selected file", 400

    filename = secure_filename(file.filename)
    stream_id = uuid.uuid4().hex
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    video_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{stream_id}_{filename}")
    file.save(video_path)

    csv_path = os.path.join(OUTPUT_FOLDER, f"tracking_{ts}_{stream_id}.csv")
    STREAMS[stream_id] = {"video_path": video_path, "csv_path": csv_path}

    print(f"🎥 New video uploaded: {video_path} (stream_id={stream_id})")

    return jsonify({"stream_url": f"/stream/{stream_id}"})


@app.route("/stream/<stream_id>")
def stream(stream_id):
    """
    MJPEG stream of YOLO-tracked video for a given stream_id.
    """
    info = STREAMS.get(stream_id)
    if not info:
        abort(404, f"Unknown stream id: {stream_id}")

    video_path = info["video_path"]
    csv_path = info["csv_path"]

    return Response(
        generate_tracked_stream(video_path, csv_path),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ========= ENTRY POINT =========
if __name__ == "__main__":
    # For Render, PORT is provided in the environment.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
