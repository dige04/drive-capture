#!/usr/bin/env python3
"""
Drive Capture Worker - Python Native Messaging Host
Simplified, robust design for Windows & macOS
"""

import sys
import json
import struct
import os
import platform
import threading
import queue
import time
import subprocess
import csv
import uuid
from pathlib import Path

# ============ Platform Setup ============
if platform.system() == "Windows":
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

# Prevent stdout pollution
original_stdout = sys.stdout
sys.stdout = sys.stderr

# ============ Configuration ============
CONFIG = {
    'rclone_remote': 'ngonga339',
    'csv_file': 'list1.csv',
    'max_parallel': 3,
    'max_captures': 2,
    'rclone_path': '',  # Optional override for rclone path
    'max_recapture_attempts': 3,
    'failure_reset_threshold': 10,
    'stall_timeout_sec': 900,
    'reset_cooldown_sec': 180,
    # Upper bound on how many captured-but-not-yet-transferred jobs we
    # allow to sit in transfer_queue/. This helps avoid using very old
    # video playback URLs that may have expired.
    'max_pending_transfers': 32,
}

# Load config if exists
config_file = Path(__file__).parent / 'config.json'
if config_file.exists():
    try:
        with open(config_file) as f:
            CONFIG.update(json.load(f))
    except Exception:
        pass

# Derive a sane default backlog limit if not explicitly configured.
# Tie it to the max_parallel transfer setting so we don't capture far
# ahead of what the transfer daemon can process while video URLs are
# still fresh.
if 'max_pending_transfers' not in CONFIG:
    try:
        max_parallel = int(CONFIG.get('max_parallel', 3) or 1)
    except Exception:
        max_parallel = 3
    CONFIG['max_pending_transfers'] = max_parallel * 4

# ============ Global State ============
jobs_queue = queue.Queue()
active_captures = {}
completed = set()
shutdown = threading.Event()
send_lock = threading.Lock()
# Per-file capture retry tracking (capture-only; transfers handled by transfer_daemon)
capture_attempts = {}

# Persistent transfer queue directory (consumed by transfer_daemon.py)
QUEUE_DIR = (Path(__file__).parent / 'transfer_queue').resolve()
QUEUE_DIR.mkdir(exist_ok=True)

