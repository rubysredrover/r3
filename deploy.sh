#!/bin/bash
# Deploy emotion tracker to MARS robot
# Usage: bash deploy.sh

MARS_HOST="mars-the-38th.local"
MARS_USER="jetson1"
REMOTE="${MARS_USER}@${MARS_HOST}"

OUR_SKILLS="check_mood.py day_summary.py find_ruby.py"
OUR_ET_FILES="__init__.py api.py bolo_guard.py camera.py detector.py face_encoder.py find_ruby.py gemini_detector.py monitor.py mood_ring.py mood_summary.py person_registry.py ruby_score.py"

echo "=== Deploying Ruby's Red Rover to MARS ==="
echo ""

# Create directories on robot (does not touch existing files)
ssh ${REMOTE} "mkdir -p ~/skills ~/emotion_tracker/emotion_tracker"

# Copy emotion tracker service
echo "Copying emotion tracker..."
scp emotion_tracker/*.py ${REMOTE}:~/emotion_tracker/emotion_tracker/
scp run.py ${REMOTE}:~/emotion_tracker/

# Copy skills (appends to ~/skills/ — does NOT wipe other team skills)
echo "Copying skills to ~/skills/..."
scp skills/*.py ${REMOTE}:~/skills/

# Source ROS2 so our code can use rclpy
echo "Ensuring ROS2 is sourceable..."
ssh ${REMOTE} "grep -q 'source /opt/ros/humble/setup.bash' ~/.bashrc || echo 'source /opt/ros/humble/setup.bash' >> ~/.bashrc"

echo ""

# --- Post-deploy verification ---
echo "=== Verifying deploy ==="

FAIL=0

echo ""
echo "Checking skills..."
for f in ${OUR_SKILLS}; do
    if ssh ${REMOTE} "test -f ~/skills/${f}"; then
        echo "  OK  ~/skills/${f}"
    else
        echo "  MISSING  ~/skills/${f}"
        FAIL=1
    fi
done

echo ""
echo "Checking emotion_tracker..."
for f in ${OUR_ET_FILES}; do
    if ssh ${REMOTE} "test -f ~/emotion_tracker/emotion_tracker/${f}"; then
        echo "  OK  ~/emotion_tracker/emotion_tracker/${f}"
    else
        echo "  MISSING  ~/emotion_tracker/emotion_tracker/${f}"
        FAIL=1
    fi
done

if ssh ${REMOTE} "test -f ~/emotion_tracker/run.py"; then
    echo "  OK  ~/emotion_tracker/run.py"
else
    echo "  MISSING  ~/emotion_tracker/run.py"
    FAIL=1
fi

echo ""
if [ ${FAIL} -eq 0 ]; then
    echo "=== All files verified. Deploy complete. ==="
else
    echo "=== WARNING: Some files missing! Check output above. ==="
    exit 1
fi

echo ""
echo "To run the emotion monitor:"
echo "  ssh ${REMOTE}"
echo "  cd ~/emotion_tracker"
echo "  export GEMINI_API_KEY=your-key"
echo "  python3 run.py"
echo ""
echo "Skills deployed to ~/skills/ — BASIC will auto-discover:"
echo "  - check_mood: 'How is Ruby feeling?'"
echo "  - day_summary: 'How was Ruby's day?'"
echo "  - find_ruby: 'Where is Ruby?'"
