# Bolo Integration — Trust & Permissions for MARS

## How it works

```
Mom (@rubys_mom)                    PCA Jane (@pca_jane)
     │                                    │
     │  Creates grant:                    │  Asks MARS:
     │  "Give @pca_jane                   │  "How is Ruby?"
     │   mood:read + location:status"     │
     │                                    ▼
     ▼                              ┌───────────┐
  Bolo API                          │ MARS skill│
  (stores grant)                    │           │
                                    │ checks    │──► Bolo API: "Does @pca_jane
                                    │ access    │     have mood:read on mars?"
                                    │           │
                                    │           │◄── YES
                                    │           │
                                    │ returns   │──► "Ruby is feeling content"
                                    └───────────┘
```

1. **MARS is registered as a Bolo widget** (slug: `mars`, ID: `cmnuyz5mv000ba6jvhiluitkb`)
2. **Mom creates grants** — giving specific people access to specific scopes
3. **At runtime**, every skill checks Bolo before returning data (`bolo_guard.py`)
4. **Non-transitive trust** — if Mom grants PCA Jane access, Jane can't pass that access to anyone else

## Widget registration

Run once (already done):

```bash
node register_widget.js
```

## Scopes

| Scope | What it controls |
|---|---|
| `mood:read` | Check Ruby's current mood |
| `mood:history` | View mood timeline / day summary |
| `mood:notify` | Receive mood change alerts |
| `location:status` | Ask "Where's Ruby?" |
| `location:beacon` | Trigger Find My Ruby lights/sounds |
| `person:register` | Register new people with MARS |
| `person:list` | View who MARS knows |
| `settings:manage` | Change scan intervals, thresholds |

## Example grants

| Who | Scopes | Why |
|---|---|---|
| PCA Jane | `mood:read`, `mood:history`, `location:status` | Needs to check on Ruby during shifts |
| Grandma | `mood:read` | Wants to know Ruby's mood, nothing else |
| PT therapist | `mood:history` | Reviews mood patterns for treatment |
| Mom herself | All scopes | Full access |

## Runtime permission check

Every skill calls `bolo_guard.py` before returning data:

```python
from emotion_tracker.bolo_guard import require_access

# inside a skill's execute() method:
denied = require_access(requester_handle, "mood:read")
if denied:
    return denied, SkillResult.FAILURE  # "Access denied. Ask Mom."
```

## Environment variables

```bash
export BOLO_API_KEY="bolo_live_..."    # your Bolo API key
export MOM_PHONE_NUMBER="+1..."         # for SMS notifications (optional)
```

If `BOLO_API_KEY` is not set, the system runs in **open mode** (no permission checks) — useful for development and demos.
