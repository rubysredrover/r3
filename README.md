# Ruby's Red Rover

**An always-on emotion awareness system for the Innate MARS robot — built for people who communicate differently.**

Ruby's Red Rover gives MARS the ability to see a person, recognize who they are, read their emotional state, and remember how they've been feeling over time. It was designed from day one for people with cerebral palsy and other motor disabilities, where standard emotion detection fails because it mistakes involuntary muscle movements for emotional expressions.

This isn't a demo. It's a tool that watches, learns, and adapts — scanning more frequently when it detects distress, backing off when things are stable, and building a longitudinal mood record that caregivers and researchers can use.

---

## What It Does

**Sees you.** MARS captures frames from its onboard RGBD camera.

**Knows you.** Local face recognition (on-device, no cloud) generates a 128-dimensional face embedding. If MARS has seen you before, it identifies you in milliseconds — no API call needed.

**Reads you.** The frame is sent to Google Gemini Vision with a prompt specifically tuned for people with motor disabilities. It distinguishes spasticity from anger, fatigue from sadness, motor frustration from emotional distress.

**Remembers you.** Every observation is logged — who, what emotion, what cues, when. The first time MARS meets someone, it asks their name. Every time after that, it knows.

**Shows you.** Colored Reachy Mini LEDs on top of MARS act as Ruby's **mood ring**. Walk into the room and get an instant vibe check — no screen, no app, just color.

| Color | Meaning |
|---|---|
| Warm yellow | Happy |
| Soft green | Content |
| Calm blue | Relaxed |
| Lavender | Neutral |
| Deep blue | Sad |
| Muted purple | Tired |
| Amber-orange | Stressed |
| Red (pulsing) | In pain |
| Red-orange (pulsing) | Frustrated |

Mom walks in at 3pm. The lights are soft green. She knows Ruby's having a good afternoon — without asking, without interrupting.

**Tells you.** Ask MARS "how was Ruby's day?" and it generates a natural language summary from the mood log:

> *"Ruby was mostly content today (68% of readings). There were 3 readings showing concern (frustrated, tired), starting around 2:15pm. Mood changed 4 times throughout the day. Last reading at 4:30pm: happy."*

**Adapts.** The scan frequency adjusts in real time:

| State | Scan Interval | Why |
|---|---|---|
| No one in frame | 10s | Save resources |
| Stable mood (3+ same readings) | 30s | Nothing to catch |
| Mood just changed | 10s | Track the shift |
| Distress detected | 5s | Don't miss anything |

---

## Architecture

```
                    MARS Robot (Jetson Orin Nano 8GB)
                    ================================

  RGBD Camera
      │
      v
  ┌─────────────────────────────────────────────────┐
  │  EmotionMonitor (always-on loop)                │
  │                                                  │
  │  FAST PATH (on-device, free, instant)           │
  │  Frame ──> inspireface                           │
  │              ├─ Face ID (who is this?)           │
  │              └─ Basic emotion                    │
  │                                                  │
  │  DEEP PATH (cloud, CP-aware, on mood change)    │
  │  Frame ──> Gemini Vision API                     │
  │              └─ "Is that grimace pain or         │
  │                  spasticity? Fatigue or sadness?" │
  │                    │                             │
  │                    v                             │
  │              PersonRegistry (SQLite)             │
  │              mood logged + adaptive timing       │
  │                    │                             │
  │                    v                             │
  │              MoodRing (Reachy Mini LEDs)         │
  │              "Ruby's ambient mood ring"          │
  └─────────────────────────────────────────────────┘
```

**Two-tier detection.** inspireface (already on MARS) handles face identity and basic emotion entirely on-device — zero API calls, zero latency. Gemini is only called when the mood changes or distress is detected, for CP-aware nuance that standard models miss. This cuts API usage by ~80% while keeping the deep analysis where it matters.

---

## Quick Start

### 1. Get your Gemini API key

