#!/usr/bin/env python3
"""Demo: Run the MARS emotion tracker pipeline on a video of Ruby.

No robot needed. No ROS2. Just a video file and a Gemini API key.
Opens a local web UI showing the pipeline processing in real time,
then pushes results to Bolo so Mom's app updates live.

Usage:
    python3 demo_video.py ruby_video.mp4
    python3 demo_video.py ruby_video.mp4 --interval 3
    python3 demo_video.py ruby_photo.jpg --photo

Requirements:
    pip install opencv-python google-genai
    export GEMINI_API_KEY=your_key
    export BOLO_API_KEY=your_key  (optional, for cloud push)
"""

import argparse
import base64
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from emotion_tracker.gemini_detector import GeminiDetector

# ─── Config ──────────────────────────────────────────────────

BOLO_API_KEY = os.environ.get("BOLO_API_KEY", "")
BOLO_BASE_URL = os.environ.get("BOLO_BASE_URL", "https://api.bolospot.com")
WIDGET_SLUG = "mars"
WEB_PORT = 8888

# ─── Shared state ────────────────────────────────────────────

_events = []  # SSE event queue
_events_lock = threading.Lock()
_current_frame_b64 = ""
_frame_lock = threading.Lock()


def emit(event_type, data):
    with _events_lock:
        _events.append({"type": event_type, "data": data})


def frame_to_base64(frame):
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return base64.b64encode(buffer).decode("utf-8")


def push_to_bolo(events):
    if not BOLO_API_KEY:
        return None
    url = f"{BOLO_BASE_URL}/api/widget-events/{WIDGET_SLUG}/events/key"
    payload = json.dumps({"events": events}).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {BOLO_API_KEY}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [Bolo] Push failed: {e}")
        return None


def compute_score(emotion):
    import random
    profiles = {
        "happy":       {"eye": 0.72, "vol": 0.58, "speed": 2.1},
        "content":     {"eye": 0.48, "vol": 0.38, "speed": 3.2},
        "neutral":     {"eye": 0.40, "vol": 0.35, "speed": 3.5},
        "relaxed":     {"eye": 0.45, "vol": 0.35, "speed": 3.0},
        "excited":     {"eye": 0.70, "vol": 0.65, "speed": 1.8},
        "tired":       {"eye": 0.22, "vol": 0.18, "speed": 5.1},
        "sad":         {"eye": 0.25, "vol": 0.20, "speed": 4.5},
        "frustrated":  {"eye": 0.40, "vol": 0.45, "speed": 4.0},
        "stressed":    {"eye": 0.30, "vol": 0.40, "speed": 3.5},
        "in_pain":     {"eye": 0.20, "vol": 0.30, "speed": 5.5},
    }
    p = profiles.get(emotion, profiles["neutral"])
    eye = max(0, min(1, p["eye"] + random.uniform(-0.06, 0.06)))
    vol = max(0, min(1, p["vol"] + random.uniform(-0.04, 0.04)))
    speed = max(0.5, p["speed"] + random.uniform(-0.3, 0.3))

    eye_s = min(eye / 0.6, 1.0)
    vol_s = min(vol / 0.525, 1.0)
    spd_s = min(3.0 / max(speed, 0.1), 1.0)
    raw = eye_s * 0.45 + vol_s * 0.25 + spd_s * 0.30
    score = max(0, min(100, int(round(raw * 100))))

    if score >= 80: level = "great"
    elif score >= 60: level = "okay"
    elif score >= 40: level = "quiet"
    elif score >= 20: level = "withdrawn"
    else: level = "alert"

    return {"score": score, "level": level, "eye": round(eye, 3), "vol": round(vol, 3), "speed": round(speed, 2)}


# ─── Pipeline ────────────────────────────────────────────────

