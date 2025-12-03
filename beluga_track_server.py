# beluga_track_server.py  (TEMP TEST VERSION)

import sys
import os
import cv2

def main():
    if len(sys.argv) != 4:
        print("Usage: python beluga_track_server.py <input_video> <output_video> <output_csv>", file=sys.stderr)
        sys.exit(1)

    input_video = sys.argv[1]
    output_video = sys.argv[2]
    output_csv = sys.argv[3]

    print("TEST TRACKER: starting", file=sys.stderr)
    print("Input:", input_video, file=sys.stderr)
    print("Output video:", output_video, file=sys.stderr)
    print("Output csv:", output_csv, file=sys.stderr)

    if not os.path.exists(input_video):
        print("Input video not found", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(output_video), exist_ok=True)

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print("Could not open input video", file=sys.stderr)
        sys.exit(1)

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_video, fourcc, fps, (width, height))

    if not writer.isOpened():
        print("Could not open writer", file=sys.stderr)
        sys.exit(1)

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_idx += 1
        # Big obvious overlay so we know this is the processed video
        cv2.putText(
            frame,
            f"TEST TRACK {frame_idx}",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 255),
            3,
            cv2.LINE_AA,
        )

        writer.write(frame)

    cap.release()
    writer.release()
    print("TEST TRACKER: done", file=sys.stderr)
    sys.exit(0)

if __name__ == "__main__":
    main()
