#!/usr/bin/env python3
"""
Integration Test for Drive Capture Workflow

Tests the complete workflow from job creation to transfer queue
without actually running rclone or Playwright.
"""

import json
import sys
import time
import tempfile
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
print("Drive Capture Worker - Integration Test Suite")
print("=" * 70)
print()

# ==============================================================================
# Test 1: End-to-end job enqueueing
# ==============================================================================
print("[1/7] Testing end-to-end job enqueueing...")

try:
    from worker import enqueue_transfer_job, QUEUE_DIR

    test_job = {
        'file_id': 'integration_test_12345',
        'file_name': 'test_integration.mp4',
        'folder_path': '/test/integration',
    }

    urls = [
        'https://example.com/video1.mp4',
        'https://example.com/video2.mp4',
        'https://example.com/video3.mp4'
    ]

    # Clean up any existing test jobs
    for f in QUEUE_DIR.glob("integration_test_*"):
        f.unlink()

    # Enqueue job
    enqueue_transfer_job(test_job, urls)

    # Find the job file
    job_files = list(QUEUE_DIR.glob("integration_test_12345_*.json"))

    if job_files:
        test_pass("Job file created in queue")

        # Load and verify
        with open(job_files[0]) as f:
            job_data = json.load(f)

        # Verify all expected fields
        expected_fields = ['file_id', 'folder_path', 'file_name', 'urls',
                          'created_at', 'attempts', 'next_attempt_at', 'last_error']

        missing = [f for f in expected_fields if f not in job_data]
        if not missing:
            test_pass("Job file has all required fields")
        else:
            test_fail("Job file fields", f"Missing: {missing}")

        # Verify URLs
        if job_data['urls'] == urls:
            test_pass("Job URLs match input")
        else:
            test_fail("Job URLs", f"Expected {urls}, got {job_data['urls']}")

        # Cleanup
        job_files[0].unlink()
    else:
        test_fail("Job file creation", "No job file found in queue")

except Exception as e:
    test_fail("End-to-end job enqueueing", str(e))

print()

# ==============================================================================
# Test 2: Transfer daemon job acquisition
# ==============================================================================
print("[2/7] Testing transfer daemon job acquisition...")

try:
    from transfer_daemon import acquire_job, release_job, QUEUE_DIR as DAEMON_QUEUE_DIR

    # Create a test job file
    test_file = DAEMON_QUEUE_DIR / "test_acquire_job.json"
    test_data = {
        'file_id': 'test_acquire_123',
        'urls': ['http://example.com/test'],
        'attempts': 0
    }

    with open(test_file, 'w') as f:
        json.dump(test_data, f)

    # Test acquisition
    locked = acquire_job(test_file)

    if locked and locked.exists() and '.locked' in locked.name:
        test_pass("Job successfully locked")

        # Verify original is gone
        if not test_file.exists():
            test_pass("Original job file removed after lock")
        else:
            test_fail("Job acquisition", "Original file still exists")

        # Test release
        release_job(locked, test_data)

        # Verify released job exists and locked is gone
        if test_file.exists() and not locked.exists():
            test_pass("Job successfully released")
            test_file.unlink()
        else:
            test_fail("Job release", "Job not properly released")
    else:
        test_fail("Job acquisition", "Failed to acquire job lock")
        if test_file.exists():
            test_file.unlink()

except Exception as e:
    test_fail("Transfer daemon job acquisition", str(e))

print()

# ==============================================================================
# Test 3: URL expiration logic
# ==============================================================================
print("[3/7] Testing URL expiration logic...")

try:
    from url_refresher import is_url_expired
    from transfer_daemon import URL_REFRESH_AVAILABLE

    # Test various time scenarios
    now = time.time()

    scenarios = [
        (now - 3600, 7200, False, "1 hour old, 2 hour limit - fresh"),
        (now - 7200, 3600, True, "2 hours old, 1 hour limit - expired"),
        (now - 14400, 14400, True, "Exactly at limit - expired"),
        (now - 14399, 14400, False, "Just under limit - fresh"),
    ]

    all_passed = True
    for created_at, max_age, expected, desc in scenarios:
        result = is_url_expired(created_at, max_age)
        if result == expected:
            test_pass(f"URL expiration: {desc}")
        else:
            test_fail(f"URL expiration: {desc}", f"Expected {expected}, got {result}")
            all_passed = False

    if URL_REFRESH_AVAILABLE:
        test_pass("URL refresh is available (Playwright installed)")
    else:
        test_warn("URL refresh", "Playwright not available - refresh disabled")

except Exception as e:
    test_fail("URL expiration logic", str(e))

print()

# ==============================================================================
# Test 4: Configuration merging
# ==============================================================================
print("[4/7] Testing configuration loading and merging...")

