#!/usr/bin/env python3
"""
Test Suite for Drive Capture Worker Modules

Tests basic functionality of the three main Python modules:
- worker.py: Native messaging host
- transfer_daemon.py: Transfer queue processor
- url_refresher.py: URL refresh functionality
"""

import sys
import json
import tempfile
import time
from pathlib import Path

# Test counters
passed = 0
failed = 0
warnings = 0

def test_pass(name):
    global passed
    passed += 1
    print(f"✓ PASS: {name}")

def test_fail(name, error):
    global failed
    failed += 1
    print(f"✗ FAIL: {name}")
    print(f"  Error: {error}")

def test_warn(name, message):
    global warnings
    warnings += 1
    print(f"⚠ WARN: {name}")
    print(f"  Warning: {message}")

print("=" * 70)
print("Drive Capture Worker - Module Test Suite")
print("=" * 70)
print()

# ==============================================================================
# Test 1: Import all modules
# ==============================================================================
print("[1/10] Testing module imports...")

try:
    import worker
    test_pass("Import worker.py")
except Exception as e:
    test_fail("Import worker.py", str(e))

try:
    import transfer_daemon
    test_pass("Import transfer_daemon.py")
except Exception as e:
    test_fail("Import transfer_daemon.py", str(e))

try:
    import url_refresher
    test_pass("Import url_refresher.py")
except Exception as e:
    test_fail("Import url_refresher.py", str(e))

print()

# ==============================================================================
# Test 2: Check Playwright availability
# ==============================================================================
print("[2/10] Testing Playwright availability...")

try:
    from url_refresher import PLAYWRIGHT_AVAILABLE
    if PLAYWRIGHT_AVAILABLE:
        test_pass("Playwright is available")
    else:
        test_warn("Playwright not available",
                 "URL refresh will be disabled. Install with: pip install playwright && playwright install chromium")
except Exception as e:
    test_fail("Check Playwright availability", str(e))

print()

# ==============================================================================
# Test 3: Test url_refresher.is_url_expired()
# ==============================================================================
print("[3/10] Testing url_refresher.is_url_expired()...")

try:
    from url_refresher import is_url_expired

    # Test with recent timestamp (not expired)
    recent = time.time() - 3600  # 1 hour ago
    if not is_url_expired(recent, max_age=7200):  # max age 2 hours
        test_pass("is_url_expired() - recent URL")
    else:
        test_fail("is_url_expired() - recent URL", "Recent URL incorrectly marked as expired")

    # Test with old timestamp (expired)
    old = time.time() - 18000  # 5 hours ago
    if is_url_expired(old, max_age=7200):  # max age 2 hours
        test_pass("is_url_expired() - old URL")
    else:
        test_fail("is_url_expired() - old URL", "Old URL incorrectly marked as fresh")

except Exception as e:
    test_fail("is_url_expired() function", str(e))

print()

# ==============================================================================
# Test 4: Test transfer_daemon configuration loading
# ==============================================================================
print("[4/10] Testing transfer_daemon configuration...")

try:
    from transfer_daemon import CONFIG

    required_keys = [
        'rclone_remote', 'csv_file', 'max_parallel',
        'max_transfer_attempts', 'url_max_age_sec'
    ]

    missing = [k for k in required_keys if k not in CONFIG]
    if not missing:
        test_pass("transfer_daemon CONFIG has all required keys")
    else:
        test_fail("transfer_daemon CONFIG", f"Missing keys: {missing}")

    # Validate types
    if isinstance(CONFIG.get('max_parallel'), int) and CONFIG['max_parallel'] > 0:
        test_pass("transfer_daemon max_parallel is valid")
    else:
        test_fail("transfer_daemon max_parallel", "Invalid value")

except Exception as e:
    test_fail("transfer_daemon configuration", str(e))

print()

# ==============================================================================
# Test 5: Test worker configuration loading
# ==============================================================================
print("[5/10] Testing worker configuration...")

try:
    from worker import CONFIG as WORKER_CONFIG

    required_keys = ['rclone_remote', 'csv_file', 'max_captures']
    missing = [k for k in required_keys if k not in WORKER_CONFIG]

    if not missing:
        test_pass("worker CONFIG has all required keys")
    else:
        test_fail("worker CONFIG", f"Missing keys: {missing}")

    # Validate max_captures
    if isinstance(WORKER_CONFIG.get('max_captures'), int) and WORKER_CONFIG['max_captures'] > 0:
        test_pass("worker max_captures is valid")
    else:
        test_fail("worker max_captures", "Invalid value")

except Exception as e:
    test_fail("worker configuration", str(e))

print()

# ==============================================================================
# Test 6: Test transfer_daemon job file functions
# ==============================================================================
print("[6/10] Testing transfer_daemon job file operations...")

