#!/usr/bin/env python3
"""
Drive Capture Transfer Daemon

Long-lived process responsible for running rclone copyurl transfers
independently of the Chrome extension / native-messaging worker.

Workflow:
- worker.py (native host) captures URLs and writes JSON job files
  into QUEUE_DIR (transfer_queue/).
- This daemon scans QUEUE_DIR, picks jobs, runs rclone with retries
  and backoff, and marks jobs completed by updating .completed.txt.
- Because this process is not tied to Chrome's native-messaging
  lifecycle, transfers continue even if the extension or worker
  restarts.
"""

import json
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Dict, Any

# ============ Configuration ============
CONFIG = {
    'rclone_remote': 'ngonga339',
    'csv_file': 'list1.csv',
    'max_parallel': 4,              # concurrent rclone processes
    'rclone_path': '',              # optional override
    'stall_timeout_sec': 900,
    'max_transfer_attempts': 5,
    'backoff_base_sec': 30,
    'backoff_max_sec': 900,
    # Default User-Agent for rclone HTTP requests. This can be overridden
    # in worker/config.json to match the actual browser UA on the
    # machine running Drive Capture.
    'user_agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
}

# Load config if exists (shared with worker.py)
config_file = Path(__file__).parent / 'config.json'
if config_file.exists():
    try:
        with open(config_file) as f:
            CONFIG.update(json.load(f))
    except Exception:
        pass

# ============ Paths & Globals ============
BASE_DIR = Path(__file__).parent.resolve()
QUEUE_DIR = (BASE_DIR / 'transfer_queue').resolve()
FAILED_DIR = (BASE_DIR / 'transfer_failed').resolve()
QUEUE_DIR.mkdir(exist_ok=True)
FAILED_DIR.mkdir(exist_ok=True)

completed: set[str] = set()
completed_lock = threading.Lock()
log_lock = threading.Lock()


# ============ Logging ============
def log(msg: str, level: str = 'INFO') -> None:
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with log_lock:
        print(f"[{ts}] [{level}] {msg}", flush=True)


# ============ CSV / Completion Tracking ============
def get_csv_path() -> Path:
    csv_path = Path(CONFIG['csv_file'])
    if not csv_path.is_absolute():
        csv_path = (BASE_DIR / csv_path).resolve()
    return csv_path


def load_completed() -> None:
    """Populate the in-memory completed set from .completed.txt if present."""
    csv_path = get_csv_path()
    completed_file = csv_path.with_suffix('.completed.txt')
    if not completed_file.exists():
        return
    try:
        with completed_file.open() as f:
            with completed_lock:
                completed.update(line.strip() for line in f if line.strip())
        log(f"Loaded {len(completed)} completed jobs from {completed_file}")
    except Exception as e:
        log(f"Failed to load completed file: {e}", 'ERROR')


def save_completed(file_id: str) -> None:
    """Append a completed file_id to .completed.txt and update memory."""
    with completed_lock:
        if file_id in completed:
            return
        completed.add(file_id)

    csv_path = get_csv_path()
    completed_file = csv_path.with_suffix('.completed.txt')
    try:
        with completed_file.open('a') as f:
            f.write(f"{file_id}\n")
        log(f"Marked completed: {file_id}")
    except Exception as e:
        log(f"Failed to write completed for {file_id}: {e}", 'ERROR')


# ============ Queue Helpers ============
def list_job_files() -> List[Path]:
    return sorted(p for p in QUEUE_DIR.glob('*.json'))


def acquire_job(path: Path) -> Path | None:
    """Attempt to atomically lock a job file by renaming it.

    Returns the locked path (with .locked suffix) if successful, else None.
    """
    locked = path.with_suffix(path.suffix + '.locked')
    try:
        path.rename(locked)
        return locked
    except FileNotFoundError:
        return None
    except OSError:
        # Someone else likely locked it
        return None