# ============ Logging ============
def log(msg, level='INFO'):
    """Simple logging to stderr"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {msg}", file=sys.stderr, flush=True)

# ============ Native Messaging ============
def read_message():
    """Read message from Chrome extension"""
    try:
        # Read 4-byte length
        raw_length = sys.stdin.buffer.read(4)
        if not raw_length or len(raw_length) != 4:
            return None
        
        # Parse length
        message_length = struct.unpack('=I', raw_length)[0]
        
        # Read message
        message_data = sys.stdin.buffer.read(message_length)
        if not message_data or len(message_data) != message_length:
            return None
            
        return json.loads(message_data.decode('utf-8'))
        
    except Exception as e:
        log(f"Read error: {e}", 'ERROR')
        return None

def send_message(msg):
    """Send message to Chrome extension"""
    try:
        encoded = json.dumps(msg).encode('utf-8')
        length = struct.pack('=I', len(encoded))
        
        with send_lock:
            original_stdout.buffer.write(length)
            original_stdout.buffer.write(encoded)
            original_stdout.buffer.flush()
        
        log(f"Sent: {msg.get('type', 'unknown')}")
        return True
        
    except Exception as e:
        log(f"Send error: {e}", 'ERROR')
        return False

# ============ Job Management ============
def get_csv_path():
    """Resolve the absolute path to the CSV file from config."""
    csv_path = Path(CONFIG['csv_file'])
    if not csv_path.is_absolute():
        csv_path = (Path(__file__).parent / csv_path).resolve()
    return csv_path

def load_jobs():
    """Load jobs from CSV file"""
    csv_path = get_csv_path()
    
    if not csv_path.exists():
        log(f"CSV file not found: {csv_path}", 'WARN')
        return []
    
    jobs = []
    completed_file = csv_path.with_suffix('.completed.txt')
    
    # Load completed IDs
    if completed_file.exists():
        with open(completed_file) as f:
            completed.update(line.strip() for line in f)
    
    # Load jobs
    try:
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_id = row['file_id']
                if file_id not in completed:
                    jobs.append({
                        'file_id': file_id,
                        'folder_path': row.get('folder_path', ''),
                        'file_name': row.get('file_name', f'{file_id}.mp4'),
                        'size': row.get('size', ''),
                        'mime_type': row.get('mime_type', ''),
                        'mod_time': row.get('mod_time', ''),
                        'md5': row.get('md5', '')
                    })
    except Exception as e:
        log(f"Error loading CSV: {e}", 'ERROR')
    
    log(f"Loaded {len(jobs)} pending jobs ({len(completed)} completed)")
    return jobs

def save_completed(file_id):
    """Legacy helper (no longer used in capture-only worker).

    Completion is now the responsibility of transfer_daemon.py, which updates
    the .completed.txt file after successful rclone transfers.
    This function is kept for backward compatibility but is not called.
    """
    completed.add(file_id)
    
    csv_path = get_csv_path()
    completed_file = csv_path.with_suffix('.completed.txt')
    try:
        with open(completed_file, 'a') as f:
            f.write(f"{file_id}\n")
    except Exception:
        pass


# ============ Transfer Job Enqueue (for transfer_daemon) ============
def enqueue_transfer_job(job, url_or_urls):
    """Persist a transfer job to QUEUE_DIR for transfer_daemon.py to consume.

    Each queued job is a JSON file containing file metadata and candidate
    URLs. The transfer daemon is responsible for retries, backoff, and
    marking jobs completed.
    """
    file_id = job['file_id']
    urls = url_or_urls if isinstance(url_or_urls, list) else [url_or_urls]
    urls = [u for u in urls if u]
    if not urls:
        log(f"enqueue_transfer_job called with no URLs for {file_id}", 'WARN')
        return

    payload = {
        'file_id': file_id,
        'folder_path': job.get('folder_path', ''),
        'file_name': job.get('file_name', f'{file_id}.mp4'),
        'urls': urls,
        'created_at': time.time(),
        # transfer_daemon will manage these fields
        'attempts': 0,
        'next_attempt_at': 0.0,
        'last_error': None,
    }

    fname = f"{file_id}_{uuid.uuid4().hex}.json"
    tmp_path = QUEUE_DIR / (fname + '.tmp')
    final_path = QUEUE_DIR / fname

    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        os.replace(tmp_path, final_path)  # atomic on POSIX
        log(f"Enqueued transfer job for {file_id} -> {final_path}")
    except Exception as e:
        log(f"Failed to enqueue transfer job for {file_id}: {e}", 'ERROR')

# NOTE: Rclone transfer logic has moved to transfer_daemon.py.
# The worker now acts purely as a capture coordinator and enqueues
# transfer jobs for the daemon to process.

# ============ Worker Threads ============ 
def capture_worker():
    """Request captures from extension.

    This worker pulls jobs directly from jobs_queue and limits concurrent
    captures via active_captures and CONFIG['max_captures'].
    """
    while not shutdown.is_set():
        try:
            # Apply backpressure based on how many pending transfer jobs
            # are already sitting in QUEUE_DIR. This keeps us from
            # capturing far ahead of the transfer daemon and ending up
            # with stale (expired) video playback URLs.
            try:
                max_pending = int(CONFIG.get('max_pending_transfers', 0) or 0)
            except Exception:
                max_pending = 0

            if max_pending > 0:
                try:
                    pending = sum(1 for _ in QUEUE_DIR.glob('*.json'))
                except Exception as e:
                    log(f"Queue size check failed: {e}", 'WARN')
                    pending = 0

                if pending >= max_pending:
                    time.sleep(1.0)
                    continue

            # Respect capture concurrency limit
            if len(active_captures) >= CONFIG['max_captures']:
                time.sleep(0.1)
                continue

            # Get next job that still needs capture
            job = jobs_queue.get(timeout=1)
            file_id = job['file_id']

            if file_id in completed:
                # Already completed according to CSV snapshot; skip
                continue

            if file_id in active_captures:
                # Already being captured; requeue to avoid duplicate capture
                jobs_queue.put(job)
                continue

            active_captures[file_id] = job

            send_message({
                'type': 'capture',
                'file_id': file_id
            })
            log(f"Requested capture: {file_id} (active_captures={len(active_captures)})")

        except queue.Empty:
            # No jobs currently pending
            time.sleep(0.1)
        except Exception as e:
            log(f"Capture worker error: {e}", 'ERROR')

# NOTE: Transfer work is now handled by transfer_daemon.py.

# NOTE: job scheduling between transfers and captures is no longer
# required in the capture-only worker. Captures pull directly from
# jobs_queue, and transfers are managed independently by transfer_daemon.

def heartbeat_worker():
    """Send periodic ping to keep connection alive"""
    while not shutdown.is_set():
        time.sleep(20)
        send_message({'type': 'ping'})

# ============ Message Handler ============ 
def handle_extension_message(msg):
    """Process messages from extension"""
    msg_type = msg.get('type')
    
    if msg_type == 'hello':
        log(f"Extension connected (version {msg.get('version', 'unknown')})")
        send_message({'type': 'ready'})
        
    elif msg_type == 'pong':
        pass  # Heartbeat response
        
    elif msg_type == 'result':
        file_id = msg.get('file_id')
        url = msg.get('url')
        urls = msg.get('urls')
        error = msg.get('error')
        
        if file_id in active_captures:
            job = active_captures.pop(file_id)
            
            if url:
                # Successful capture; enqueue transfer job for daemon
                log(f"Got URL for {file_id}, enqueueing transfer job")
                if urls and isinstance(urls, list) and len(urls) > 0:
                    candidates = [url] + [u for u in urls if u != url]
                    enqueue_transfer_job(job, candidates)
                else:
                    enqueue_transfer_job(job, url)
            else:
                # Capture failed; limited recapture attempts
                log(f"Capture failed for {file_id}: {error}", 'WARN')
                attempts = capture_attempts.get(file_id, 0)
                attempts += 1
                capture_attempts[file_id] = attempts
                if attempts <= CONFIG.get('max_recapture_attempts', 3):
                    log(f"Scheduling recapture for {file_id} (attempt {attempts})", 'WARN')
                    jobs_queue.put(job)
                else:
                    log(f"Giving up on capture for {file_id} after {attempts} attempts", 'ERROR')

# ============ Main ============ 
def main():
    """Main entry point"""
    log("=" * 50)
    log("Drive Capture Worker v2.0 Starting")
    log(f"Platform: {platform.system()}")
    log(f"Python: {platform.python_version()}")
    log("=" * 50)
    
    # Send initial ready
    send_message({'type': 'ready'})
    
    # Load jobs
    jobs = load_jobs()
    if jobs:
        # Queue all jobs; capture_worker will pull directly from jobs_queue
        for job in jobs:
            jobs_queue.put(job)
    
    # Start worker threads (capture + heartbeat only)
    threads = [
        threading.Thread(target=capture_worker, name='Capture'),
        threading.Thread(target=heartbeat_worker, name='Heartbeat'),
    ]
    
    for t in threads:
        t.daemon = True
        t.start()
    
    # Main message loop
    try:
        while True:
            msg = read_message()
            if msg is None:
                log("Connection closed", 'WARN')
                break
            
            handle_extension_message(msg)
            
    except KeyboardInterrupt:
        log("Interrupted by user")
    except Exception as e:
        log(f"Fatal error: {e}", 'ERROR')
    
    # Cleanup
    shutdown.set()
    log("Worker shutting down")

if __name__ == "__main__":
    main()