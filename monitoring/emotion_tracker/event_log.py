"""Event log: records what MARS does so Red Rover can show live activity.

Skills call log_event() when they execute. Red Rover polls /api/events.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "mars_tracker.db"


def _get_conn(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            type TEXT NOT NULL,
            icon TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def log_event(action: str, event_type: str = "action", icon: str = "", db_path=None):
    """Log an event from MARS.

    Call this from any skill or the monitor:
        log_event("Picked up pen from desk", "manipulation", "pencil")
        log_event("Navigated to kitchen", "navigation", "walking")
        log_event("Ruby Score: 87", "score", "green_circle")
    """
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT INTO event_log (action, type, icon, timestamp) VALUES (?, ?, ?, ?)",
        (action, event_type, icon, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_events(limit: int = 20, db_path=None) -> list[dict]:
    """Get recent events for Red Rover."""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT action, type, icon, timestamp FROM event_log ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