try:
    from transfer_daemon import write_job, load_job

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_job.json"
        test_data = {
            'file_id': 'test123',
            'file_name': 'test.mp4',
            'folder_path': '/test',
            'urls': ['http://example.com/video1', 'http://example.com/video2'],
            'attempts': 1,
            'created_at': time.time()
        }

        # Test write
        write_job(test_file, test_data)
        if test_file.exists():
            test_pass("transfer_daemon write_job()")
        else:
            test_fail("transfer_daemon write_job()", "File not created")

        # Test read
        loaded = load_job(test_file)
        if loaded == test_data:
            test_pass("transfer_daemon load_job()")
        else:
            test_fail("transfer_daemon load_job()", "Data mismatch")

except Exception as e:
    test_fail("transfer_daemon job file operations", str(e))

print()

# ==============================================================================
# Test 7: Test transfer_daemon backoff calculation
# ==============================================================================
print("[7/10] Testing transfer_daemon backoff delay...")

try:
    from transfer_daemon import backoff_delay, CONFIG

    delay1 = backoff_delay(1)
    delay2 = backoff_delay(2)
    delay3 = backoff_delay(3)

    base = CONFIG.get('backoff_base_sec', 30)
    max_backoff = CONFIG.get('backoff_max_sec', 900)

    # Verify exponential growth
    if delay1 <= delay2 <= delay3:
        test_pass("transfer_daemon backoff_delay() - exponential growth")
    else:
        test_fail("transfer_daemon backoff_delay()", f"Not exponential: {delay1}, {delay2}, {delay3}")

    # Verify max cap
    if delay3 <= max_backoff:
        test_pass("transfer_daemon backoff_delay() - respects max")
    else:
        test_fail("transfer_daemon backoff_delay()", f"Exceeds max: {delay3} > {max_backoff}")

except Exception as e:
    test_fail("transfer_daemon backoff_delay()", str(e))

print()

# ==============================================================================
# Test 8: Test worker enqueue_transfer_job()
# ==============================================================================
print("[8/10] Testing worker enqueue_transfer_job()...")

try:
    from worker import enqueue_transfer_job, QUEUE_DIR

    # Clean up any existing test jobs
    for f in QUEUE_DIR.glob("test_file_*"):
        f.unlink()

    test_job = {
        'file_id': 'test_file_enqueue_123',
        'file_name': 'test_video.mp4',
        'folder_path': '/test/path',
    }

    urls = ['http://example.com/video1', 'http://example.com/video2']

    enqueue_transfer_job(test_job, urls)

    # Check if job file was created
    job_files = list(QUEUE_DIR.glob("test_file_enqueue_123_*.json"))

    if job_files:
        test_pass("worker enqueue_transfer_job() - creates job file")

        # Verify job content
        with open(job_files[0]) as f:
            job_data = json.load(f)

        if job_data['file_id'] == test_job['file_id'] and job_data['urls'] == urls:
            test_pass("worker enqueue_transfer_job() - correct content")
        else:
            test_fail("worker enqueue_transfer_job()", "Job content mismatch")

        # Cleanup
        job_files[0].unlink()
    else:
        test_fail("worker enqueue_transfer_job()", "No job file created")

except Exception as e:
    test_fail("worker enqueue_transfer_job()", str(e))

print()

# ==============================================================================
# Test 9: Test transfer_daemon URL refresh integration
# ==============================================================================
print("[9/10] Testing transfer_daemon URL refresh integration...")

try:
    from transfer_daemon import URL_REFRESH_AVAILABLE, is_url_expired as daemon_is_expired

    if URL_REFRESH_AVAILABLE:
        # Test with imported function
        test_pass("transfer_daemon URL refresh integration - Playwright available")
    else:
        # Test with fallback function
        old_time = time.time() - 20000
        if daemon_is_expired(old_time, max_age=14400):
            test_pass("transfer_daemon URL refresh integration - fallback function works")
        else:
            test_fail("transfer_daemon URL refresh integration", "Fallback function incorrect")

except Exception as e:
    test_fail("transfer_daemon URL refresh integration", str(e))

print()

# ==============================================================================
# Test 10: Test url_refresher.get_chrome_user_data_dir()
# ==============================================================================
print("[10/10] Testing url_refresher.get_chrome_user_data_dir()...")

try:
    from url_refresher import get_chrome_user_data_dir
    import platform

    user_data_dir = get_chrome_user_data_dir()

    if user_data_dir:
        test_pass(f"url_refresher.get_chrome_user_data_dir() - found: {user_data_dir}")

        # Verify it exists
        if Path(user_data_dir).exists():
            test_pass("Chrome user data directory exists")
        else:
            test_warn("Chrome user data directory", f"Path returned but doesn't exist: {user_data_dir}")
    else:
        test_warn("url_refresher.get_chrome_user_data_dir()",
                 "Chrome user data directory not found (may affect URL refresh)")

except Exception as e:
    test_fail("url_refresher.get_chrome_user_data_dir()", str(e))

print()

# ==============================================================================
# Summary
# ==============================================================================
print("=" * 70)
print("Test Summary")
print("=" * 70)
print(f"PASSED:   {passed}")
print(f"FAILED:   {failed}")
print(f"WARNINGS: {warnings}")
print()

if failed == 0:
    print("✓ All tests passed!")
    sys.exit(0)
else:
    print("✗ Some tests failed. Please review the errors above.")
    sys.exit(1)
