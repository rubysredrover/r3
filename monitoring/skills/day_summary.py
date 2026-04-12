"""Skill: Summarize Ruby's mood throughout the day.

Drop this file into ~/skills/ on MARS. innate-os auto-discovers it.
BASIC can call it when someone asks "How was Ruby's day?"
"""

import sys
sys.path.insert(0, "/home/jetson1/emotion_tracker")

from brain_client.skill_types import Skill, SkillResult


class DaySummary(Skill):
    """Generates a natural language summary of someone's mood for the day."""

    def __init__(self, logger):
        super().__init__(logger)

    @property
    def name(self):
        return "day_summary"

    def guidelines(self):
        return (
            "Use when someone asks about Ruby's day, mood history, or mood patterns. "
            "Examples: 'How was Ruby's day?', 'Give me a mood report', "
            "'How has she been today?', 'Any mood changes today?', "
            "'Was she upset at all today?', 'Mood summary'"
        )

    def execute(self, person_name: str = "", date: str = ""):
        """Get a mood summary for a person's day.

        Args:
            person_name: Name of person. Defaults to primary tracked person.
            date: Date in YYYY-MM-DD format. Defaults to today.
        """
        try:
            from emotion_tracker.person_registry import PersonRegistry
            from emotion_tracker.mood_summary import summarize_day

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
                    people = reg.get_all_people()
                    if people:
                        person = people[0]

                if not person:
                    return "No one is registered yet. I need to see someone first.", SkillResult.FAILURE

                summary = summarize_day(reg, person["id"], date=date if date else None)

                if summary["entry_count"] == 0:
                    return f"No mood data for {person['name']} today.", SkillResult.FAILURE

                return summary["summary"], SkillResult.SUCCESS

        except Exception as e:
            return f"Error generating summary: {e}", SkillResult.FAILURE

    def cancel(self):
        return "Summary cancelled."
