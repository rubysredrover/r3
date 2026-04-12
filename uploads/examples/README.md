# Ruby Emotion Examples

Drop labeled photos or short video clips of Ruby here. These are used by the emotion tracker to understand what each emotional state looks like **for Ruby specifically** — not population averages.

## Structure

```
uploads/examples/
  happy/          # Muscle tension, stimming, bright eyes, animated
  content/        # Relaxed posture, steady eye contact, calm
  tired/          # Drooping eyelids, slower movement, low energy
  frustrated/     # Motor difficulty — NOT emotional (eyes still engaged)
  neutral/        # Baseline — steady, moderate engagement
  excited/        # Stimming, bouncing, loud vocalizations — this is JOY
  in_pain/        # Confirmed pain — different from motor grimacing
```

## What to capture

- **happy**: Muscle tension + stimming = Ruby's happiness signal. Standard AI reads this as stressed/agitated. We know better.
- **frustrated**: Motor frustration (task difficulty) vs emotional frustration. Eye contact stays steady during motor frustration.
- **excited**: Stimming, repetitive movements, loud — this is joy, not distress.
- **tired**: Post-effort fatigue. Not sadness. Will recover.

## File naming

Use descriptive names: `ruby_happy_stimming_kitchen.jpg`, `ruby_tired_post_therapy.mp4`

## Usage

The demo walkthrough (`demo_video.py`) can process these files through the full pipeline:

```bash
python3 demo_video.py uploads/examples/happy/ruby_stimming.jpg --photo
python3 demo_video.py uploads/examples/ruby_afternoon.mp4 --interval 3
```
