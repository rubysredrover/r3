# For Engineers: Consuming Emotion Data

The person registry is a SQLite database at `~/emotion_tracker/people.db`. Your agent actions can query it directly:

```python
from emotion_tracker.person_registry import PersonRegistry
from emotion_tracker.mood_summary import summarize_day

with PersonRegistry() as reg:
    # who's the primary person we're tracking?
    primary = reg.get_primary_person()
    
    # what's their mood right now?
    mood = reg.get_last_mood(primary["id"])
    print(f"{primary['name']} is feeling {mood['emotion']}")
    
    # "how was Ruby's day?"
    summary = summarize_day(reg, primary["id"])
    print(summary["summary"])
    # → "Ruby was mostly content today (68% of readings). There were 3 readings
    #    showing concern (frustrated, tired), starting around 2:15pm..."
    
    # raw mood history
    history = reg.get_mood_history(primary["id"], limit=20)
    for entry in history:
        print(f"  {entry['timestamp']}: {entry['emotion']} ({entry['context']})")
```

## Database Schema

**people**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER | Primary key |
| name | TEXT | Their name |
| description | TEXT | Physical description from Gemini |
| face_embedding | BLOB | 128-dim face vector (local recognition) |
| is_primary | INTEGER | 1 = actively tracked person |
| created_at | TEXT | ISO timestamp |

**mood_log**
| Column | Type | Notes |
|---|---|---|
| person_id | INTEGER | FK to people |
| emotion | TEXT | happy, sad, tired, in_pain, frustrated, etc. |
| confidence | TEXT | high / medium / low |
| context | TEXT | "grimacing but eyes engaged" — the why behind the label |
| timestamp | TEXT | ISO timestamp |
