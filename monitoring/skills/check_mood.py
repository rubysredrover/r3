"""Skill: Check Ruby's current mood.

Drop this file into ~/skills/ on MARS. innate-os auto-discovers it.
BASIC can call it when someone asks "How is Ruby feeling?"
"""

import sys
sys.path.insert(0, "/home/jetson1/emotion_tracker")

from brain_client.skill_types import Skill, SkillResult


class CheckMood(Skill):
    """Checks the current mood of the primary tracked person."""

    def __init__(self, logger):
        super().__init__(logger)

    @property
    def name(self):
        return "check_mood"

    def guidelines(self):
        return (
            "Use when someone asks about Ruby's current mood or emotional state. "
            "Examples: 'How is Ruby feeling?', 'What's her mood?', 'Is she okay?', "
            "'Check on Ruby', 'How is she doing right now?'"
        )

    def execute(self, person_name: str = ""):
        """Check the current mood of a tracked person.

        Args:
            person_name: Name of person to check. Defaults to primary tracked person.
        """
        try:
            from emotion_tracker.person_registry import PersonRegistry

            with PersonRegistry() as reg:
                if person_name:
                    people = reg.get_all_people()
                    person = next(
                        (p for p in people if p["name"].lower() == person_name.lower()),
                        None
                    )
                else:
                    person = reg.get_primary_person()

                if not person:
                    if not person_name:
                        # try first person in registry
                        people = reg.get_all_people()
                        if people:
                            person = people[0]

                if not person:
                    return "No one is registered yet. I need to see someone first.", SkillResult.FAILURE

                mood = reg.get_last_mood(person["id"])
                if not mood:
                    return f"I've met {person['name']} but haven't read their mood yet.", SkillResult.FAILURE

                name = person["name"]
                emotion = mood["emotion"]
                context = mood.get("context", "")
                timestamp = mood["timestamp"].split("T")[1][:5]

                response = f"{name} is feeling {emotion} (as of {timestamp})."
                if context:
                    response += f" {context}."

                return response, SkillResult.SUCCESS

        except Exception as e:
            return f"Error checking mood: {e}", SkillResult.FAILURE

    def cancel(self):
        return "Mood check cancelled."