Go to [Google AI Studio](https://aistudio.google.com), create a key.

### 2. Deploy to MARS

```bash
git clone https://github.com/YOUR_ORG/rubysredrover.git
cd rubysredrover
bash deploy.sh
```

### 3. Run it

```bash
ssh jetson1@mars-the-38th.local
cd ~/emotion_tracker
export GEMINI_API_KEY="your-key"
python3 run.py
```

MARS will start scanning. When it sees someone new, it'll ask for their name. After that, it remembers.

---

## For Engineers: Consuming Emotion Data

The person registry is a SQLite database at `~/emotion_tracker/people.db`. Your agent actions can query it directly:

```python
from emotion_tracker.person_registry import PersonRegistry
from emotion_tracker.mood_summary import summarize_day

with PersonRegistry() as reg:
    # who's the primary person we're tracking?
    primary = reg.get_primary_person()
    
    # what's their mood right now?
    mood = reg.get_last_mood(primary["id"])
    print(f"{primary['name']} is feeling {mood['emotion']}")
    
    # "how was Ruby's day?"
    summary = summarize_day(reg, primary["id"])
    print(summary["summary"])
    # → "Ruby was mostly content today (68% of readings). There were 3 readings
    #    showing concern (frustrated, tired), starting around 2:15pm..."
    
    # raw mood history
    history = reg.get_mood_history(primary["id"], limit=20)
    for entry in history:
        print(f"  {entry['timestamp']}: {entry['emotion']} ({entry['context']})")
```

### Database schema

**people**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER | Primary key |
| name | TEXT | Their name |
| description | TEXT | Physical description from Gemini |
| face_embedding | BLOB | 128-dim face vector (local recognition) |
| is_primary | INTEGER | 1 = actively tracked person |
| created_at | TEXT | ISO timestamp |

**mood_log**
| Column | Type | Notes |
|---|---|---|
| person_id | INTEGER | FK to people |
| emotion | TEXT | happy, sad, tired, in_pain, frustrated, etc. |
| confidence | TEXT | high / medium / low |
| context | TEXT | "grimacing but eyes engaged" — the why behind the label |
| timestamp | TEXT | ISO timestamp |

---

## CP-Aware Emotion Detection

Standard emotion detection systems are trained on neurotypical expressions. They see spasticity and label it anger. They see fatigue and call it sadness. For someone with cerebral palsy, that's worse than useless.

Ruby's Red Rover prompts the vision model to:

- Distinguish involuntary muscle movements from emotional expressions
- Look beyond facial muscles — body tension, breathing, eye engagement
- Separate motor frustration from emotional distress
- Recognize fatigue and pain as distinct states, not subcategories of "sad"
- Include extended emotion labels: `in_pain`, `uncomfortable`, `frustrated`, `relaxed`

This isn't perfect. Vision models still have bias. But it's a starting point that acknowledges the problem instead of ignoring it.

---

## Red Rover — Mom's App

Red Rover is the companion web app that lets Mom (or any authorized caregiver) check on Ruby from her phone.

- Live mood ring — matches the physical LEDs on MARS
- "Where's Ruby?" — presence status at a glance
- "Find My Ruby" — activates beacon lights/sounds on the robot
- Today's mood timeline — every reading, with context
- Day summary — natural language narrative ("Ruby was mostly content today...")
- Access management — powered by Bolo grants (coming soon in UI)

Red Rover talks to the MARS API running on the Jetson (port 8080).

Lives in the sibling repo: `rubysredrover-app/`

---

## Bolo Integration — Who Can Check On Ruby

[Bolospot](https://bolospot.com) is the trust layer. Mom controls who can access Ruby's data.

MARS is registered as a Bolo widget (slug: `mars`). Mom creates grants to give people specific access — PCA Jane gets `mood:read` + `location:status`, Grandma gets `mood:read` only. At runtime, every skill checks Bolo before returning data. Non-transitive: if Mom grants Jane access, Jane can't pass it along.

**Scopes:** `mood:read`, `mood:history`, `mood:notify`, `location:status`, `location:beacon`, `person:register`, `person:list`, `settings:manage`

See [BOLO.md](BOLO.md) for full integration docs — grant examples, runtime checks, environment variables.

---

## Project Structure

```
rubysredrover/                          # MARS robot code
├── run.py                              # entry point (monitor + API server)
├── deploy.sh                           # one-command deploy to MARS
├── register_widget.js                  # register MARS as Bolo widget
├── requirements.txt
├── MARS_SETUP.md                       # what's on the robot (keep updated!)
├── skills/                             # → ~/skills/ on robot (BASIC auto-discovers)
│   ├── check_mood.py                   # "How is Ruby feeling?"
│   ├── day_summary.py                  # "How was Ruby's day?"
│   └── find_ruby.py                    # "Where's Ruby?" + beacon
└── emotion_tracker/                    # → ~/emotion_tracker/ on robot
    ├── camera.py                       # ROS2 topic subscriber (innate-os native)
    ├── detector.py                     # abstract EmotionDetector interface
    ├── gemini_detector.py              # CP-aware deep analysis (Gemini)
    ├── face_encoder.py                 # inspireface on-device (face ID + basic emotion)
    ├── person_registry.py              # SQLite: people + embeddings + mood log
    ├── monitor.py                      # always-on, two-tier, adaptive timing
    ├── mood_ring.py                    # Reachy Mini LED mood colors
    ├── mood_summary.py                 # "how was Ruby's day?" narratives
    ├── find_ruby.py                    # presence tracking + beacon + text Mom
    ├── bolo_guard.py                   # Bolo permission checks (runtime)
    └── api.py                          # HTTP API for Red Rover (port 8080)

rubysredrover-app/                      # Red Rover — Mom's web app
├── src/App.tsx                         # React UI
├── src/App.css                         # Dark theme, mobile-first
└── ...                                 # Vite + TypeScript
```

---

## Future: On-Device Inference

The architecture is ready. When you want to stop calling the cloud:

1. Create `local_detector.py` implementing `EmotionDetector`
2. Load your model on the Jetson GPU (TensorRT, ONNX, whatever)
3. In `run.py`, swap `GeminiDetector()` for `LocalDetector()`
4. Everything else stays the same

Zero bandwidth. Zero latency. Zero API cost. Same interface.

## Future: Anima Engine (Text-Based Emotion)

[Anima](https://github.com/brainwavecollective/anima-engine) is a two-loop emotion extraction engine for text input. It could complement vision-based detection by analyzing Ruby's *words* alongside her facial cues — especially valuable when CP makes facial expressions unreliable. Face + voice + text = three signals triangulating on the truth.

---

## Built With

- [Innate MARS](https://www.innate.bot/) — the robot (innate-os 0.5.0-rc10)
- [Google Gemini 2.0 Flash](https://aistudio.google.com) — CP-aware emotion analysis (cloud, called only on mood changes)
- [InspireFace](https://github.com/HyperInspire/InspireFace) — on-device face recognition + basic emotion (pre-installed on MARS)
- [OpenCV](https://opencv.org/) — camera capture (pre-installed on MARS)
- SQLite — because it's on a robot and it just works
- **Zero new packages installed on the robot** — everything was already there

---

*Built at the Google DeepMind Hackathon, April 2026.*
