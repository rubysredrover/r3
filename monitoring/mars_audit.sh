#!/bin/bash
# mars_audit.sh — Run on MARS robot, paste output back for doc verification
# Usage: ssh jetson1@mars-the-38th.local 'bash -s' < mars_audit.sh

set -e

echo "========================================"
echo "MARS AUDIT — $(date -Iseconds)"
echo "========================================"
echo ""

# --- OS / Hardware ---
echo "## OS & Hardware"
echo "Hostname: $(hostname)"
echo "Kernel: $(uname -r)"
echo "Arch: $(uname -m)"
if [ -f /etc/innate-os-version ]; then
    echo "innate-os version: $(cat /etc/innate-os-version)"
elif [ -f /etc/os-release ]; then
    echo "OS: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"
fi
echo ""

# --- Disk ---
echo "## Disk"
df -h / | tail -1 | awk '{print "Total: "$2"  Used: "$3"  Free: "$4"  Use%: "$5}'
echo ""

# --- RAM / Swap ---
echo "## Memory"
free -h | grep -E "Mem|Swap" | awk '{print $1" Total:"$2" Used:"$3" Free:"$4" Available:"$7}'
echo ""

# --- GPU ---
echo "## GPU"
if command -v tegrastats &>/dev/null; then
    echo "(tegrastats available — run manually for live stats)"
elif command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader 2>/dev/null || echo "nvidia-smi present but query failed"
else
    echo "No GPU tool found"
fi
echo ""

# --- Python packages (the ones we care about) ---
echo "## Python Packages (relevant)"
PACKAGES="google-genai opencv-python numpy inspireface google-auth huggingface_hub rclpy flask fastapi uvicorn requests aiohttp pillow scipy scikit-learn torch transformers onnxruntime tensorrt"
for pkg in $PACKAGES; do
    ver=$(python3 -m pip show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ -n "$ver" ]; then
        echo "  $pkg==$ver"
    fi
done
echo ""

# --- All pip packages (for completeness) ---
echo "## All Pip Packages"
python3 -m pip list --format=columns 2>/dev/null | head -80
echo "  ... (truncated at 80 lines — full list: pip list)"
echo ""

# --- ROS2 ---
echo "## ROS2 Topics"
if command -v ros2 &>/dev/null; then
    ros2 topic list 2>/dev/null || echo "ros2 available but topic list failed"
else
    echo "ros2 not found in PATH"
fi
echo ""

echo "## ROS2 Services"
if command -v ros2 &>/dev/null; then
    ros2 service list 2>/dev/null || echo "ros2 available but service list failed"
else
    echo "ros2 not found in PATH"
fi
echo ""

# --- What's deployed: skills ---
echo "## ~/skills/"
if [ -d ~/skills ]; then
    echo "Files:"
    ls -la ~/skills/ 2>/dev/null
    echo ""
    echo "Skill names (grep class.*Skill):"
    grep -rh "class.*Skill" ~/skills/*.py 2>/dev/null || echo "  (none found)"
else
    echo "  Directory does not exist"
fi
echo ""

# --- What's deployed: emotion_tracker ---
echo "## ~/emotion_tracker/"
if [ -d ~/emotion_tracker ]; then
    echo "Files:"
    find ~/emotion_tracker -type f -name "*.py" -o -name "*.db" -o -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.cfg" | sort
    echo ""
    echo "DB size:"
    ls -lh ~/emotion_tracker/people.db 2>/dev/null || echo "  people.db not found"
else
    echo "  Directory does not exist"
fi
echo ""

# --- Other team files: check common locations ---
echo "## Other Deployed Code (team scan)"
for dir in ~/actions ~/agents ~/services ~/ros2_ws/src ~/catkin_ws/src ~/workspace; do
    if [ -d "$dir" ]; then
        echo "Found: $dir"
        find "$dir" -maxdepth 2 -type f -name "*.py" -o -name "*.launch" -o -name "*.yaml" | head -20
        echo ""
    fi
done
echo ""

# --- Running processes ---
echo "## Running Processes (Python/ROS)"
ps aux | grep -E "python|ros|node" | grep -v grep | awk '{print $11, $12, $13}' | head -30
echo ""

# --- Systemd services (innate-os / custom) ---
echo "## Active Services (custom/innate)"
systemctl list-units --type=service --state=running 2>/dev/null | grep -iE "innate|mars|emotion|skill|ros|brain" || echo "  (none matched filter)"
echo ""

# --- Network: what's listening ---
echo "## Listening Ports"
ss -tlnp 2>/dev/null | grep -E "LISTEN" | awk '{print $4, $6}' | head -20
echo ""

# --- Environment variables (relevant, redacted) ---
echo "## Environment Variables (relevant)"
env | grep -iE "GEMINI|BOLO|MARS|INNATE|ROS|API_KEY|MODEL" | sed 's/=.*KEY.*/=<REDACTED>/' | sed 's/=.*api.*/=<REDACTED>/i' | sort
echo ""

# --- Crontab ---
echo "## Crontab"
crontab -l 2>/dev/null || echo "  (no crontab)"
echo ""

echo "========================================"
echo "AUDIT COMPLETE"
echo "========================================"
