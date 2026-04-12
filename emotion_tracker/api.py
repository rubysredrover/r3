"""Simple HTTP API for Red Rover (Mom's app) to talk to MARS.

Runs on the Jetson alongside the emotion monitor.
Red Rover (React app) calls these endpoints.

Endpoints:
  GET  /api/mood           — Ruby's current mood + mood ring color
  GET  /api/mood/history   — mood log for today
  GET  /api/mood/summary   — "how was Ruby's day?" narrative
  GET  /api/status         — where's Ruby? presence + last seen
  POST /api/beacon         — activate Find My Ruby lights/sounds
  GET  /api/people         — list registered people
  GET  /api/health         — is the emotion tracker running?
"""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from .person_registry import PersonRegistry
from .mood_summary import summarize_day
from .mood_ring import MOOD_COLORS

# shared state — updated by the monitor
_state = {
    "is_running": False,
    "current_emotion": None,
    "in_frame": False,
    "last_seen": None,
    "primary_person_id": None,
}
_state_lock = threading.Lock()


def update_api_state(**kwargs):
    """Called by the monitor to update shared state."""
    with _state_lock:
        _state.update(kwargs)


def get_api_state():
    with _state_lock:
        return dict(_state)


class RedRoverHandler(BaseHTTPRequestHandler):
    """HTTP handler for Red Rover API."""

    def do_GET(self):
        if self.path == "/api/mood":
            self._handle_mood()
        elif self.path == "/api/mood/history":
            self._handle_history()
        elif self.path == "/api/mood/summary":
            self._handle_summary()
        elif self.path == "/api/status":
            self._handle_status()
        elif self.path == "/api/people":
            self._handle_people()
        elif self.path == "/api/health":
            self._handle_health()
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/beacon":
            self._handle_beacon()
        else:
            self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _handle_mood(self):
        state = get_api_state()
        with PersonRegistry() as reg:
            person_id = state.get("primary_person_id")
            if not person_id:
                primary = reg.get_primary_person()
                if not primary:
                    people = reg.get_all_people()
                    primary = people[0] if people else None
                if primary:
                    person_id = primary["id"]

            if not person_id:
                self._send(200, {"mood": None, "message": "No one registered yet."})
                return

            person = reg.get_person(person_id)
            mood = reg.get_last_mood(person_id)

            emotion = mood["emotion"] if mood else "unknown"
            color = MOOD_COLORS.get(emotion, MOOD_COLORS["unknown"])

            self._send(200, {
                "name": person["name"] if person else "Unknown",
                "emotion": emotion,
                "confidence": mood.get("confidence", "") if mood else "",
                "context": mood.get("context", "") if mood else "",
                "timestamp": mood["timestamp"] if mood else None,
                "color": {"r": color[0], "g": color[1], "b": color[2]},
                "in_frame": state.get("in_frame", False),
            })

    def _handle_history(self):
        with PersonRegistry() as reg:
            primary = reg.get_primary_person()
            if not primary:
                people = reg.get_all_people()
                primary = people[0] if people else None
            if not primary:
                self._send(200, {"history": []})
                return
            history = reg.get_mood_history(primary["id"], limit=50)
            self._send(200, {"name": primary["name"], "history": history})

    def _handle_summary(self):
        with PersonRegistry() as reg:
            primary = reg.get_primary_person()
            if not primary:
                people = reg.get_all_people()
                primary = people[0] if people else None
            if not primary:
                self._send(200, {"summary": "No one registered yet."})
                return
            summary = summarize_day(reg, primary["id"])
            self._send(200, summary)

    def _handle_status(self):
        state = get_api_state()
        with PersonRegistry() as reg:
            primary = reg.get_primary_person()
            if not primary:
                people = reg.get_all_people()
                primary = people[0] if people else None

            mood = reg.get_last_mood(primary["id"]) if primary else None

            self._send(200, {
                "name": primary["name"] if primary else "Unknown",
                "in_frame": state.get("in_frame", False),
                "last_seen": state.get("last_seen"),
                "current_mood": mood["emotion"] if mood else "unknown",
                "mood_context": mood.get("context", "") if mood else "",
            })

    def _handle_people(self):
        with PersonRegistry() as reg:
            people = reg.get_all_people()
            # strip embeddings for JSON
            clean = []
            for p in people:
                clean.append({
                    "id": p["id"],
                    "name": p["name"],
                    "description": p["description"],
                    "is_primary": p.get("is_primary", 0),
                })
            self._send(200, {"people": clean})

    def _handle_health(self):
        state = get_api_state()
        self._send(200, {
            "status": "running" if state["is_running"] else "stopped",
            "current_emotion": state.get("current_emotion"),
            "timestamp": datetime.now().isoformat(),
        })

    def _handle_beacon(self):
        # import here to avoid circular deps
        from .find_ruby import FindRuby
        from .mood_ring import MoodRing

        with PersonRegistry() as reg:
            finder = FindRuby(registry=reg, mood_ring=MoodRing())
            finder.beacon_on(sound=True, lights=True, duration=15)

        self._send(200, {"message": "Find My Ruby beacon activated for 15 seconds."})

    def _send(self, code, data):
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, format, *args):
        pass  # suppress request logs


def start_api(port=8080):
    """Start the Red Rover API server in a background thread.

    Tries the requested port, then falls back to higher ports if taken.
    Non-fatal — emotion tracker runs even if the API can't bind.
    """
    for try_port in [port, port + 1, port + 2, port + 10, port + 100]:
        try:
            server = HTTPServer(("0.0.0.0", try_port), RedRoverHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            print(f"[Red Rover API] Running on http://0.0.0.0:{try_port}")
            return server
        except OSError:
            print(f"[Red Rover API] Port {try_port} in use, trying next...")
    print("[Red Rover API] WARNING: Could not bind to any port. API disabled, monitor will still run.")
    return None
