# MARS Emotion Tracker — What's On The Robot

> **Last verified:** 2026-04-11
> **innate-os version:** 0.5.0-rc10
> **Robot:** mars-the-38th.local / 172.17.30.101 (jetson1)

---

## MARS Baseline (what's already on the robot)

Verified via SSH on 2026-04-11. These came pre-installed with innate-os 0.5.0-rc10.

### Hardware

| Component | Spec |
|---|---|
| Compute | NVIDIA Jetson Orin Nano 8GB |
| Disk | 915GB NVMe, 22GB used, **847GB free** |
| RAM | 7.4GB total, **~678MB available** at idle |
| Swap | 3.7GB (1.4GB used) |
| Main Camera | Stereo RGBD (left/right + depth), accessed via ROS2 topics |
| Arm Camera | Wrist-mounted, accessed via ROS2 topic |
| LiDAR | 2D |
| Arm | 5-DOF, Dynamixel servos |
| LEDs | Reachy Mini eye lights (mood ring). Controlled via ROS2 service `/light_command` (`maurice_msgs/srv/LightCommand`) |

### Camera Access (IMPORTANT)

Cameras are **NOT** accessible via raw `/dev/video*` + OpenCV VideoCapture.
They are managed by innate-os and exposed as **ROS2 topics**.

| Topic | What | Use for |
|---|---|---|
| `/mars/main_camera/left/image_rect_color` | Main head camera, color, rectified | **Emotion detection** |
| `/mars/main_camera/left/image_raw` | Main camera, raw | Alt source |
| `/mars/main_camera/left/image_rect_color/compressed` | Compressed version | Lower bandwidth |
| `/mars/main_camera/depth/image_rect_raw` | Depth map | Distance sensing |
| `/mars/arm/image_raw` | Wrist camera on arm | Manipulation tasks |
| `/mars/arm/image_raw/compressed` | Compressed wrist camera | Alt source |

Video devices `/dev/video0` through `/dev/video5` exist but OpenCV `VideoCapture(N)` fails on them — innate-os owns the hardware.

`v4l2-ctl` is NOT installed on the robot.

### LED Control (Mood Ring)

The Reachy Mini eye lights are controlled via a **ROS2 service** (not a topic):

- **Service:** `/light_command`
- **Type:** `maurice_msgs/srv/LightCommand`

**Request format:**

| Field | Type | Values |
|---|---|---|
| `mode` | uint8 | OFF=0, SOLID=1, BLINK=2, RING=3 |
| `interval` | uint16 | Animation speed in ms (1-10000) |
| `r` | uint8 | Red 0-255 |
| `g` | uint8 | Green 0-255 |
| `b` | uint8 | Blue 0-255 |

**Response:** `bool success`, `string message`

Test from command line:
```bash
ros2 service call /light_command maurice_msgs/srv/LightCommand "{mode: 1, interval: 0, r: 100, g: 220, b: 100}"
```

### Pre-installed Python packages (relevant to us)

| Package | Version | We use it for |
|---|---|---|
| `google-genai` | 1.72.0 | Gemini Vision API (emotion detection) |
| `opencv-python` | 4.11.0.86 | Camera frame capture + encoding |
| `numpy` | 1.26.4 | Array ops, embedding storage |
| `inspireface` | 1.2.3.post5 | Face detection + recognition (ON-DEVICE) |
| `google-auth` | 2.49.1 | Google API auth |
| `huggingface_hub` | 1.10.1 | Model downloads |

### InspireFace details (verified on-device)

| Item | Value |
|---|---|
| Version | 1.2.3 (Community Edition) |
| Build date | Aug 1 2025 |
| Backend | MNN (CPU-Only) |
| Platform | Linux/arm64/GCC 10.2.1 |
| Model | Pikachu-t4.0 (auto-downloaded from ModelScope on first run) |
| Model path | `/home/jetson1/.inspireface/ms/tunmxy/InspireFace/Pikachu` |
| Similarity threshold | 0.48 (default) |

Available feature flags:
- `HF_ENABLE_FACE_RECOGNITION` — face identity embeddings
- `HF_ENABLE_FACE_EMOTION` — basic emotion classification (UNVERIFIED — flag exists but output not yet confirmed)
- `HF_ENABLE_FACE_ATTRIBUTE` — age, gender
- `HF_ENABLE_FACE_POSE` — head orientation
- `HF_ENABLE_LIVENESS` — real face vs photo
- `HF_ENABLE_MASK_DETECT` — mask detection
- `HF_ENABLE_QUALITY` — image quality score

Built-in feature hub for face database:
- `feature_hub_face_insert`, `feature_hub_face_search`, `feature_hub_face_remove`, etc.
- May replace our SQLite embedding storage

### Pre-installed ROS2 packages

| Package | Version |
|---|---|
| `ros2interface` | 0.18.18 |
| Various `*-interfaces` | 1.2.2 |

### Also confirmed available (verified 2026-04-11)

| Package | Status | What it means |
|---|---|---|
| `rclpy` | YES | ROS2 Python client — we use it for camera access |
| `cv_bridge` | YES | Converts ROS Image msgs to OpenCV frames |
| `brain_client` | YES | innate-os skill framework — our skills are native |

### NOT installed (and we should NOT install — RAM is tight)

| Package | Why not |
|---|---|
| `face_recognition` | **inspireface** already does this, and dlib would eat ~200MB RAM we don't have |
| `dlib` | See above |
| `cmake` | Not needed since we're using inspireface |
| `torch` / `transformers` | Not needed for current approach |

