#!/bin/bash
# macOS/Linux launcher for native messaging host

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Add common rclone paths to PATH
export PATH="/usr/local/bin:/usr/bin:$HOME/bin:$PATH"

# Check for Python
if command -v python3 &> /dev/null; then
    exec python3 -u worker.py
elif command -v python &> /dev/null; then
    exec python -u worker.py
else
    echo "Python not found!" >&2
    exit 1
fi