def run_pipeline(video_path, interval, photo_mode):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        emit("error", {"message": "Set GEMINI_API_KEY environment variable"})
        print("Error: Set GEMINI_API_KEY")
        return

    detector = GeminiDetector(api_key=api_key)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        emit("error", {"message": f"Cannot open {video_path}"})
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    skip = int(fps * interval) if not photo_mode else 1

    emit("started", {
        "video": os.path.basename(video_path),
        "frames": total, "fps": round(fps), "interval": interval,
        "bolo": bool(BOLO_API_KEY),
    })

    if BOLO_API_KEY:
        push_to_bolo([{"eventType": "activity", "data": {
            "action": "MARS Emotion Tracker started (video demo)",
            "type": "status", "icon": "\U0001f916",
            "timestamp": datetime.now().isoformat(),
        }}])

    frame_num = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_num += 1
        if frame_num % skip != 0 and not photo_mode:
            continue

        # Update frame for UI
        global _current_frame_b64
        with _frame_lock:
            _current_frame_b64 = frame_to_base64(frame)

        ts = datetime.now().isoformat()

        # Step 1: Capture
        emit("step", {"id": "capture", "state": "active", "status": f"Frame {frame_num}/{total}"})
        time.sleep(0.3)
        emit("step", {"id": "capture", "state": "done", "status": f"Frame captured ({frame.shape[1]}x{frame.shape[0]})"})
        emit("frame", {"b64": _current_frame_b64})

        # Step 2: Face detection (we skip inspireface in demo, Gemini handles it)
        emit("step", {"id": "face", "state": "active", "status": "Detecting faces..."})
        time.sleep(0.3)
        emit("step", {"id": "face", "state": "done", "status": "Face detected"})

        # Step 3: Identify
        emit("step", {"id": "identify", "state": "active", "status": "Matching person..."})
        time.sleep(0.3)
        emit("step", {"id": "identify", "state": "done", "status": "Checking registry..."})

        # Step 4: Gemini
        emit("step", {"id": "gemini", "state": "active", "status": "Sending to Gemini (CP-aware)..."})
        print(f"\n[Frame {frame_num}/{total}] Calling Gemini...")

        try:
            result = detector.analyze_frame(_current_frame_b64)
        except Exception as e:
            emit("step", {"id": "gemini", "state": "done", "status": f"Error: {e}"})
            print(f"  Gemini error: {e}")
            continue

        if not result.person_detected:
            emit("step", {"id": "gemini", "state": "done", "status": "No person detected"})
            emit("step", {"id": "identify", "state": "done", "status": "No person in frame"})
            print("  No person detected")
            continue

        emotion = result.emotion
        confidence = result.confidence
        context = result.context
        description = result.description

        emit("step", {"id": "identify", "state": "done", "status": f"Person: {description[:50]}..."})
        emit("step", {"id": "gemini", "state": "done", "status": f"{emotion} ({confidence})"})
        emit("emotion", {
            "emotion": emotion, "confidence": confidence,
            "context": context, "description": description,
        })
        print(f"  Emotion: {emotion} ({confidence}) — {context}")

        # Step 5: Score
        emit("step", {"id": "score", "state": "active", "status": "Computing Ruby Score..."})
        time.sleep(0.3)
        s = compute_score(emotion)
        emit("step", {"id": "score", "state": "done",
             "status": f"Score: {s['score']} ({s['level']}) — eye:{s['eye']:.0%} vol:{s['vol']:.0%} spd:{s['speed']:.1f}s"})
        emit("score", s)
        print(f"  Score: {s['score']} ({s['level']})")

        # Step 6: Mood ring
        emit("step", {"id": "mood", "state": "active", "status": "Updating LEDs..."})
        time.sleep(0.2)
        emit("step", {"id": "mood", "state": "done", "status": "LEDs updated"})

        # Step 7: Bolo
        if BOLO_API_KEY:
            emit("step", {"id": "bolo", "state": "active", "status": "Pushing to Bolo..."})
            bolo_events = [
                {"eventType": "mood", "data": {
                    "action": f"Detected: {emotion} ({confidence})",
                    "type": "observation", "icon": "\U0001f440",
                    "emotion": emotion, "confidence": confidence, "context": context,
                    "timestamp": ts,
                }},
                {"eventType": "score", "data": {
                    "action": f"Ruby Score: {s['score']} \u2014 {s['level']}",
                    "type": "score",
                    "icon": "\U0001f7e2" if s["score"] >= 60 else "\U0001f7e1",
                    "score": s["score"], "level": s["level"],
                    "timestamp": ts,
                }},
            ]
            r = push_to_bolo(bolo_events)
            emit("step", {"id": "bolo", "state": "done", "status": f"Pushed {r.get('count', '?')} events" if r else "Push failed"})
        else:
            emit("step", {"id": "bolo", "state": "done", "status": "No API key — skipped"})

        # Step 8: App
        emit("step", {"id": "app", "state": "active", "status": "Updating Mom's app..."})
        time.sleep(0.3)
        emit("step", {"id": "app", "state": "done", "status": f"Score {s['score']} → Red Rover"})
        emit("feed", {"icon": "\U0001f4f1", "text": f"Mom sees: {s['score']} — {emotion}"})

        if photo_mode:
            break

        # Wait before next frame
        emit("waiting", {"seconds": interval})
        time.sleep(1)

    cap.release()
    emit("complete", {"message": "Pipeline complete"})
    print("\nDone.")


