"""Generate natural language summaries of Ruby's mood throughout the day."""

from datetime import datetime, timedelta
from collections import Counter

from .person_registry import PersonRegistry


def summarize_day(registry: PersonRegistry, person_id: int, date: str = None):
    """Generate a human-readable summary of someone's mood for the day.

    Args:
        registry: PersonRegistry instance (must be open)
        person_id: ID of the person to summarize
        date: ISO date string (YYYY-MM-DD), defaults to today

    Returns:
        dict with timeline, dominant mood, shifts, and narrative summary
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # get all mood entries for the day
    history = registry.get_mood_history(person_id, limit=500)
    day_entries = [
        entry for entry in history
        if entry["timestamp"].startswith(date)
    ]
    day_entries.reverse()  # chronological order

    if not day_entries:
        return {
            "date": date,
            "entry_count": 0,
            "summary": "No mood data recorded today.",
            "timeline": [],
        }

    person = registry.get_person(person_id)
    name = person["name"] if person else "Unknown"

    # build timeline
    timeline = []
    for entry in day_entries:
        time_str = entry["timestamp"].split("T")[1][:5]  # HH:MM
        timeline.append({
            "time": time_str,
            "emotion": entry["emotion"],
            "context": entry.get("context", ""),
        })

    # count emotions
    emotion_counts = Counter(e["emotion"] for e in day_entries)
    dominant = emotion_counts.most_common(1)[0][0]
    total = len(day_entries)

    # detect mood shifts
    shifts = []
    for i in range(1, len(day_entries)):
        if day_entries[i]["emotion"] != day_entries[i - 1]["emotion"]:
            shifts.append({
                "time": day_entries[i]["timestamp"].split("T")[1][:5],
                "from": day_entries[i - 1]["emotion"],
                "to": day_entries[i]["emotion"],
            })

    # build narrative
    narrative = _build_narrative(name, date, day_entries, emotion_counts, shifts, dominant, total)

    return {
        "date": date,
        "person": name,
        "entry_count": total,
        "dominant_mood": dominant,
        "mood_breakdown": dict(emotion_counts),
        "shifts": shifts,
        "timeline": timeline,
        "summary": narrative,
    }


def _build_narrative(name, date, entries, counts, shifts, dominant, total):
    """Build a natural language summary."""
    lines = []

    # overall
    pct = (counts[dominant] / total) * 100
    lines.append(f"{name} was mostly {dominant} today ({pct:.0f}% of readings).")

    # notable periods
    distress_emotions = {"in_pain", "frustrated", "stressed", "angry", "fearful", "uncomfortable"}
    distress_entries = [e for e in entries if e["emotion"] in distress_emotions]

    if distress_entries:
        first_distress = distress_entries[0]["timestamp"].split("T")[1][:5]
        distress_types = set(e["emotion"] for e in distress_entries)
        lines.append(
            f"There were {len(distress_entries)} readings showing concern "
            f"({', '.join(distress_types)}), starting around {first_distress}."
        )

    # mood shifts
    if shifts:
        lines.append(f"Mood changed {len(shifts)} time{'s' if len(shifts) != 1 else ''} throughout the day.")
        # highlight biggest shift
        for s in shifts:
            if s["to"] in distress_emotions:
                lines.append(f"Shifted from {s['from']} to {s['to']} at {s['time']}.")
    else:
        lines.append("Mood was stable all day.")

    # current
    current = entries[-1]
    current_time = current["timestamp"].split("T")[1][:5]
    lines.append(f"Last reading at {current_time}: {current['emotion']}.")

    return " ".join(lines)
