#!/usr/bin/env python3
"""
URL Refresher Module for Drive Capture Transfer Daemon

Fetches fresh videoplayback URLs directly using Playwright browser automation.
This allows the transfer daemon to refresh expired URLs without going through
the Chrome extension round-trip.
"""

import json
import os
import time
from pathlib import Path
from typing import List, Optional, Callable

# Default maximum age for URLs before considering them expired (4 hours)
URL_MAX_AGE_SEC = 4 * 3600

# Try to import Playwright
try:
    from playwright.sync_api import sync_playwright, Response
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def is_url_expired(created_at: float, max_age: float = URL_MAX_AGE_SEC) -> bool:
    """Check if a URL is likely expired based on its creation timestamp.

    Args:
        created_at: Unix timestamp when the URL was captured
        max_age: Maximum age in seconds before URL is considered expired

    Returns:
        True if URL is older than max_age, False otherwise
    """
    return (time.time() - created_at) > max_age


def get_chrome_user_data_dir() -> Optional[str]:
    """Detect the default Chrome user data directory for the current platform."""
    import platform
    system = platform.system()
    home = Path.home()

    if system == 'Darwin':  # macOS
        path = home / 'Library' / 'Application Support' / 'Google' / 'Chrome'
    elif system == 'Windows':
        path = home / 'AppData' / 'Local' / 'Google' / 'Chrome' / 'User Data'
    else:  # Linux
        path = home / '.config' / 'google-chrome'

    return str(path) if path.exists() else None


def fetch_fresh_urls(
    file_id: str,
    user_data_dir: Optional[str] = None,
    timeout_ms: int = 30000,
    log_fn: Optional[Callable[[str, str], None]] = None
) -> List[str]:
    """
    Fetch fresh videoplayback URLs for a Google Drive file using Playwright.

    Opens the Drive file viewer page in a headless browser and intercepts
    the API response containing streaming URLs.

    Args:
        file_id: Google Drive file ID
        user_data_dir: Path to Chrome user data directory (for cookies/session).
                       If None, attempts to detect default location.
        timeout_ms: Page load timeout in milliseconds
        log_fn: Optional logging function with signature (msg, level)

    Returns:
        List of videoplayback URLs (highest quality last), or empty list on failure
    """
    if not PLAYWRIGHT_AVAILABLE:
        if log_fn:
            log_fn("Playwright not available - install with: pip install playwright && playwright install chromium", "WARN")
        return []

    def log(msg: str, level: str = 'INFO') -> None:
        if log_fn:
            log_fn(msg, level)
        else:
            print(f"[{level}] {msg}")

    # Auto-detect Chrome profile if not provided
    if not user_data_dir:
        user_data_dir = get_chrome_user_data_dir()
        if user_data_dir:
            log(f"[{file_id[:8]}] Using Chrome profile: {user_data_dir}")

    urls: List[str] = []

    def handle_response(response: Response) -> None:
        nonlocal urls
        try:
            if 'workspacevideo-pa.clients6.google.com' in response.url:
                if response.status == 200:
                    body = response.body()
                    data = json.loads(body)
                    transcodes = (
                        data.get('mediaStreamingData', {})
                        .get('formatStreamingData', {})
                        .get('progressiveTranscodes', [])
                    )
                    urls = [t['url'] for t in transcodes if t.get('url')]
                    if urls:
                        log(f"[{file_id[:8]}] Captured {len(urls)} fresh URL(s)")
        except Exception as e:
            log(f"[{file_id[:8]}] Response parse error: {e}", "WARN")

    browser = None
    try:
        with sync_playwright() as p:
            # Launch browser with persistent context to use existing cookies
            # We use chromium in a way that can access the user's Chrome cookies
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-first-run',
            ]

            if user_data_dir and Path(user_data_dir).exists():
                # Use persistent context with Chrome's user data
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=True,
                    args=launch_args,
                    channel='chrome',  # Use installed Chrome
                )
                page = context.new_page()
            else:
                # Fallback: launch without user data (likely won't have auth)
                log(f"[{file_id[:8]}] No Chrome profile found, launching without cookies", "WARN")
                browser = p.chromium.launch(headless=True, args=launch_args)
                context = browser.new_context()
                page = context.new_page()

            # Set up response interception
            page.on('response', handle_response)

            # Navigate to Drive file viewer
            drive_url = f'https://drive.google.com/file/d/{file_id}/view'
            log(f"[{file_id[:8]}] Loading {drive_url}")

            page.goto(drive_url, timeout=timeout_ms, wait_until='networkidle')

            # Give extra time for the video API call to complete
            page.wait_for_timeout(3000)

            # Cleanup
            context.close()
            if browser:
                browser.close()

    except Exception as e:
        log(f"[{file_id[:8]}] Playwright error: {e}", "ERROR")
        if browser:
            try:
                browser.close()
            except:
                pass

    return urls


def refresh_job_urls(
    job: dict,
    max_age: float = URL_MAX_AGE_SEC,
    log_fn: Optional[Callable[[str, str], None]] = None
) -> dict:
    """
    Check if a job's URLs are expired and refresh them if needed.

    Args:
        job: Job dictionary with 'file_id', 'urls', 'created_at' keys
        max_age: Maximum URL age in seconds before refresh
        log_fn: Optional logging function

    Returns:
        Updated job dictionary (modifies in place and returns)
    """
    file_id = job.get('file_id', '')
    created_at = float(job.get('created_at', 0))

    if not is_url_expired(created_at, max_age):
        return job

    if log_fn:
        age_hours = (time.time() - created_at) / 3600
        log_fn(f"[{file_id[:8]}] URL is {age_hours:.1f}h old, refreshing...", "INFO")

    fresh_urls = fetch_fresh_urls(file_id, log_fn=log_fn)

    if fresh_urls:
        job['urls'] = fresh_urls
        job['created_at'] = time.time()
        job['refreshed_at'] = time.time()
        if log_fn:
            log_fn(f"[{file_id[:8]}] Refreshed with {len(fresh_urls)} URL(s)", "INFO")
    else:
        if log_fn:
            log_fn(f"[{file_id[:8]}] URL refresh failed, using original URLs", "WARN")

    return job


# CLI for testing
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python url_refresher.py <file_id>")
        sys.exit(1)

    file_id = sys.argv[1]
    print(f"Fetching URLs for file: {file_id}")

    if not PLAYWRIGHT_AVAILABLE:
        print("ERROR: Playwright not installed")
        print("Install with: pip install playwright && playwright install chromium")
        sys.exit(1)

    urls = fetch_fresh_urls(file_id)

    if urls:
        print(f"\nFound {len(urls)} URL(s):")
        for i, url in enumerate(urls):
            print(f"  [{i+1}] {url[:100]}...")
    else:
        print("\nNo URLs found. Make sure you're logged into Google Drive in Chrome.")