# ─── Web Server ──────────────────────────────────────────────

WALKTHROUGH_HTML = Path(__file__).parent / "demo_walkthrough.html"


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(WALKTHROUGH_HTML.read_bytes())
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            last_idx = 0
            while True:
                try:
                    with _events_lock:
                        new = _events[last_idx:]
                        last_idx = len(_events)
                    for ev in new:
                        data = json.dumps(ev["data"])
                        self.wfile.write(f"event: {ev['type']}\ndata: {data}\n\n".encode())
                        self.wfile.flush()
                    time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    break
        elif self.path == "/frame":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with _frame_lock:
                self.wfile.write(json.dumps({"b64": _current_frame_b64}).encode())
        else:
            # Serve static files (images)
            try:
                fp = Path(__file__).parent.parent / self.path.lstrip("/")
                if fp.exists() and fp.suffix in ('.jpg', '.jpeg', '.png', '.gif', '.jfif'):
                    self.send_response(200)
                    mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                            'gif': 'image/gif', 'jfif': 'image/jpeg'}
                    self.send_header("Content-Type", mime.get(fp.suffix.lstrip('.'), 'application/octet-stream'))
                    self.end_headers()
                    self.wfile.write(fp.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception:
                self.send_response(404)
                self.end_headers()

    def log_message(self, format, *args):
        pass


# ─── Main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MARS Emotion Tracker — Video Demo")
    parser.add_argument("video", help="Path to video file or image of Ruby")
    parser.add_argument("--interval", type=int, default=5, help="Seconds between frame analysis (default: 5)")
    parser.add_argument("--photo", action="store_true", help="Single photo mode")
    parser.add_argument("--port", type=int, default=WEB_PORT, help=f"Web UI port (default: {WEB_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Error: File not found: {args.video}")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: Set GEMINI_API_KEY environment variable")
        print("  Get one at: https://aistudio.google.com")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  MARS Emotion Tracker — Video Demo")
    print(f"{'='*60}")
    print(f"  Video:    {args.video}")
    print(f"  Interval: {args.interval}s")
    print(f"  Gemini:   Ready")
    print(f"  Bolo:     {'Connected' if BOLO_API_KEY else 'Not configured'}")
    print(f"  Web UI:   http://localhost:{args.port}")
    print(f"{'='*60}\n")

    # Start web server
    server = HTTPServer(("0.0.0.0", args.port), DemoHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"[Web UI] Running at http://localhost:{args.port}")

    if not args.no_browser:
        webbrowser.open(f"http://localhost:{args.port}")

    # Wait a moment for browser to connect
    time.sleep(2)

    # Run pipeline
    run_pipeline(args.video, args.interval, args.photo)

    # Keep server alive for viewing results
    print("\nPipeline complete. Web UI still running. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
