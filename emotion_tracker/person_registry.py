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
