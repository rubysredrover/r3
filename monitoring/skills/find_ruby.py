"""Skill: Find Ruby / Where's Ruby?

Drop this file into ~/skills/ on MARS. innate-os auto-discovers it.
BASIC can call it when Mom asks "Where's Ruby?"
"""

import sys
sys.path.insert(0, "/home/jetson1/emotion_tracker")

from brain_client.skill_types import Skill, SkillResult


class FindRubySkill(Skill):
    """Locate Ruby and report her status, or activate the beacon."""

    def __init__(self, logger):
        super().__init__(logger)

    @property
    def name(self):
        return "find_ruby"

    def guidelines(self):
        return (
            "Use when someone asks where Ruby is, wants to check on her, "
            "or wants to activate the 'Find My Ruby' beacon. "
            "Examples: 'Where is Ruby?', 'Find Ruby', 'Is Ruby nearby?', "
            "'Activate find my ruby', 'Turn on the locator', "
            "'Text mom where Ruby is', 'Send mom an update'"
        )

    def execute(self, action: str = "status", person_name: str = "",
                notify_mom: bool = False, beacon: bool = False):
        """Find Ruby and optionally notify Mom or activate beacon.

        Args:
            action: 'status' (default) or 'beacon'
            person_name: Name to look for. Defaults to primary person.
            notify_mom: If True, text Mom with Ruby's status.
            beacon: If True, activate lights/sounds to locate Ruby.
        """
        try:
            from emotion_tracker.person_registry import PersonRegistry
            from emotion_tracker.find_ruby import FindRuby, send_text_to_mom
            from emotion_tracker.mood_ring import MoodRing

            with PersonRegistry() as reg:
                finder = FindRuby(registry=reg, mood_ring=MoodRing())
                status = finder.get_status(person_name=person_name)

                if not status["found"]:
                    return status["message"], SkillResult.FAILURE

                message = status["message"]

                # send to Mom if requested
                if notify_mom:
                    send_text_to_mom(message)
                    message += " Mom has been notified."

                # activate beacon if requested
                if beacon or action == "beacon":
                    finder.beacon_on(sound=True, lights=True, duration=30)
                    message += " Find My Ruby beacon activated for 30 seconds."

                return message, SkillResult.SUCCESS

        except Exception as e:
            return f"Error finding Ruby: {e}", SkillResult.FAILURE

    def cancel(self):
        return "Find Ruby cancelled."
