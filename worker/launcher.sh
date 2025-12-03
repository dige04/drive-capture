#!/bin/bash
# macOS/Linux launcher for native messaging host

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Add common rclone paths to PATH
export PATH="/usr/local/bin:/usr/bin:$HOME/bin:$PATH"

# Ensure transfer daemon is running (idempotent check)
if ! pgrep -f "transfer_daemon.py" >/dev/null 2>&1; then
    nohup python3 -u "$DIR/transfer_daemon.py" >> "$DIR/transfer_daemon.log" 2>&1 &
fi

# Check for Python for the native host worker
if command -v python3 &> /dev/null; then
    exec python3 -u worker.py
elif command -v python &> /dev/null; then
    exec python -u worker.py
else
    echo "Python not found!" >&2
    exit 1
fi
