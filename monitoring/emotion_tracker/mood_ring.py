"""Mood ring LED controller for Reachy Mini eyes via serial.

Drives the Reachy Mini eye LEDs based on Ruby Score levels.
Uses the reachy_eyes library (serial/USB) for direct hardware control.

Score-to-eyes mapping:
  80-100 (great):     GREEN, calm energy, natural blinking
  60-80  (okay):      CYAN, low energy
  40-60  (quiet):     AMBER, no energy (still, watchful)
  20-40  (withdrawn): MAGENTA, pulsing energy (blink effect)
  0-20   (alert):     RED, high energy, startle effect → alert Mom
"""

# Emotion-to-color mapping (used by api.py for Red Rover)
MOOD_COLORS = {
    "happy": (255, 223, 0), "excited": (255, 140, 0),
    "content": (100, 220, 100), "relaxed": (100, 180, 255),
    "neutral": (180, 180, 255), "sad": (70, 70, 200),
    "tired": (120, 80, 180), "confused": (200, 200, 100),
    "stressed": (255, 100, 50), "frustrated": (255, 60, 30),
    "angry": (255, 0, 0), "fearful": (180, 0, 255),
    "in_pain": (255, 0, 60), "uncomfortable": (255, 80, 80),
    "unknown": (100, 100, 100),
}

import time
import threading

try:
    from reachy_eyes import ReachyEyes, EyesDevice, Color
    REACHY_EYES_AVAILABLE = True
except ImportError:
    REACHY_EYES_AVAILABLE = False


# Ruby Score level → Reachy eyes config
SCORE_EYES = {
    "great":     {"color": Color.GREEN,   "intensity": 0.7, "energy": 0.15},
    "okay":      {"color": Color.CYAN,    "intensity": 0.6, "energy": 0.1},
    "quiet":     {"color": Color.AMBER,   "intensity": 0.5, "energy": 0.0},
    "withdrawn": {"color": Color.MAGENTA, "intensity": 0.7, "energy": 0.4},
    "alert":     {"color": Color.RED,     "intensity": 0.9, "energy": 0.6},
} if REACHY_EYES_AVAILABLE else {}

# Legacy emotion-to-firmware-color (fallback when score isn't available)
EMOTION_COLORS = {
    "happy": "GREEN", "excited": "AMBER", "content": "GREEN", "relaxed": "CYAN",
    "neutral": "CYAN", "sad": "BLUE", "tired": "BLUE", "confused": "AMBER",
    "stressed": "AMBER", "frustrated": "MAGENTA", "angry": "RED", "fearful": "MAGENTA",
    "in_pain": "RED", "uncomfortable": "RED",
}

BLINK_EMOTIONS = {"in_pain", "frustrated", "fearful"}


class MoodRing:
    """Controls the Reachy Mini eye lights via reachy_eyes serial library."""

    def __init__(self):
        self.current_emotion = None
        self.current_color = None
        self.current_level = None
        self._eyes = None

        if REACHY_EYES_AVAILABLE:
            try:
                self._setup_eyes()
            except Exception as e:
                print(f"[Mood Ring] Reachy eyes setup failed: {e}")

    def _setup_eyes(self):
        """Discover and connect to Reachy Mini eyes over serial."""
        device = EyesDevice.discover()
        self._eyes = ReachyEyes(device)
        self._eyes.enable_blinking()
        print("[Mood Ring] Connected to Reachy Mini eyes (serial)")

    def set_score(self, score_color):
        """Update the eyes based on Ruby Score query result.

        Args:
            score_color: dict from PersonRegistry.get_score_for_color()
                         with keys: score, level, mode, color
        """
        if score_color is None:
            return

        level = score_color["level"]
        if level == self.current_level:
            return  # no change

        self.current_level = level
        self.current_color = score_color["color"]

        if self._eyes is None:
            print(f"[Mood Ring] score={score_color['score']} ({level}) [no hardware]")
            return

        config = SCORE_EYES.get(level, SCORE_EYES["quiet"])
        self._eyes.set_color(config["color"])
        self._eyes.set_intensity(config["intensity"])
        self._eyes.set_energy(config["energy"])

        # startle effect on alert transitions to draw attention
        if level == "alert":
            self._eyes.startle()

        print(f"[Mood Ring] score={score_color['score']} ({level}) "
              f"-> {config['color']} intensity={config['intensity']} "
              f"energy={config['energy']}")

    def set_mood(self, emotion: str):
        """Update the eyes based on detected emotion (legacy/fallback)."""
        if emotion == self.current_emotion:
            return

        self.current_emotion = emotion
        fw_color = EMOTION_COLORS.get(emotion, "WHITE")

        if self._eyes is None:
            print(f"[Mood Ring] {emotion} -> {fw_color} [no hardware]")
            return

        self._eyes.set_color(fw_color)

        if emotion in BLINK_EMOTIONS:
            self._eyes.set_energy(0.5)
            self._eyes.startle()
        else:
            self._eyes.set_energy(0.1)

        print(f"[Mood Ring] {emotion} -> {fw_color}")

    def beacon(self, duration_sec: int = 15):
        """Activate Find My Ruby beacon — alternating eye animation."""
        if self._eyes is None:
            print(f"[Mood Ring] BEACON (no hardware)")
            return

        print(f"[Mood Ring] BEACON ON for {duration_sec}s")
        self._eyes.weewoo(duration=duration_sec)
        print("[Mood Ring] BEACON OFF")

        # restore current state
        if self.current_level:
            config = SCORE_EYES.get(self.current_level, SCORE_EYES["quiet"])
            self._eyes.set_color(config["color"])
            self._eyes.set_intensity(config["intensity"])
            self._eyes.set_energy(config["energy"])

    def clear(self):
        """Turn off the eyes."""
        self.current_emotion = None
        self.current_color = None
        self.current_level = None
        if self._eyes:
            self._eyes.off()
        print("[Mood Ring] Off")

    def cleanup(self):
        """Clean up serial connection."""
        if self._eyes:
            self._eyes.cleanup()
