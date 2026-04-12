"""Mood ring LED controller via /light_command ROS2 service.

Maps Ruby's current emotion to a color on the Reachy Mini eye lights
so Mom or PCA can get a vibe check at a glance.

Service: /light_command (maurice_msgs/srv/LightCommand)
  mode: OFF=0, SOLID=1, BLINK=2, RING=3
  interval: animation speed in ms (1-10000)
  r, g, b: color (0-255)
"""

import threading

try:
    import rclpy
    from rclpy.node import Node
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False


# Emotion-to-color mapping (RGB tuples)
MOOD_COLORS = {
    # Positive
    "happy":       (255, 223, 0),    # warm yellow
    "excited":     (255, 140, 0),    # bright orange
    "content":     (100, 220, 100),  # soft green
    "relaxed":     (100, 180, 255),  # calm blue

    # Neutral
    "neutral":     (180, 180, 255),  # soft lavender

    # Negative / concern
    "sad":         (70,  70,  200),  # deep blue
    "tired":       (120, 80,  180),  # muted purple
    "confused":    (200, 200, 100),  # pale yellow
    "stressed":    (255, 100, 50),   # amber-orange
    "frustrated":  (255, 60,  30),   # red-orange
    "angry":       (255, 0,   0),    # red
    "fearful":     (180, 0,   255),  # violet

    # Urgent
    "in_pain":     (255, 0,   60),   # urgent red-pink
    "uncomfortable": (255, 80, 80),  # warm red

    # Fallback
    "unknown":     (100, 100, 100),  # dim gray
}

# Emotions that should blink instead of solid
BLINK_EMOTIONS = {"in_pain", "frustrated", "fearful"}

# LightCommand mode constants
MODE_OFF = 0
MODE_SOLID = 1
MODE_BLINK = 2
MODE_RING = 3


class MoodRing:
    """Controls the Reachy Mini eye lights via /light_command ROS2 service."""

    def __init__(self):
        self.current_emotion = None
        self.current_color = None
        self._client = None
        self._node = None

        if ROS2_AVAILABLE:
            try:
                self._setup_ros2()
            except Exception as e:
                print(f"[Mood Ring] ROS2 setup failed: {e}")

    def _setup_ros2(self):
        """Create a ROS2 service client for /light_command."""
        # import here to avoid issues if maurice_msgs isn't available
        from maurice_msgs.srv import LightCommand
        self._LightCommand = LightCommand

        if not rclpy.ok():
            rclpy.init()

        self._node = rclpy.create_node("mood_ring")
        self._client = self._node.create_client(LightCommand, "/light_command")
        print("[Mood Ring] Connected to /light_command service")

    def set_mood(self, emotion: str):
        """Update the mood ring color based on detected emotion."""
        if emotion == self.current_emotion:
            return  # no change needed

        self.current_emotion = emotion
        color = MOOD_COLORS.get(emotion, MOOD_COLORS["unknown"])
        self.current_color = color

        if emotion in BLINK_EMOTIONS:
            mode = MODE_BLINK
            interval = 500  # fast blink for distress
        else:
            mode = MODE_SOLID
            interval = 0

        self._send_command(color, mode, interval)
        print(f"[Mood Ring] {emotion} → RGB{color} {'(blinking)' if mode == MODE_BLINK else ''}")

    def _send_command(self, color: tuple, mode: int = MODE_SOLID, interval: int = 0):
        """Send a color command to the /light_command service."""
        r, g, b = color

        if self._client is None:
            # fallback: just log
            return

        try:
            request = self._LightCommand.Request()
            request.mode = mode
            request.interval = interval
            request.r = r
            request.g = g
            request.b = b

            future = self._client.call_async(request)
            rclpy.spin_until_future_complete(self._node, future, timeout_sec=2.0)

            if future.result() is not None:
                result = future.result()
                if not result.success:
                    print(f"[Mood Ring] Service error: {result.message}")
            else:
                print("[Mood Ring] Service call timed out")

        except Exception as e:
            print(f"[Mood Ring] Error: {e}")

    def beacon(self, duration_sec: int = 15):
        """Activate Find My Ruby beacon — rainbow ring animation."""
        self._send_command((255, 0, 255), MODE_RING, 200)
        print(f"[Mood Ring] BEACON ON for {duration_sec}s")

        import time
        time.sleep(duration_sec)

        # restore current mood
        if self.current_emotion:
            self.set_mood(self.current_emotion)
        else:
            self.clear()

        print("[Mood Ring] BEACON OFF")

    def clear(self):
        """Turn off the mood ring."""
        self.current_emotion = None
        self.current_color = None
        self._send_command((0, 0, 0), MODE_OFF, 0)
        print("[Mood Ring] Off")