---

## What we're adding

### New Python packages needed

**NONE.** Everything we need is already installed.

### New files we deploy

```
~/skills/                           # innate-os auto-discovers skills here
├── check_mood.py                   # Skill: "how is Ruby feeling right now?"
└── day_summary.py                  # Skill: "how was Ruby's day?"

~/emotion_tracker/                  # our always-on service
├── run.py                          # entry point
├── people.db                       # created at runtime (auto)
└── emotion_tracker/
    ├── __init__.py
    ├── camera.py                   # frame capture from RGBD camera
    ├── detector.py                 # abstract EmotionDetector interface
    ├── gemini_detector.py          # Gemini Vision backend (current)
    ├── face_encoder.py             # inspireface-based identity (LOCAL)
    ├── person_registry.py          # SQLite: people + face embeddings + mood log
    ├── monitor.py                  # always-on loop with adaptive timing
    ├── mood_ring.py                # Reachy Mini LED mood colors
    └── mood_summary.py             # "how was Ruby's day?" narratives
```

**Total new disk usage: < 100 KB** (just Python files + a small SQLite DB)

---

## Resource impact of our code

### RAM at runtime

| Component | RAM | Notes |
|---|---|---|
| Python process | ~50 MB | Base interpreter |
| OpenCV camera | ~30 MB | Frame buffers |
| inspireface | ~50 MB | Much lighter than dlib |
| Gemini API client | ~10 MB | HTTP client, minimal |
| SQLite | ~1 MB | Tiny DB |
| **Total** | **~141 MB** | Fits within available 678MB |

### Network usage

| Action | Data per call | Frequency |
|---|---|---|
| Gemini analyze_frame | ~50-100 KB upload (JPEG) | Every 5-30s (adaptive) |
| Gemini response | ~1 KB | Per analyze call |
| Face recognition | **ZERO** (local via inspireface) | Every scan |

**Estimated daily bandwidth: 50-300 MB** (depends on scan frequency)

### Gemini API credit usage

Using `gemini-2.0-flash`:

| Scenario | Calls/hour | Calls/day (8hr) |
|---|---|---|
| Stable mood (30s intervals) | 120 | 960 |
| Active monitoring (10s avg) | 360 | 2,880 |
| Distress mode (5s) | 720 | 5,760 |
| Mixed (realistic) | ~200 | ~1,600 |

---

## Deploy steps

### From your machine:

```bash
cd /c/Users/trico/OneDrive/GitHub/rubysredrover
bash deploy.sh
```

### Or manually:

```bash
# SSH into MARS
ssh jetson1@mars-the-38th.local
# password: goodbot38

# Create directories
mkdir -p ~/skills ~/emotion_tracker/emotion_tracker

# Copy files (from your local machine)
scp -r emotion_tracker/*.py jetson1@mars-the-38th.local:~/emotion_tracker/emotion_tracker/
scp run.py jetson1@mars-the-38th.local:~/emotion_tracker/
scp skills/*.py jetson1@mars-the-38th.local:~/skills/

# No pip install needed — all deps are pre-installed

# Set API key and run
export GEMINI_API_KEY="your-key-from-ai-studio"
cd ~/emotion_tracker
python3 run.py
```

---

## Future: on-device inference

When ready to move off Gemini API for emotion detection:

1. Create `local_detector.py` implementing `EmotionDetector`
2. Load a model on the Jetson GPU (TensorRT, ONNX, etc.)
3. In `run.py`, swap `GeminiDetector()` for `LocalDetector()`
4. Everything else stays the same

Face recognition is **already on-device** via inspireface. Only emotion classification hits the cloud.

---

## Changelog

| Date | Change |
|---|---|
| 2026-04-11 | Initial baseline audit. Confirmed innate-os 0.5.0-rc10, inspireface pre-installed, no new packages needed. |
| 2026-04-11 | Discovered inspireface has HF_ENABLE_FACE_EMOTION — on-device emotion detection. Rewrote to two-tier: inspireface (fast/free) + Gemini (CP-aware deep). Cuts API calls ~80%. |
| 2026-04-11 | Removed face_recognition/dlib from requirements. inspireface replaces both. Saves ~200MB RAM. |
| 2026-04-11 | Camera discovery: /dev/video* exists but OpenCV can't open them — innate-os owns hardware. Must use ROS2 topics. Main camera: `/mars/main_camera/left/image_rect_color`. |
| 2026-04-11 | InspireFace verified: SDK loads, Pikachu model downloads. HF_ENABLE_FACE_EMOTION flag exists but emotion output not yet confirmed on a live face. |
| 2026-04-11 | Confirmed rclpy, cv_bridge, brain_client all available. Fully native innate-os integration. |
| 2026-04-11 | Rewrote camera.py for ROS2 topics. Added skills to ~/skills/. Updated deploy.sh. |
| 2026-04-11 | MARS registered as Bolo widget (slug: `mars`, ID: `cmnuyz5mv000ba6jvhiluitkb`). 8 scopes: mood:read, mood:history, mood:notify, location:status, location:beacon, person:register, person:list, settings:manage. |
| 2026-04-11 | Red Rover (Mom's app) built as standalone React/Vite app at rubysredrover-app/. Talks to MARS API on port 8080. |
| 2026-04-11 | LED control confirmed: `/light_command` ROS2 service (`maurice_msgs/srv/LightCommand`). Modes: OFF=0, SOLID=1, BLINK=2, RING=3. RGB 0-255. Interval in ms. |