def load_job(path: Path) -> Dict[str, Any]:
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def write_job(path: Path, job: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(job, f)
    os.replace(tmp, path)


def release_job(locked_path: Path, job: Dict[str, Any]) -> None:
    """Release a locked job back into QUEUE_DIR with updated content."""
    unlocked = QUEUE_DIR / locked_path.name.replace('.locked', '')
    write_job(unlocked, job)
    try:
        locked_path.unlink(missing_ok=True)
    except TypeError:
        # Python < 3.8 compatibility, ignore if missing
        if locked_path.exists():
            locked_path.unlink()


def move_to_failed(locked_path: Path, job: Dict[str, Any]) -> None:
    dest = FAILED_DIR / locked_path.name.replace('.locked', '')
    write_job(dest, job)
    try:
        locked_path.unlink(missing_ok=True)
    except TypeError:
        if locked_path.exists():
            locked_path.unlink()
    log(f"Moved job for {job.get('file_id')} to failed queue: {dest}", 'ERROR')


# ============ Rclone Transfer Logic ============
def run_rclone(job: Dict[str, Any], urls: List[str]) -> Dict[str, Any]:
    """Run rclone copyurl for a job, trying candidate URLs in order.

    Returns a dict with keys:
      - success: bool
      - errors: list[str]
    """
    file_id = job['file_id']
    file_name = job['file_name']
    folder_path = job['folder_path']

    # Resolve rclone executable
    rclone_executable = CONFIG.get('rclone_path') or 'rclone'

    target = f"{CONFIG['rclone_remote']}:{folder_path}/{file_name}"

    def execute_copy(single_url: str) -> tuple[bool, List[str], bool]:
        errors: List[str] = []
        killed_by_watchdog = False

        # User-Agent header is configurable via CONFIG['user_agent'] so
        # it can match the real Chrome UA on this machine (helps avoid
        # 403s from overly strict backends).
        ua = CONFIG.get('user_agent') or 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'

        cmd = [
            rclone_executable, 'copyurl',
            single_url,
            target,
            '--header', f'User-Agent: {ua}',
            '--header', 'Referer: https://drive.google.com/',
            '--multi-thread-cutoff', '0',
            '--multi-thread-streams', '4',
            '--retries', '5',
            '--low-level-retries', '5',
            '--retries-sleep', '10s',
            '--progress',
        ]

        log(f"[{file_id[:8]}] starting rclone for {file_name} -> {target}")
        start_ts = time.time()

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )

            last_output_time = time.time()

            def watchdog() -> None:
                nonlocal killed_by_watchdog
                stall_limit = CONFIG.get('stall_timeout_sec', 900)
                while process.poll() is None:
                    time.sleep(15)
                    if time.time() - last_output_time > stall_limit:
                        try:
                            log(f"[{file_id[:8]}] watchdog killing stalled rclone for {file_name}", 'WARN')
                            process.kill()
                            killed_by_watchdog = True
                            break
                        except Exception:
                            break

            threading.Thread(target=watchdog, daemon=True).start()

            assert process.stdout is not None
            for line in process.stdout:
                stripped = line.strip()
                last_output_time = time.time()
                if 'Transferred:' in stripped:
                    log(f"[{file_id[:8]}] {stripped}")
                elif 'ERROR' in stripped or 'Failed to copy' in stripped or '404 Not Found' in stripped:
                    errors.append(stripped)
                    log(f"[{file_id[:8]}] {stripped}", 'ERROR')

            process.wait()
            elapsed = time.time() - start_ts

            if process.returncode == 0 and not killed_by_watchdog:
                log(f"[{file_id[:8]}] rclone success (code 0, {elapsed:.1f}s)")
                return True, errors, killed_by_watchdog

            log(f"[{file_id[:8]}] rclone failed (code {process.returncode}, {elapsed:.1f}s)", 'ERROR')
            return False, errors, killed_by_watchdog

        except Exception as e:
            errors.append(str(e))
            log(f"[{file_id[:8]}] rclone exception: {e}", 'ERROR')
            return False, errors, killed_by_watchdog

    # Normalize URLs
    candidates = [u for u in (urls or []) if u]
    if not candidates:
        log(f"[{file_id[:8]}] no URLs provided for transfer", 'ERROR')
        return {'success': False, 'errors': ['no URLs']}

    all_errors: List[str] = []
    for idx, url in enumerate(candidates):
        log(f"[{file_id[:8]}] trying URL {idx+1}/{len(candidates)}")
        success, errors, killed = execute_copy(url)
        if success:
            return {'success': True, 'errors': all_errors}
        all_errors.extend(errors)
        # For 404/EOF/connection issues, try next candidate
        if any('404 Not Found' in e or 'unexpected EOF' in e or 'context deadline exceeded' in e or 'connection reset by peer' in e for e in errors) or killed:
            continue
        # Other errors: break early
        break

    return {'success': False, 'errors': all_errors}


