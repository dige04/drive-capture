#!/bin/bash
# Script to migrate data from old project

echo "Drive Capture v2 - Migration Tool"
echo "================================="
echo

# Check if old project exists
OLD_PROJECT="../final-extension-2"
if [ ! -d "$OLD_PROJECT" ]; then
    echo "Old project not found at: $OLD_PROJECT"
    echo "Please specify path to old project:"
    read -p "Path: " OLD_PROJECT
fi

if [ ! -d "$OLD_PROJECT" ]; then
    echo "Error: Directory not found"
    exit 1
fi

echo "Migrating from: $OLD_PROJECT"
echo

# Copy CSV files
echo "1. Copying CSV files..."
if [ -f "$OLD_PROJECT/native-messaging/list1.csv" ]; then
    cp "$OLD_PROJECT/native-messaging/list1.csv" data/list.csv
    echo "   ✓ Copied list1.csv → data/list.csv"
fi

if [ -f "$OLD_PROJECT/native-messaging/list1_completed.txt" ]; then
    cp "$OLD_PROJECT/native-messaging/list1_completed.txt" data/list.completed.txt
    echo "   ✓ Copied completed file"
fi

# Copy GUI config if exists
if [ -f "$OLD_PROJECT/native-messaging/gui_config.json" ]; then
    echo
    echo "2. Found GUI config. Extracting settings..."
    
    # Parse with Python if available
    if command -v python3 &> /dev/null; then
        python3 -c "
import json
with open('$OLD_PROJECT/native-messaging/gui_config.json') as f:
    old = json.load(f)
    print(f'   Remote: {old.get(\"rclone_remote\", \"unknown\")}')
    print(f'   Parallel: {old.get(\"parallel_jobs\", \"unknown\")}')
    print(f'   Captures: {old.get(\"capture_jobs\", \"unknown\")}')
"
    fi
fi

echo
echo "3. Migration Summary:"
echo "   - CSV data copied to data/ folder"
echo "   - Progress preserved"
echo "   - Ready for new setup"
echo
echo "Next steps:"
echo "1. Run setup script: ./setup/install.sh"
echo "2. Configure rclone if needed"
echo "3. Start capturing!"
echo
