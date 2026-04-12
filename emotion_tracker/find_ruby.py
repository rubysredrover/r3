"""Find Ruby: location status + alert system.

Two modes:
  1. STATUS — Mom asks "Where's Ruby?" → gets a text with Ruby's
     location, current mood, and last activity timestamp
  2. BEACON — "Find My Ruby" → activates lights/sounds on MARS
     so someone in the house can physically locate her
"""

import subprocess
import time
from datetime import datetime

from .person_registry import PersonRegistry
from .mood_ring import MoodRing, MOOD_COLORS


# Beacon patterns for "Find My Ruby"
BEACON_COLORS = [
    (255, 0, 255),   # magenta
    (0, 255, 255),   # cyan
    (255, 255, 0),   # yellow
]


class FindRuby:
    """Tracks Ruby's presence and provides status + beacon alerts."""

    def __init__(self, registry: PersonRegistry, mood_ring: MoodRing = None):
        self.registry = registry
        self.mood_ring = mood_ring or MoodRing()
        self.last_seen = None          # timestamp of last time Ruby was in frame
        self.last_location = "unknown"  # room/area if available
        self.is_in_frame = False

    def update_presence(self, person_id, in_frame: bool):
        """Called by the monitor each scan to track Ruby's presence."""
        primary = self.registry.get_primary_person()
        if not primary or primary["id"] != person_id:
            return

        self.is_in_frame = in_frame
        if in_frame:
            self.last_seen = datetime.now()

    def get_status(self, person_name: str = "") -> dict:
        """Get Ruby's current status for Mom.

        Returns a dict with all the info Mom needs.
        """
        if person_name:
            people = self.registry.get_all_people()
            person = next(
                (p for p in people if p["name"].lower() == person_name.lower()),
                None
            )
        else:
            person = self.registry.get_primary_person()
            if not person:
                people = self.registry.get_all_people()
                person = people[0] if people else None

        if not person:
            return {"found": False, "message": "No one registered yet."}

        name = person["name"]
        mood = self.registry.get_last_mood(person["id"])

        status = {
            "found": True,
            "name": name,
            "in_frame_now": self.is_in_frame,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "current_mood": mood["emotion"] if mood else "unknown",
            "mood_context": mood.get("context", "") if mood else "",
            "mood_time": mood["timestamp"] if mood else None,
        }

        # build human-readable message for Mom
        if self.is_in_frame:
            msg = f"I can see {name} right now. "
        elif self.last_seen:
            minutes_ago = (datetime.now() - self.last_seen).total_seconds() / 60
            if minutes_ago < 1:
                msg = f"{name} was just here moments ago. "
            elif minutes_ago < 60:
                msg = f"I last saw {name} {int(minutes_ago)} minutes ago. "
            else:
                hours = minutes_ago / 60
                msg = f"I last saw {name} {hours:.1f} hours ago. "
        else:
            msg = f"I haven't seen {name} yet today. "

        if mood:
            msg += f"Mood: {mood['emotion']}."
            if mood.get("context"):
                msg += f" ({mood['context']})"

        status["message"] = msg
        return status

    def beacon_on(self, sound=True, lights=True, duration=30):
        """Activate 'Find My Ruby' beacon — flashing lights and/or sound.

        Makes MARS visible and audible so someone can find Ruby
        (or Ruby can find MARS).
        """
        print(f"[Find My Ruby] BEACON ON (lights={lights}, sound={sound}, {duration}s)")
        end_time = time.time() + duration
        color_idx = 0

        while time.time() < end_time:
            if lights:
                color = BEACON_COLORS[color_idx % len(BEACON_COLORS)]
                self.mood_ring._send_color(color, pulse=True)
                color_idx += 1

            if sound:
                _play_beacon_sound()

            time.sleep(1.0)

        # restore mood ring to current state
        if self.mood_ring.current_emotion:
            self.mood_ring.set_mood(self.mood_ring.current_emotion)
        else:
            self.mood_ring.clear()

        print("[Find My Ruby] BEACON OFF")

    def beacon_off(self):
        """Turn off the beacon and restore normal mood ring."""
        if self.mood_ring.current_emotion:
            self.mood_ring.set_mood(self.mood_ring.current_emotion)
        else:
            self.mood_ring.clear()


def _play_beacon_sound():
    """Play a short locator tone via espeak or aplay."""
    try:
        subprocess.run(
            ["espeak", "-s", "160", "Here I am!"],
            timeout=3,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def send_text_to_mom(message: str, phone_number: str = None, method: str = "log"):
    """Send a text message to Mom.

    Supports multiple backends:
      - "log": just print (default, for testing)
      - "twilio": send SMS via Twilio API
      - "bolo": send via Bolospot notification system

    Configure the method and credentials via environment variables:
      NOTIFY_METHOD=twilio
      TWILIO_ACCOUNT_SID=xxx
      TWILIO_AUTH_TOKEN=xxx
      TWILIO_FROM_NUMBER=+1234567890
      MOM_PHONE_NUMBER=+1234567890
    """
    import os

    method = os.environ.get("NOTIFY_METHOD", method)
    phone = phone_number or os.environ.get("MOM_PHONE_NUMBER", "")

    print(f"[Notify Mom] {message}")

    if method == "twilio" and phone:
        try:
            from twilio.rest import Client
            client = Client(
                os.environ["TWILIO_ACCOUNT_SID"],
                os.environ["TWILIO_AUTH_TOKEN"],
            )
            client.messages.create(
                body=message,
                from_=os.environ["TWILIO_FROM_NUMBER"],
                to=phone,
            )
            print(f"[Notify Mom] SMS sent to {phone}")
        except Exception as e:
            print(f"[Notify Mom] SMS failed: {e}")

    elif method == "bolo":
        # placeholder for Bolospot integration
        print(f"[Notify Mom] Would send via Bolo: {message}")

    # always log regardless of method
    return message
