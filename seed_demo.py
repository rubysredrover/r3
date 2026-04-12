#!/usr/bin/env python3
"""Seed people.db with a realistic day of Ruby's mood data.

Run on the robot:
  python3 seed_demo.py

Creates Ruby as the primary person and populates a full day
of mood readings that tell a story.
"""

import sqlite3
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

conn.commit()
conn.close()

print(f"Seeded {len(moods)} mood readings for Ruby")
print(f"DB: {DB_PATH}")
