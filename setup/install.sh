#!/bin/bash
# =====================================================
#  Drive Capture v2 - macOS/Linux Auto Installer
# =====================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

clear
echo "====================================================="
echo "     Drive Capture v2 - macOS/Linux Setup"
echo "====================================================="
echo

# Get project directory (parent of setup folder)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

echo "Project directory: $PROJECT_DIR"
echo

# Step 1: Check Python
echo -e "${YELLOW}[1] Checking Python...${NC}"
if command -v python3 &> /dev/null; then
    echo -e "${GREEN}[OK] Python3 found${NC}"
    python3 --version
elif command -v python &> /dev/null; then
    echo -e "${GREEN}[OK] Python found${NC}"
    python --version
else
    echo -e "${RED}[ERROR] Python not found!${NC}"
    echo "Please install Python 3"
    exit 1
fi
echo

# Step 2: Make launcher executable
echo -e "${YELLOW}[2] Setting up launcher...${NC}"
chmod +x "$PROJECT_DIR/worker/launcher.sh"

# Remove quarantine on macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    xattr -cr "$PROJECT_DIR" 2>/dev/null || true
fi

echo -e "${GREEN}[OK] Launcher ready${NC}"
echo

# Step 3: Chrome Extension
echo -e "${YELLOW}[3] Chrome Extension Setup${NC}"
echo "---------------------------"
echo
echo "Please:"
echo "1. Open Chrome and go to: chrome://extensions"
echo "2. Enable 'Developer mode' (top right)"
echo "3. Click 'Load unpacked'"
echo "4. Select folder: $PROJECT_DIR/extension"
echo "5. Copy the Extension ID shown"
echo
read -p "Paste Extension ID here: " EXTENSION_ID

if [ -z "$EXTENSION_ID" ]; then
    echo -e "${RED}[ERROR] Extension ID required!${NC}"
    exit 1
fi
echo

# Step 4: Create Native Messaging Manifest
echo -e "${YELLOW}[4] Creating native messaging manifest...${NC}"

MANIFEST_FILE="$PROJECT_DIR/worker/com.drivecapture.worker.json"
LAUNCHER_PATH="$PROJECT_DIR/worker/launcher.sh"

cat > "$MANIFEST_FILE" <<EOF
{
  "name": "com.drivecapture.worker",
  "description": "Drive Capture v2 Worker",
  "path": "$LAUNCHER_PATH",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
EOF

echo -e "${GREEN}[OK] Manifest created${NC}"
echo

# Step 5: Install manifest
echo -e "${YELLOW}[5] Installing manifest...${NC}"

# Detect OS and browser
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    MANIFEST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    MANIFEST_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
else
    echo -e "${RED}Unsupported OS: $OSTYPE${NC}"
    exit 1
fi

mkdir -p "$MANIFEST_DIR"
cp "$MANIFEST_FILE" "$MANIFEST_DIR/"

echo -e "${GREEN}[OK] Manifest installed${NC}"
echo

# Step 6: Create config
echo -e "${YELLOW}[6] Creating configuration...${NC}"

read -p "Enter your rclone remote name (default: ngonga339): " rclone_remote
read -p "Enter the CSV file number to use, 1-20 (default: 1): " csv_file_num
read -p "Enter the max parallel rclone jobs (default: 3): " max_parallel_rclone
read -p "Enter the absolute path to your rclone executable (e.g., /opt/homebrew/bin/rclone): " rclone_path

# Set defaults if empty
rclone_remote=${rclone_remote:-"ngonga339"}
csv_file_num=${csv_file_num:-1}
max_parallel_rclone=${max_parallel_rclone:-3}
rclone_path=${rclone_path:-}

CONFIG_FILE="$PROJECT_DIR/worker/config.json"

cat > "$CONFIG_FILE" <<EOT
{
  "rclone_remote": "$rclone_remote",
  "csv_file": "../data/list${csv_file_num}.csv",
  "max_parallel": $max_parallel_rclone,
  "max_captures": 1,
  "rclone_path": "$rclone_path"
}
EOT

echo -e "${GREEN}[OK] Configuration created: $CONFIG_FILE${NC}"
echo

# Step 7: Test
echo -e "${YELLOW}[7] Testing Python worker...${NC}"
cd "$PROJECT_DIR/worker"
echo
echo "If you see 'Drive Capture Worker v2.0 Starting', it works!"
echo "Press Ctrl+C to stop test"
echo
sleep 2

if command -v python3 &> /dev/null; then
    timeout 3 python3 -u worker.py 2>&1 | head -10 || true
else
    timeout 3 python -u worker.py 2>&1 | head -10 || true
fi

echo
echo "====================================================="
echo -e "${GREEN}     Installation Complete!${NC}"
echo "====================================================="
echo
echo "Next steps:"
echo "1. Place your CSV file in: $PROJECT_DIR/data/list.csv"
echo "2. Configure rclone if not done: rclone config"
echo "3. Restart Chrome completely"
echo "4. Check extension popup for connection status"
echo
echo "Extension ID: $EXTENSION_ID"
echo