try:
    import worker
    import transfer_daemon

    # Check if config.json exists and was loaded
    config_file = Path(__file__).parent / 'config.json'

    if config_file.exists():
        test_pass("config.json exists")

        # Verify it was loaded correctly
        with open(config_file) as f:
            config_data = json.load(f)

        # Check if worker loaded it
        if worker.CONFIG.get('rclone_remote') == config_data.get('rclone_remote'):
            test_pass("worker.py loaded config.json correctly")
        else:
            test_fail("worker.py config", "Config not loaded correctly")

        # Check if transfer_daemon loaded it
        if transfer_daemon.CONFIG.get('rclone_remote') == config_data.get('rclone_remote'):
            test_pass("transfer_daemon.py loaded config.json correctly")
        else:
            test_fail("transfer_daemon.py config", "Config not loaded correctly")
    else:
        test_warn("config.json", "No config.json found - using defaults")

except Exception as e:
    test_fail("Configuration loading", str(e))

print()

# ==============================================================================
# Test 5: Completed tracking
# ==============================================================================
print("[5/7] Testing completed file tracking...")

try:
    from transfer_daemon import save_completed, load_completed, completed, get_csv_path

    # Clear current completed set
    completed.clear()

    # Create a temporary completed file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.completed.txt', delete=False) as f:
        temp_completed = Path(f.name)
        f.write("test_file_1\n")
        f.write("test_file_2\n")
        f.write("test_file_3\n")

    try:
        # Temporarily override CONFIG to use temp file
        original_csv = transfer_daemon.CONFIG['csv_file']
        transfer_daemon.CONFIG['csv_file'] = str(temp_completed.with_suffix('.csv'))

        # Create the fake CSV
        temp_completed.with_suffix('.csv').touch()

        # Load completed
        load_completed()

        if len(completed) == 3:
            test_pass("Loaded completed file IDs")
        else:
            test_fail("Load completed", f"Expected 3 IDs, got {len(completed)}")

        # Test save_completed
        save_completed('test_file_4')

        # Verify it was written
        with open(temp_completed) as f:
            lines = [l.strip() for l in f if l.strip()]

        if 'test_file_4' in lines:
            test_pass("save_completed() writes to file")
        else:
            test_fail("save_completed()", "New ID not found in file")

        # Restore original config
        transfer_daemon.CONFIG['csv_file'] = original_csv

    finally:
        # Cleanup
        temp_completed.unlink(missing_ok=True)
        temp_completed.with_suffix('.csv').unlink(missing_ok=True)

except Exception as e:
    test_fail("Completed file tracking", str(e))

print()

# ==============================================================================
# Test 6: Backoff exponential growth
# ==============================================================================
print("[6/7] Testing backoff exponential growth...")

try:
    from transfer_daemon import backoff_delay, CONFIG

    delays = [backoff_delay(i) for i in range(1, 6)]

    # Verify exponential growth (each should be roughly 2x previous)
    is_exponential = True
    for i in range(1, len(delays)):
        ratio = delays[i] / delays[i-1]
        # Should be around 2.0 (allowing some tolerance for max cap)
        if ratio < 1.5 or ratio > 2.5:
            if delays[i] != delays[i-1]:  # Allow equal if at max
                is_exponential = False
                break

    if is_exponential or all(d == delays[-1] for d in delays[-3:]):  # or all maxed out
        test_pass("Backoff delays grow exponentially")
        print(f"  Delays: {[f'{d:.1f}s' for d in delays]}")
    else:
        test_fail("Backoff delays", f"Not exponential: {delays}")

    # Verify max cap is enforced
    max_backoff = CONFIG.get('backoff_max_sec', 900)
    if all(d <= max_backoff for d in delays):
        test_pass("Backoff respects maximum cap")
    else:
        test_fail("Backoff max cap", f"Some delays exceed {max_backoff}s")

except Exception as e:
    test_fail("Backoff exponential growth", str(e))

print()

# ==============================================================================
# Test 7: Job file atomicity
# ==============================================================================
print("[7/7] Testing job file atomic writes...")

try:
    from transfer_daemon import write_job

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_atomic.json"

        # Write job data
        test_data = {
            'file_id': 'atomic_test',
            'data': 'x' * 10000,  # Large enough to be non-atomic without proper handling
        }

        write_job(test_file, test_data)

        # Verify file exists
        if test_file.exists():
            test_pass("Atomic write creates file")
        else:
            test_fail("Atomic write", "File not created")

        # Verify no .tmp file remains
        tmp_file = test_file.with_suffix(test_file.suffix + '.tmp')
        if not tmp_file.exists():
            test_pass("Atomic write cleanup (no .tmp file)")
        else:
            test_fail("Atomic write cleanup", "Temp file still exists")

        # Verify content
        with open(test_file) as f:
            loaded = json.load(f)

        if loaded == test_data:
            test_pass("Atomic write preserves data integrity")
        else:
            test_fail("Atomic write data", "Data corruption detected")

except Exception as e:
    test_fail("Job file atomic writes", str(e))

print()

# ==============================================================================
# Summary
# ==============================================================================
print("=" * 70)
print("Integration Test Summary")
print("=" * 70)
print(f"PASSED:   {passed}")
print(f"FAILED:   {failed}")
print(f"WARNINGS: {warnings}")
print()

if failed == 0:
    print("✓ All integration tests passed!")
    sys.exit(0)
else:
    print("✗ Some integration tests failed. Please review the errors above.")
    sys.exit(1)
