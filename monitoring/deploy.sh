#!/bin/bash
# Deploy emotion tracker to MARS robot
# Run from the monitoring/ directory, or from repo root via: bash monitoring/deploy.sh
# Usage: bash deploy.sh

MARS_HOST="mars-the-38th.local"
MARS_USER="jetson1"
REMOTE="${MARS_USER}@${MARS_HOST}"

# Find the monitoring directory (works whether run from monitoring/ or repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OUR_SKILLS="check_mood.py day_summary.py find_ruby.py wave_hello.py"
OUR_ET_FILES="__init__.py api.py bolo_guard.py camera.py cloud_sync.py detector.py event_log.py face_encoder.py find_ruby.py gemini_detector.py monitor.py mood_ring.py mood_summary.py person_registry.py ruby_score.py"

echo "=== Deploying Ruby's Red Rover to MARS ==="
echo "Source: ${SCRIPT_DIR}"
echo ""

# Create directories on robot (does not touch existing files)
ssh ${REMOTE} "mkdir -p ~/skills ~/emotion_tracker/emotion_tracker"

# Copy emotion tracker service
echo "Copying emotion tracker..."
scp ${SCRIPT_DIR}/emotion_tracker/*.py ${REMOTE}:~/emotion_tracker/emotion_tracker/
scp ${SCRIPT_DIR}/run.py ${REMOTE}:~/emotion_tracker/

# Copy .env if it exists locally
if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "Copying .env..."
    scp ${SCRIPT_DIR}/.env ${REMOTE}:~/emotion_tracker/
fi

# Copy skills (appends to ~/skills/ — does NOT wipe other team skills)
echo "Copying skills to ~/skills/..."
scp ${SCRIPT_DIR}/skills/*.py ${REMOTE}:~/skills/

# Fix line endings (in case Windows CRLF snuck in)
echo "Fixing line endings..."
ssh ${REMOTE} "sed -i 's/\r$//' ~/emotion_tracker/emotion_tracker/*.py ~/emotion_tracker/run.py ~/skills/check_mood.py ~/skills/day_summary.py ~/skills/find_ruby.py ~/skills/wave_hello.py 2>/dev/null"

# Fix camera topic and Gemini model (known issues from dev)
echo "Applying on-device fixes..."
ssh ${REMOTE} "sed -i 's|image_rect_color|image_raw|g' ~/emotion_tracker/emotion_tracker/camera.py ~/emotion_tracker/run.py 2>/dev/null"
ssh ${REMOTE} "sed -i 's|gemini-2.0-flash|gemini-2.5-flash|' ~/emotion_tracker/emotion_tracker/gemini_detector.py 2>/dev/null"
ssh ${REMOTE} "sed -i 's|Part.from_text(ANALYZE_PROMPT)|Part.from_text(text=ANALYZE_PROMPT)|' ~/emotion_tracker/emotion_tracker/gemini_detector.py 2>/dev/null"

# Ensure GEMINI_API_KEY persists in zsh
echo "Checking zsh env..."
ssh ${REMOTE} "grep -q 'GEMINI_API_KEY' ~/.zshrc 2>/dev/null || echo '# Set your key: export GEMINI_API_KEY=your-key' >> ~/.zshrc"

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
echo "  python3 run.py --api-port 8090"
echo ""
echo "Skills deployed to ~/skills/ — BASIC will auto-discover:"
echo "  - check_mood: 'How is Ruby feeling?'"
echo "  - day_summary: 'How was Ruby's day?'"
echo "  - find_ruby: 'Where is Ruby?'"
echo "  - wave_hello: 'Wave at Ruby'"
