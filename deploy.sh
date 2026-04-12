#!/bin/bash
# Deploy emotion tracker to MARS robot
# Usage: bash deploy.sh

MARS_HOST="mars-the-38th.local"
MARS_USER="jetson1"

echo "=== Deploying Ruby's Red Rover to MARS ==="
echo ""

# Create directories on robot
ssh ${MARS_USER}@${MARS_HOST} "mkdir -p ~/skills ~/emotion_tracker/emotion_tracker"

# Copy emotion tracker service
echo "Copying emotion tracker..."
scp emotion_tracker/*.py ${MARS_USER}@${MARS_HOST}:~/emotion_tracker/emotion_tracker/
scp run.py ${MARS_USER}@${MARS_HOST}:~/emotion_tracker/

# Copy skills (auto-discovered by innate-os)
echo "Copying skills to ~/skills/..."
scp skills/*.py ${MARS_USER}@${MARS_HOST}:~/skills/

# No pip install needed — all deps are pre-installed on innate-os 0.5.0-rc10

echo ""
echo "=== Deployed! ==="
echo ""
echo "To run the emotion monitor:"
echo "  ssh ${MARS_USER}@${MARS_HOST}"
echo "  cd ~/emotion_tracker"
echo "  export GEMINI_API_KEY=your-key"
echo "  python3 run.py"
echo ""
echo "Skills deployed to ~/skills/ — BASIC will auto-discover:"
echo "  - check_mood: 'How is Ruby feeling?'"
echo "  - day_summary: 'How was Ruby's day?'"
