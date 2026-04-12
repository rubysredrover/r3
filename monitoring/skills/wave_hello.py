"""Skill: Wave and say hello from Mom (or another caregiver).

Drop this file into ~/skills/ on MARS. innate-os auto-discovers it.
Triggered from Red Rover app when Mom taps "Say Hi."
"""

import subprocess
import time
import threading

from brain_client.skill_types import Skill, SkillResult


# Wave motion: sequence of joint angle keyframes (radians)
# Each tuple: (joint_angles[6], duration_ms)
WAVE_SEQUENCE = [
    # Raise arm up
    ([0.0, -1.0, 1.5, -0.8, 0.0, 0.0], 1500),
    # Wave right
    ([0.0, -1.0, 1.5, -0.3, 0.0, 0.0], 400),
    # Wave left
    ([0.0, -1.0, 1.5, -0.8, 0.0, 0.0], 400),
    # Wave right
    ([0.0, -1.0, 1.5, -0.3, 0.0, 0.0], 400),
    # Wave left
    ([0.0, -1.0, 1.5, -0.8, 0.0, 0.0], 400),
    # Return to rest
    ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1500),
]


class WaveHello(Skill):
    """Wave and speak a greeting from a caregiver."""

    def __init__(self, logger):
        super().__init__(logger)

    @property
    def name(self):
        return "wave_hello"

    def guidelines(self):
        return (
            "Use when someone wants MARS to wave at Ruby and say hello. "
            "Examples: 'Wave at Ruby', 'Say hi to Ruby', 'Tell Ruby Mom says hi', "
            "'Send Ruby a wave from Mom', 'Greet Ruby'"
        )

    def execute(self, sender_name: str = "Mom", message: str = ""):
        """Wave and say a greeting.

        Args:
            sender_name: Who is saying hi (e.g., "Mom", "Grandma", "Jane")
            message: Custom message. Defaults to "Ruby, {sender_name} says hi!"
        """
        greeting = message or f"Ruby, {sender_name} says hi!"

        try:
            # Speak and wave in parallel
            speak_thread = threading.Thread(target=_speak, args=(greeting,))
            wave_thread = threading.Thread(target=_wave_arm)

            speak_thread.start()
            wave_thread.start()

            speak_thread.join(timeout=10)
            wave_thread.join(timeout=10)

            return f"MARS waved and said: {greeting}", SkillResult.SUCCESS

        except Exception as e:
            return f"Wave failed: {e}", SkillResult.FAILURE

    def cancel(self):
        return "Wave cancelled."


def _speak(text):
    """Speak via espeak on the Jetson."""
    print(f"[MARS]: {text}")
    try:
        subprocess.run(
            ["espeak", "-s", "130", "-p", "50", text],
            timeout=10,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _wave_arm():
    """Execute the wave motion via ROS2 service call."""
    try:
        import rclpy
        from rclpy.node import Node
        from maurice_msgs.srv import GotoJS
        from std_msgs.msg import Float64MultiArray

        if not rclpy.ok():
            rclpy.init()

        node = rclpy.create_node("wave_hello_skill")
        client = node.create_client(GotoJS, "/mars/arm/goto_js")

        if not client.wait_for_service(timeout_sec=3.0):
            print("[Wave] Arm service not available — skipping wave")
            node.destroy_node()
            return

        for joints, duration_ms in WAVE_SEQUENCE:
            request = GotoJS.Request()
            request.data = Float64MultiArray(data=joints)
            request.time = duration_ms

            future = client.call_async(request)
            rclpy.spin_until_future_complete(node, future, timeout_sec=5.0)

            # Wait for the motion to complete
            time.sleep(duration_ms / 1000.0)

        node.destroy_node()

    except ImportError:
        # ROS2 not available (dev machine) — just log
        print("[Wave] ROS2 not available — simulating wave")
        for joints, duration_ms in WAVE_SEQUENCE:
            print(f"  arm → {joints} ({duration_ms}ms)")
            time.sleep(duration_ms / 1000.0)
    except Exception as e:
        print(f"[Wave] Arm motion failed: {e}")