# ============ Worker Loop ============
def backoff_delay(attempts: int) -> float:
    base = CONFIG.get('backoff_base_sec', 30)
    max_b = CONFIG.get('backoff_max_sec', 900)
    return min(base * (2 ** max(attempts - 1, 0)), max_b)


def process_job_file(job_path: Path) -> None:
    locked = acquire_job(job_path)
    if locked is None:
        return

    try:
        job = load_job(locked)
    except Exception as e:
        log(f"Failed to load job {locked}: {e}", 'ERROR')
        try:
            locked.unlink(missing_ok=True)
        except TypeError:
            if locked.exists():
                locked.unlink()
        return

    file_id = job.get('file_id')
    if not file_id:
        log(f"Job file {locked} missing file_id; moving to failed", 'ERROR')
        move_to_failed(locked, job)
        return

    # Skip if already completed
    with completed_lock:
        if file_id in completed:
            log(f"[{file_id[:8]}] already completed; dropping queued job {locked}")
            try:
                locked.unlink(missing_ok=True)
            except TypeError:
                if locked.exists():
                    locked.unlink()
            return

    attempts = int(job.get('attempts', 0)) + 1
    next_allowed = float(job.get('next_attempt_at', 0.0))
    now = time.time()

    if now < next_allowed:
        # Not yet time; release job back
        release_job(locked, job)
        return

    job['attempts'] = attempts

    urls = job.get('urls') or []
    log(f"[{file_id[:8]}] transfer attempt {attempts} with {len(urls)} URL(s)")

    result = run_rclone(job, urls)

    if result.get('success'):
        save_completed(file_id)
        try:
            locked.unlink(missing_ok=True)
        except TypeError:
            if locked.exists():
                locked.unlink()
        return

    # Failure path
    errors = result.get('errors') or []
    last_error = errors[-1] if errors else 'unknown error'
    job['last_error'] = last_error

    if attempts >= CONFIG.get('max_transfer_attempts', 5):
        log(f"[{file_id[:8]}] giving up after {attempts} attempts: {last_error}", 'ERROR')
        move_to_failed(locked, job)
        return

    delay = backoff_delay(attempts)
    job['next_attempt_at'] = time.time() + delay
    log(f"[{file_id[:8]}] scheduling retry in {delay:.1f}s (attempts={attempts})", 'WARN')
    release_job(locked, job)


def worker_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        jobs = list_job_files()
        if not jobs:
            time.sleep(1.0)
            continue

        for path in jobs:
            if stop_event.is_set():
                break
            process_job_file(path)

        # Small pause to avoid tight loop
        time.sleep(0.2)


def main() -> None:
    log("=" * 60)
    log("Drive Capture Transfer Daemon starting")
    log(f"Platform: {platform.system()}")
    log(f"Python: {platform.python_version()}")
    log(f"Queue dir: {QUEUE_DIR}")
    log(f"Failed dir: {FAILED_DIR}")
    log("=" * 60)

    load_completed()

    stop_event = threading.Event()
    workers: List[threading.Thread] = []
    num_workers = max(1, int(CONFIG.get('max_parallel', 4)))

    for i in range(num_workers):
        t = threading.Thread(target=worker_loop, args=(stop_event,), name=f'TransferWorker-{i+1}')
        t.daemon = True
        t.start()
        workers.append(t)

    try:
        while True:
            time.sleep(5.0)
    except KeyboardInterrupt:
        log("Transfer daemon interrupted by user", 'WARN')
    finally:
        stop_event.set()
        for t in workers:
            t.join(timeout=5.0)
        log("Transfer daemon shutting down")


if __name__ == '__main__':
    main()
