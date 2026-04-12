"""SQLite-based person registry with face embeddings and mood history."""

import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np


DB_PATH = Path(__file__).parent.parent / "people.db"


class PersonRegistry:
    """Stores known people (with face embeddings) and their mood history."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.conn = None

    def open(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
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
        self.conn.commit()

    def register_person(self, name, description, face_embedding=None, is_primary=False):
        """Register a new person with their description and optional face embedding."""
        blob = face_embedding.tobytes() if face_embedding is not None else None
        cursor = self.conn.execute(
            "INSERT INTO people (name, description, face_embedding, is_primary, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, description, blob, int(is_primary), datetime.now().isoformat())
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_face_embedding(self, person_id, face_embedding):
        """Update face embedding for an existing person."""
        self.conn.execute(
            "UPDATE people SET face_embedding = ? WHERE id = ?",
            (face_embedding.tobytes(), person_id)
        )
        self.conn.commit()

    def set_primary(self, person_id):
        """Set a person as the primary person to track."""
        self.conn.execute("UPDATE people SET is_primary = 0")
        self.conn.execute("UPDATE people SET is_primary = 1 WHERE id = ?", (person_id,))
        self.conn.commit()

    def get_primary_person(self):
        """Get the primary person being tracked."""
        cursor = self.conn.execute(
            "SELECT id, name, description, face_embedding, is_primary FROM people WHERE is_primary = 1"
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_person(row)

    def log_mood(self, person_id, emotion, confidence=None, context=None):
        """Log a mood observation for a person."""
        self.conn.execute(
            "INSERT INTO mood_log (person_id, emotion, confidence, context, timestamp) VALUES (?, ?, ?, ?, ?)",
            (person_id, emotion, confidence, context, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_all_people(self):
        """Return all registered people."""
        cursor = self.conn.execute("SELECT id, name, description, face_embedding, is_primary FROM people")
        return [self._row_to_person(row) for row in cursor.fetchall()]

    def get_all_face_embeddings(self):
        """Return all people who have face embeddings stored."""
        cursor = self.conn.execute(
            "SELECT id, face_embedding FROM people WHERE face_embedding IS NOT NULL"
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "person_id": row["id"],
                "embedding": np.frombuffer(row["face_embedding"], dtype=np.float64),
            })
        return results

    def get_person(self, person_id):
        """Get a single person by ID."""
        cursor = self.conn.execute(
            "SELECT id, name, description, face_embedding, is_primary FROM people WHERE id = ?",
            (person_id,)
        )
        row = cursor.fetchone()
        return self._row_to_person(row) if row else None

    def log_ruby_score(self, person_id, eye_contact, volume, response_latency,
                        score, level, label=None):
        """Log a Ruby Score reading with raw signals."""
        self.conn.execute(
            """INSERT INTO ruby_score_log
               (person_id, eye_contact, volume, response_latency, score, level, label, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (person_id, eye_contact, volume, response_latency, score, level,
             label, datetime.now().isoformat())
        )
        self.conn.commit()

    def label_ruby_score(self, score_id, label):
        """Caregiver labels a score reading (0-100) for training."""
        self.conn.execute(
            "UPDATE ruby_score_log SET label = ? WHERE id = ?",
            (label, score_id)
        )
        self.conn.commit()

    def get_training_data(self):
        """Query all labeled Ruby Score readings for model training."""
        cursor = self.conn.execute(
            """SELECT eye_contact, volume, response_latency, label
               FROM ruby_score_log
               WHERE label IS NOT NULL
               ORDER BY timestamp"""
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_ruby_score_history(self, person_id, limit=50):
        """Get recent Ruby Score readings."""
        cursor = self.conn.execute(
            """SELECT id, eye_contact, volume, response_latency, score, level, label, timestamp
               FROM ruby_score_log WHERE person_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (person_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_last_ruby_score(self, person_id):
        """Get the most recent Ruby Score for a person."""
        cursor = self.conn.execute(
            """SELECT score, level, eye_contact, volume, response_latency, timestamp
               FROM ruby_score_log WHERE person_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (person_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def check_alert_condition(self, person_id, window=5):
        """Query recent scores to decide if Mom should be alerted.

        Returns dict with:
          - should_alert: bool
          - reason: why (or None)
          - score: current score
          - level: current level
          - trend: improving / declining / stable
        """
        rows = self.conn.execute(
            """SELECT score, level, timestamp
               FROM ruby_score_log WHERE person_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (person_id, window)
        ).fetchall()

        if not rows:
            return {"should_alert": False, "reason": None, "score": None,
                    "level": None, "trend": "insufficient_data"}

        current = dict(rows[0])
        scores = [r["score"] for r in rows]

        # trend calculation
        if len(scores) >= 2:
            first_half = sum(scores[len(scores)//2:]) / max(len(scores)//2, 1)
            second_half = sum(scores[:len(scores)//2]) / max(len(scores)//2, 1)
            diff = second_half - first_half
            if diff > 10:
                trend = "improving"
            elif diff < -10:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        should_alert = False
        reason = None

        # ALERT: score in critical zone
        if current["score"] < 20:
            should_alert = True
            reason = f"score critically low ({current['score']})"

        # ALERT: sustained withdrawn (3+ consecutive readings below 40)
        elif len(scores) >= 3 and all(s < 40 for s in scores[:3]):
            should_alert = True
            reason = f"withdrawn for {len([s for s in scores if s < 40])} consecutive readings"

        # ALERT: rapid decline (dropped 30+ points in the window)
        elif len(scores) >= 2 and (scores[-1] - scores[0]) > 30:
            should_alert = True
            reason = f"rapid decline ({scores[-1]} -> {scores[0]})"

        return {
            "should_alert": should_alert,
            "reason": reason,
            "score": current["score"],
            "level": current["level"],
            "trend": trend,
        }

    def get_score_for_color(self, person_id):
        """Query to determine what color the Reachy lights should show.

        Returns dict with:
          - score: 0-100
          - level: great/okay/quiet/withdrawn/alert
          - mode: solid or blink
          - color: (r, g, b) tuple for API consumers
          - fw_color: firmware color name (GREEN/CYAN/AMBER/MAGENTA/RED)
        """
        current = self.get_last_ruby_score(person_id)
        if not current:
            return None

        score = current["score"]
        level = current["level"]

        # Score-driven color mapping
        # App hex colors align with Tailwind palette used in Red Rover app
        # fw_color = reachy_eyes firmware named color for the physical eyes
        if score >= 80:
            color = (34, 197, 94)       # #22c55e — green-500
            fw_color = "GREEN"
            mode = "solid"
        elif score >= 60:
            color = (59, 130, 246)      # #3b82f6 — blue-500
            fw_color = "CYAN"
            mode = "solid"
        elif score >= 40:
            color = (234, 179, 8)       # #eab308 — yellow-500
            fw_color = "AMBER"
            mode = "solid"
        elif score >= 20:
            color = (168, 85, 247)      # #a855f7 — purple-500
            fw_color = "MAGENTA"
            mode = "blink"
        else:
            color = (239, 68, 68)       # #ef4444 — red-500
            fw_color = "RED"
            mode = "blink"

        return {
            "score": score,
            "level": level,
            "mode": mode,
            "color": color,
            "fw_color": fw_color,
        }

    def get_mood_history(self, person_id, limit=10):
        """Get recent mood history for a person."""
        cursor = self.conn.execute(
            "SELECT emotion, confidence, context, timestamp FROM mood_log WHERE person_id = ? ORDER BY timestamp DESC LIMIT ?",
            (person_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_last_mood(self, person_id):
        """Get the most recent mood for a person."""
        history = self.get_mood_history(person_id, limit=1)
        return history[0] if history else None

    def _row_to_person(self, row):
        person = dict(row)
        if person.get("face_embedding"):
            person["face_embedding"] = np.frombuffer(person["face_embedding"], dtype=np.float64)
        return person

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
