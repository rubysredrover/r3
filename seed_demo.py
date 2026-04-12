#!/usr/bin/env python3
"""Seed people.db with a realistic day of Ruby's mood data.

Run on the robot:
  python3 seed_demo.py

Creates Ruby as the primary person and populates a full day
of mood readings that tell a story.
"""

import sqlite3
import random
from datetime import datetime

DB_PATH = "/home/jetson1/emotion_tracker/people.db"

conn = sqlite3.connect(DB_PATH)
conn.executescript("""
    CREATE TABLE IF NOT EXISTS people (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        face_embedding BLOB,
        is_primary INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS mood_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        emotion TEXT NOT NULL,
        confidence TEXT,
        context TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (person_id) REFERENCES people(id)
    );
    CREATE TABLE IF NOT EXISTS ruby_score_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        eye_contact REAL NOT NULL,
        volume REAL NOT NULL,
        response_latency REAL NOT NULL,
        score INTEGER NOT NULL,
        level TEXT NOT NULL,
        label INTEGER,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (person_id) REFERENCES people(id)
    );
""")

# Register Ruby as primary person
conn.execute("""
    INSERT OR IGNORE INTO people (id, name, description, is_primary, created_at)
    VALUES (1, 'Ruby', 'Brown wavy hair, mid-twenties, bright eyes, often in hoodie', 1, ?)
""", (datetime.now().isoformat(),))

# Clear old mood data
conn.execute("DELETE FROM mood_log WHERE person_id = 1")

# A realistic day for Ruby
today = datetime.now().strftime("%Y-%m-%d")
moods = [
    ("09:00", "happy",     "high",   "smiling, animated gestures, strong eye contact"),
    ("09:15", "happy",     "high",   "laughing, bright eyes, fast responses"),
    ("09:35", "content",   "high",   "relaxed posture, steady breathing"),
    ("10:00", "content",   "high",   "calm, engaged in conversation"),
    ("10:30", "content",   "medium", "relaxed posture, steady gaze"),
    ("11:00", "neutral",   "medium", "steady gaze, moderate engagement"),
    ("11:30", "tired",     "medium", "drooping eyelids, slower movement"),
    ("11:45", "tired",     "high",   "slower responses, lower volume"),
    ("12:15", "content",   "medium", "eating lunch, relaxed"),
    ("12:45", "happy",     "high",   "animated, telling a story"),
    ("13:00", "content",   "high",   "post-lunch, calm"),
    ("13:30", "neutral",   "medium", "steady but quieter"),
    ("14:00", "frustrated","high",   "motor difficulty with task — NOT emotional, eyes still engaged"),
    ("14:15", "frustrated","high",   "continued motor struggle — body tense but eye contact steady"),
    ("14:30", "tired",     "medium", "resting after effort, low energy"),
    ("14:45", "neutral",   "medium", "recovering, breathing normalized"),
    ("15:00", "content",   "medium", "watching something, relaxed"),
    ("15:30", "content",   "high",   "relaxed posture, steady eye contact"),
    ("15:45", "happy",     "high",   "laughing at something, volume up"),
    ("16:00", "happy",     "high",   "bright eyes, fast replies, engaged"),
    ("16:15", "content",   "high",   "winding down, still engaged"),
    ("16:30", "content",   "high",   "calm breathing, relaxed"),
    ("16:45", "content",   "high",   "steady, comfortable"),
]

for time_str, emotion, confidence, context in moods:
    ts = f"{today}T{time_str}:00"
    conn.execute(
        "INSERT INTO mood_log (person_id, emotion, confidence, context, timestamp) VALUES (1, ?, ?, ?, ?)",
        (emotion, confidence, context, ts)
    )

# --- Ruby Score signal profiles per emotion ---
# Maps emotion → (eye_contact_range, volume_range, response_latency_range, label_range)
# These reflect Ruby's real patterns: CP means motor signals ≠ emotional signals
signal_profiles = {
    "happy":      ((0.5, 0.75), (0.45, 0.65), (1.5, 2.5), (80, 95)),
    "content":    ((0.35, 0.55), (0.30, 0.45), (2.0, 3.5), (65, 80)),
    "neutral":    ((0.25, 0.45), (0.25, 0.40), (2.5, 4.0), (50, 65)),
    "tired":      ((0.15, 0.30), (0.15, 0.25), (4.0, 6.0), (30, 45)),
    "frustrated": ((0.30, 0.50), (0.35, 0.55), (3.0, 5.0), (35, 55)),
    # frustrated has STEADY eye contact — it's motor, not emotional for Ruby
}

random.seed(42)  # reproducible

def jitter(low, high):
    return round(random.uniform(low, high), 3)

conn.execute("DELETE FROM ruby_score_log WHERE person_id = 1")

for time_str, emotion, confidence, context in moods:
    ts = f"{today}T{time_str}:00"
    profile = signal_profiles.get(emotion, signal_profiles["neutral"])
    eye_r, vol_r, lat_r, label_r = profile

    eye_contact = jitter(*eye_r)
    volume = jitter(*vol_r)
    response_latency = jitter(*lat_r)
    label = random.randint(*label_r)

    # compute score from hand-tuned weights (same as RubyScoreEngine v0)
    eye_score = min(eye_contact / 0.6, 1.0)
    vol_score = min(volume / 0.525, 1.0)
    spd_score = min(3.0 / max(response_latency, 0.1), 1.0)
    raw = eye_score * 0.45 + vol_score * 0.25 + spd_score * 0.30
    score = max(0, min(100, int(round(raw * 100))))

    if score >= 80: level = "great"
    elif score >= 60: level = "okay"
    elif score >= 40: level = "quiet"
    elif score >= 20: level = "withdrawn"
    else: level = "alert"

    conn.execute(
        """INSERT INTO ruby_score_log
           (person_id, eye_contact, volume, response_latency, score, level, label, timestamp)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (eye_contact, volume, response_latency, score, level, label, ts)
    )

conn.commit()
conn.close()

print(f"Seeded {len(moods)} mood readings for Ruby")
print(f"Seeded {len(moods)} ruby_score signals (with caregiver labels)")
print(f"DB: {DB_PATH}")
