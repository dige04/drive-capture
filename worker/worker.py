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
    'rclone_path': '' # New entry
}

# Load config if exists
config_file = Path(__file__).parent / 'config.json'
if config_file.exists():
    try:
        with open(config_file) as f:
            CONFIG.update(json.load(f))
    except:
        pass

# ============ Global State ============
jobs_queue = queue.Queue()
capture_queue = queue.Queue()
transfer_queue = queue.Queue()
active_captures = {}
completed = set()
shutdown = threading.Event()
last_progress_update = {} # New global state for rate limiting

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
    """Mark job as completed"""
    completed.add(file_id)
    
    csv_path = get_csv_path()
    
    completed_file = csv_path.with_suffix('.completed.txt')
    
    try:
        with open(completed_file, 'a') as f:
            f.write(f"{file_id}\n")
    except:
        pass

# ============ Rclone Transfer ============ 
def run_rclone(job, url):
    """Execute rclone transfer"""
    file_id = job['file_id']
    file_name = job['file_name']
    folder_path = job['folder_path']
    
    # Determine rclone executable path
    rclone_executable = CONFIG.get('rclone_path', '')
    if not rclone_executable:
        rclone_executable = 'rclone' # Fallback to PATH if not specified
    
    # Build rclone command
    target = f"{CONFIG['rclone_remote']}:{folder_path}/{file_name}"
    
    cmd = [
        rclone_executable, 'copyurl',
        url,
        target,
        '--header', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        '--header', 'Referer: https://drive.google.com/',
        '--multi-thread-cutoff', '0',
        '--multi-thread-streams', '16',
        '--retries', '5',
        '--low-level-retries', '10',
        '--retries-sleep', '20s',
        '--progress'
    ]
    
    log(f"Starting transfer: {file_name}")
    send_message({'type': 'rclone_status', 'file_id': file_id, 'status': 'Starting', 'file_name': file_name})
    
    try:
        # Run rclone
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        # Monitor output
        for line in process.stdout:
            stripped_line = line.strip()
            if 'Transferred:' in stripped_line:
                log(f"[{file_id[:8]}] {stripped_line}")
                
                # Rate limit progress messages to extension
                current_time = time.time()
                if file_id not in last_progress_update or (current_time - last_progress_update[file_id]) >= 300: # 5 minutes
                    send_message({'type': 'rclone_progress', 'file_id': file_id, 'progress': stripped_line})
                    last_progress_update[file_id] = current_time
            elif 'ERROR' in stripped_line:
                log(f"[{file_id[:8]}] {stripped_line}")
                send_message({'type': 'rclone_error', 'file_id': file_id, 'error': stripped_line})
        
        process.wait()
        
        if process.returncode == 0:
            log(f"Success: {file_name}")
            send_message({'type': 'rclone_status', 'file_id': file_id, 'status': 'Success', 'file_name': file_name})
            save_completed(file_id)
            return True
        else:
            log(f"Failed: {file_name} (code {process.returncode})", 'ERROR')
            send_message({'type': 'rclone_status', 'file_id': file_id, 'status': 'Failed', 'file_name': file_name, 'code': process.returncode})
            return False
            
    except Exception as e:
        log(f"Rclone error: {e}", 'ERROR')
        send_message({'type': 'rclone_status', 'file_id': file_id, 'status': 'Error', 'file_name': file_name, 'error': str(e)})
        return False

# ============ Worker Threads ============ 
def capture_worker():
    """Request captures from extension"""
    while not shutdown.is_set():
        try:
            # Check capture slots
            if len(active_captures) < CONFIG['max_captures']:
                # Get next job
                job = capture_queue.get(timeout=1)
                
                if job['file_id'] not in completed:
                    active_captures[job['file_id']] = job
                    
                    # Request capture
                    send_message({
                        'type': 'capture',
                        'file_id': job['file_id']
                    })
                    
                    log(f"Requested capture: {job['file_id']}")
                    
        except queue.Empty:
            pass
        except Exception as e:
            log(f"Capture worker error: {e}", 'ERROR')

def transfer_worker():
    """Process transfers with rclone"""
    while not shutdown.is_set():
        try:
            # Get transfer job
            job, url = transfer_queue.get(timeout=1)
            
            if job['file_id'] not in completed:
                run_rclone(job, url)
            
            # After transfer, queue next capture if available
            try:
                next_job = jobs_queue.get_nowait()
                capture_queue.put(next_job)
            except queue.Empty: # Handle case where jobs_queue is empty
                pass 
                
        except queue.Empty:
            pass
        except Exception as e:
            log(f"Transfer worker error: {e}", 'ERROR')

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
        error = msg.get('error')
        
        if file_id in active_captures:
            job = active_captures.pop(file_id)
            
            if url:
                log(f"Got URL for {file_id}")
                transfer_queue.put((job, url))
            else:
                log(f"Capture failed for {file_id}: {error}", 'WARN')
            
            # Queue next capture
            try:
                next_job = jobs_queue.get_nowait()
                capture_queue.put(next_job)
            except:
                pass

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
        # Queue all jobs
        for job in jobs:
            jobs_queue.put(job)
        
        # Start initial captures (up to max_parallel)
        for _ in range(min(CONFIG['max_parallel'], len(jobs))): # Changed from max_captures
            try:
                capture_queue.put(jobs_queue.get_nowait())
            except queue.Empty: # Handle case where jobs_queue is empty
                break
    
    # Start worker threads
    threads = [
        threading.Thread(target=capture_worker, name='Capture'),
        threading.Thread(target=heartbeat_worker, name='Heartbeat')
    ]
    for i in range(CONFIG['max_parallel']):
        threads.append(threading.Thread(target=transfer_worker, name=f'Transfer-{i+1}'))
    
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