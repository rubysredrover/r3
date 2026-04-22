#!/usr/bin/env python3
"""Local demo of Ruby's Red Rover emotion tracker using your laptop webcam.

No ROS2, no MARS, no inspireface required — just OpenCV + Gemini.
Proves the CP-aware emotion detection pipeline works end-to-end.

Usage:
    pip install google-genai opencv-python
    export GEMINI_API_KEY="your-key"
    python demo_local.py
"""

import argparse
import base64
import json
import os
import sys
import time

import cv2

from emotion_tracker.gemini_detector import GeminiDetector
from emotion_tracker.detector import PersonEmotion


# Mood ring colors (BGR for OpenCV display)
MOOD_COLORS = {
    "happy":         (0, 200, 255),    # warm yellow
    "content":       (100, 200, 100),  # soft green
    "relaxed":       (200, 150, 80),   # calm blue
    "neutral":       (200, 150, 180),  # lavender
    "sad":           (180, 100, 50),   # deep blue
    "tired":         (180, 100, 150),  # muted purple
    "stressed":      (0, 160, 220),    # amber-orange
    "in_pain":       (0, 0, 220),      # red
    "frustrated":    (0, 80, 230),     # red-orange
    "angry":         (0, 0, 200),      # red
    "surprised":     (0, 220, 255),    # bright yellow
    "fearful":       (150, 100, 50),   # dark blue
    "disgusted":     (50, 120, 80),    # dark green
    "confused":      (200, 180, 100),  # light blue
    "excited":       (0, 180, 255),    # orange
    "uncomfortable": (100, 80, 160),   # muted mauve
}

DEFAULT_COLOR = (180, 150, 180)  # lavender fallback


def frame_to_base64(frame):
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")


def draw_overlay(frame, result: PersonEmotion, scan_count: int):
    """Draw mood ring bar and emotion info on the frame."""
    h, w = frame.shape[:2]

    if result and result.person_detected:
        color = MOOD_COLORS.get(result.emotion, DEFAULT_COLOR)

        # mood ring bar across the top
        cv2.rectangle(frame, (0, 0), (w, 40), color, -1)

        # emotion text
        label = f"{result.emotion.upper()} ({result.confidence})"
        cv2.putText(frame, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        # context at the bottom
        if result.context:
            cv2.rectangle(frame, (0, h - 35), (w, h), (0, 0, 0), -1)
            cv2.putText(frame, result.context[:80], (10, h - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    else:
        cv2.rectangle(frame, (0, 0), (w, 40), (80, 80, 80), -1)
        cv2.putText(frame, "No person detected", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)

    # scan counter
    cv2.putText(frame, f"Scan #{scan_count}", (w - 120, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    return frame


def main():
    parser = argparse.ArgumentParser(description="Ruby's Red Rover — Local Demo")
    parser.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY)")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Seconds between scans (default: 5)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: Set GEMINI_API_KEY or pass --api-key")
        sys.exit(1)

    detector = GeminiDetector(api_key=api_key)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Error: Cannot open camera {args.camera}")
        sys.exit(1)

    print("=" * 50)
    print("Ruby's Red Rover — Local Demo")
    print("=" * 50)
    print(f"Camera: {args.camera}")
    print(f"Scan interval: {args.interval}s")
    print("Press 'q' to quit, 's' to force a scan")
    print("=" * 50)
    print()

    scan_count = 0
    last_scan = 0
    last_result = None

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed")
            break

        now = time.time()

        # scan on interval or when 's' is pressed
        force_scan = False
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            force_scan = True

        if force_scan or (now - last_scan >= args.interval):
            scan_count += 1
            print(f"\n[Scan #{scan_count}] Analyzing...")

            try:
                b64 = frame_to_base64(frame)
                result = detector.analyze_frame(b64)
                last_result = result

                if result.person_detected:
                    print(f"  Emotion: {result.emotion} ({result.confidence})")
                    print(f"  Context: {result.context}")
                    print(f"  Description: {result.description}")
                else:
                    print("  No person detected")
            except Exception as e:
                print(f"  Error: {e}")

            last_scan = now

        display = draw_overlay(frame.copy(), last_result, scan_count)
        cv2.imshow("Ruby's Red Rover — Emotion Tracker", display)

    cap.release()
    cv2.destroyAllWindows()
    print(f"\nDone. {scan_count} scans completed.")


if __name__ == "__main__":
    main()
