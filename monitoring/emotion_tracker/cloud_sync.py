"""Push MARS events to Bolo cloud so Red Rover can read from anywhere.

Runs in a background thread. Polls the local event_log and pushes
new events to Bolo's widget events API.

Also pushes the latest score and mood as separate event types
so the app can read them without hitting the robot directly.
"""

import json
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

from .event_log import get_events


BOLO_API_KEY = os.environ.get("BOLO_API_KEY", "")
BOLO_BASE_URL = os.environ.get("BOLO_BASE_URL", "https://api.bolospot.com")
WIDGET_SLUG = "mars"
SYNC_INTERVAL = 10  # seconds


def _push_events(events: list[dict]):
    """Push events to Bolo widget events API."""
    if not BOLO_API_KEY or not events:
        return

    url = f"{BOLO_BASE_URL}/api/widget-events/{WIDGET_SLUG}/events/key"
    payload = json.dumps({
        "events": [
            {"eventType": e.get("type", "activity"), "data": e}
            for e in events
        ]
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {BOLO_API_KEY}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"[Cloud Sync] Push failed: {e}")
        return None


def push_score(score_data: dict):
    """Push a score update to Bolo (call from the monitor after each score)."""
    if not BOLO_API_KEY:
        return
    _push_events([{**score_data, "type": "score", "timestamp": datetime.now().isoformat()}])


def push_mood(mood_data: dict):
    """Push a mood update to Bolo (call from the monitor after each mood change)."""
    if not BOLO_API_KEY:
        return
    _push_events([{**mood_data, "type": "mood", "timestamp": datetime.now().isoformat()}])


def _sync_loop():
    """Background loop: push new local events to Bolo."""
    last_sync_count = 0

    while True:
        try:
            # Get recent local events
            local_events = get_events(limit=20)

            # Only push if there are new events since last sync
            if len(local_events) != last_sync_count and local_events:
                result = _push_events(local_events)
                if result:
                    last_sync_count = len(local_events)
        except Exception as e:
            print(f"[Cloud Sync] Error: {e}")

        time.sleep(SYNC_INTERVAL)


def start_cloud_sync():
    """Start the background sync thread. Non-fatal if Bolo isn't configured."""
    if not BOLO_API_KEY:
        print("[Cloud Sync] No BOLO_API_KEY — cloud sync disabled")
        return

    thread = threading.Thread(target=_sync_loop, daemon=True)
    thread.start()
    print(f"[Cloud Sync] Pushing events to Bolo every {SYNC_INTERVAL}s")
