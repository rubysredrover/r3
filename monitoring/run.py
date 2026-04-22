#!/usr/bin/env python3
"""Entry point for MARS Emotion Tracker + Red Rover API.

Runs as an always-on service on the Jetson.
Uses ROS2 for camera access (innate-os native).
Starts the Red Rover API on port 8080 for Mom's app.
"""

import argparse
import os
from pathlib import Path

# load .env from script directory if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

import rclpy

from emotion_tracker.camera import init_camera
from emotion_tracker.gemini_detector import GeminiDetector
from emotion_tracker.person_registry import PersonRegistry
from emotion_tracker.monitor import EmotionMonitor
from emotion_tracker.mood_ring import MoodRing
from emotion_tracker.api import start_api
from emotion_tracker.cloud_sync import start_cloud_sync


def main():
    parser = argparse.ArgumentParser(description="MARS Emotion Tracker")
    parser.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--camera-topic", default="/mars/main_camera/left/image_raw",
                        help="ROS2 camera topic (default: main camera)")
    parser.add_argument("--api-port", type=int, default=8080,
                        help="Red Rover API port (default: 8080)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: Set GEMINI_API_KEY env var or pass --api-key")
        return

    # start Red Rover API for Mom's app
    start_api(port=args.api_port)

    # start cloud sync — pushes events to Bolo so the app works from any network
    start_cloud_sync()

    detector = GeminiDetector(api_key=api_key)
    camera = init_camera(topic=args.camera_topic)
    registry = PersonRegistry()
    mood_ring = MoodRing()

    registry.open()

    try:
        monitor = EmotionMonitor(
            detector=detector,
            camera=camera,
            registry=registry,
            mood_ring=mood_ring,
        )
        monitor.run()
    finally:
        camera.close()
        registry.close()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
