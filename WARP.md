# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Common Commands & Workflows

All commands are intended to be run from the repository root.

### Install / Register Native Host

macOS / Linux (interactive installer):

```bash
./setup/install.sh
```

Windows (interactive installer):

```cmd
setup\install.cmd
```

These installers:
- Verify Python is available.
- Guide you through loading the Chrome extension and capturing its ID.
- Generate and install the Native Messaging manifest (`worker/com.drivecapture.worker.json`) pointing to the appropriate launcher script.
- Create `worker/config.json` with the selected `rclone` remote, CSV file, parallelism, and optional `rclone_path`.

### Run Worker Manually (Debug / Logs)

macOS / Linux:

```bash
cd worker
python3 -u worker.py
```

Windows:

```cmd
cd worker
python -u worker.py
```

This is the primary way to observe detailed logs, verify CSV loading, and debug capture/transfer behavior.

### Quick Smoke Test from Installer (macOS/Linux)

The installer includes a short worker smoke test (non-interactive):

```bash
./setup/install.sh   # follow prompts; near the end it runs a 3s worker test
```

If you need to replicate the smoke test behavior manually, just run the worker as shown above and watch for the startup banner in stderr.

### Notes on Tests / Linting

There is currently no automated test or linting setup in this repository. Development and debugging flows rely on running the Python worker directly and using the Chrome extension UI/console.

## High-Level Architecture

Drive Capture v2 is a two-process system tied together via Chrome Native Messaging:

- A **Chrome extension** (`extension/`) that opens Google Drive video pages, captures underlying video stream URLs via the Chrome DevTools protocol, and reports them to the worker.
- A **Python worker** (`worker/worker.py`) that reads a CSV of jobs, requests captures for each file, and uses `rclone copyurl` to transfer content to a configured remote.
- **Installers** (`setup/install.*`) that register the worker as a Native Messaging host and generate per-machine configuration.

### Top-Level Data & Config

- Input jobs: `data/list*.csv` (columns like `file_id`, `folder_path`, `file_name`, etc.).
- Completion tracking: `data/list*.completed.txt` (one `file_id` per line) auto-maintained by the worker.
- Worker configuration: `worker/config.json` (created/updated by installers, may be edited manually for advanced setups).

### Chrome Extension (Native Host Client)

Key files:
- `extension/manifest.json` – Chrome extension manifest (declares background service worker and permissions).
- `extension/background.js` – background service worker handling native host connection and capture pipeline.
- `extension/popup.html` + `extension/popup.js` – small UI to show connection state, active tab count, and extension ID.

Responsibilities (from `background.js`):
- **Native host connection & robustness**
  - Connects to the Python host `com.drivecapture.worker` via `chrome.runtime.connectNative`.
  - Implements exponential backoff reconnects (`RECONNECT_DELAYS`) and a watchdog using `chrome.alarms` that restarts the native connection if no messages arrive for a while.
  - Handles a simple message protocol:
    - From worker → extension: `ready`, `ping`, `capture`, `rclone_status`, `rclone_progress`, `rclone_error`, `reset_requested`.
    - From extension → worker: `hello`, `pong`, `result`.
  - On `reset_requested` (e.g., too many rclone failures or transport errors), it either reloads the extension (with a cooldown) or restarts the native connection.

- **Capture pipeline (Drive video URL extraction)**
  - On `capture` messages, opens a background tab to `https://drive.google.com/file/<file_id>/view`.
  - Attaches Chrome DevTools debugger (`chrome.debugger.attach`) and enables the Network domain.
  - Listens for `Network.requestWillBeSent` and `Network.responseReceived` events targeting the `workspacevideo-pa.clients6.google.com` endpoint used by Google Drive video playback.
  - Fetches the response body via `Network.getResponseBody`, parses JSON, and extracts progressive transcode URLs from `mediaStreamingData.formatStreamingData.progressiveTranscodes`.
  - Chooses the last URL (typically highest quality) as the primary video URL but also collects all candidate URLs; both are returned to the worker in the `result` message.

- **Tab & resource management**
  - Tracks tabs it opened in `activeTabs` and associated capture state in `capturedRequests`.
  - Uses timeouts (`CAPTURE_TIMEOUT`) and a two-phase strategy: initial load, then a `chrome.tabs.reload` retry if the initial capture times out.
  - Cleans up debugger attachments and closes tabs once a capture succeeds, fails, or the tab is closed unexpectedly.

- **Popup status UI**
  - `popup.js` asks the background script for `status` and displays:
    - Connection state to the worker.
    - Number of active capture tabs.
    - Current job name (if exposed; currently the background script reports `connected` and `activeTabs`).
  - Also exposes the extension ID for use in installers and debugging.

### Python Worker (Native Host)

Key file: `worker/worker.py`.

The worker is a long-running native host that:
- Speaks the Chrome Native Messaging protocol over stdin/stdout.
- Manages job queues and concurrency.
- Orchestrates `rclone` transfers with stall detection and retry logic.

#### Configuration & startup

- Base settings are defined in `CONFIG` (e.g., `rclone_remote`, `csv_file`, `max_parallel`, `max_captures`, `rclone_path`, retry thresholds).
- If `worker/config.json` exists, it is merged into `CONFIG` at startup.
- On Windows, `msvcrt.setmode` is used to force stdin/stdout into binary mode, and all normal logging is redirected to stderr to keep the Native Messaging channel clean.

#### CSV-driven job model

- `load_jobs()` resolves the CSV path (relative to the worker directory unless absolute), loads `data/list*.csv` with `csv.DictReader`, and skips any `file_id` already present in the corresponding `.completed.txt` file.
- Each job is a dict with keys: `file_id`, `folder_path`, `file_name`, `size`, `mime_type`, `mod_time`, `md5` (some are optional).
- Completed `file_id`s are appended to `*.completed.txt` via `save_completed()`.

#### Queues & threading model

The worker uses multiple queues and threads to decouple capture from transfer:

- Queues:
  - `jobs_queue`: main backlog of pending jobs loaded from CSV.
  - `capture_queue`: jobs waiting to be handed to the extension for URL capture.
  - `transfer_queue`: `(job, url_or_urls)` pairs ready for `rclone`.
  - `transfer_done_queue`: signals used by the scheduler to know when a transfer finishes.

- Threads:
  - `capture_worker()`
    - Pulls from `capture_queue` while `len(active_captures) < max_captures`.
    - Sends `{'type': 'capture', 'file_id': ...}` to the extension and tracks the job in `active_captures`.
  - `transfer_worker()` (multiple instances up to `max_parallel`)
    - Pulls from `transfer_queue`, adds a small random jitter to avoid bursts, then calls `run_rclone()`.
    - Maintains `job_attempts` per `file_id` and a global `consecutive_failures` counter.
    - Decides whether to recapture URLs, requeue jobs, or request extension resets based on error patterns.
    - Posts a token to `transfer_done_queue` when each transfer attempt concludes.
  - `job_scheduler()`
    - Listens on `transfer_done_queue` and, for each completion signal, attempts to move the next job from `jobs_queue` into `capture_queue`.
  - `heartbeat_worker()`
    - Sends `{'type': 'ping'}` to the extension every 20s to keep the Native Messaging connection alive.

The `main()` function wires this together by:
- Loading jobs from CSV and pre-seeding `jobs_queue`.
- Priming the pipeline by moving up to `max_parallel` jobs directly into `capture_queue`.
- Spawning all worker threads.
- Entering a loop that continuously reads messages from the extension and passes them to `handle_extension_message()`.

#### Message handling & capture results

`handle_extension_message()` handles:

- `hello`
  - Logs the extension version and replies with `{'type': 'ready'}`.

- `pong`
  - Heartbeat response (no additional action).

- `result`
  - Contains `file_id`, `url` (primary URL), optional `urls` (candidate URLs array), and possibly `error`.
  - If `file_id` is in `active_captures`:
    - On success (`url` present):
      - Builds a candidate list with primary URL first and any additional candidates after it.
      - Pushes `(job, candidates)` or `(job, url)` into `transfer_queue`.
    - On failure (no `url`):
      - If attempts are below `max_recapture_attempts`, reschedules the job into `capture_queue`.
      - Otherwise, puts the job back into `jobs_queue` for later retries.

#### Rclone integration & error handling

`run_rclone(job, url_or_urls)` is responsible for performing the actual transfers:

- Resolves the `rclone` executable from `CONFIG['rclone_path']` if present, otherwise uses `rclone` from `PATH`.
- Constructs a `copyurl` command targeting `<rclone_remote>:<folder_path>/<file_name>` and sets HTTP headers (User-Agent, Referer) appropriate for Google Drive playback URLs.
- Enables multi-threaded transfers and robust retry flags (`--multi-thread-streams`, `--retries`, `--low-level-retries`, etc.).
- Starts a watchdog thread that kills stalled transfers after `stall_timeout_sec`.
- Streams rclone output line-by-line:
  - Lines containing `Transferred:` are treated as progress and occasionally forwarded to the extension via `rclone_progress` messages (rate-limited per file).
  - Lines containing `ERROR`, `Failed to copy`, or `404 Not Found` are captured, logged, and forwarded via `rclone_error` and failure `rclone_status` messages.
  - Certain transport-level errors (unexpected EOF, connection reset, HTTP/2 issues) trigger a `reset_requested` message, throttled by `reset_cooldown_sec`.
- If all candidate URLs fail, the function tells the caller whether to attempt another recapture or to back off.

The combination of per-job retry counts, global failure thresholds, and extension-driven resets gives the system a controlled way to recover from transient network or API issues without manual intervention.

### Installers & Native Messaging Integration

- `setup/install.sh` (macOS/Linux) and `setup/install.cmd` (Windows) are the user-facing entry points for configuring a machine.
- They perform the following high-level steps:
  - Ensure Python is installed and accessible.
  - Guide the user through loading the unpacked extension from `extension/` and collecting the extension ID.
  - Generate `worker/com.drivecapture.worker.json` with the correct `path` to `worker/launcher.sh` or `worker/launcher.cmd` and `allowed_origins` set to the installed extension ID.
  - Install that manifest into the appropriate OS/browser location:
    - macOS: `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`.
    - Linux: `~/.config/google-chrome/NativeMessagingHosts/`.
    - Windows: registry entry under `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.drivecapture.worker` pointing to the manifest file.
  - Create `worker/config.json` using user-provided values for `rclone_remote`, CSV index (`listN.csv`), parallelism, and optional `rclone_path`.

- `worker/launcher.sh` and `worker/launcher.cmd` are small wrappers that:
  - Normalize the working directory to `worker/`.
  - Extend `PATH` to include common rclone locations.
  - Select an appropriate Python interpreter (`python3`, `python`, or `py`) and execute `python[3] -u worker.py`.

### Additional Documentation

For more detailed background and context:
- `README.md` – end-user overview, feature list, quick start, CSV format, and troubleshooting.
- `docs/ARCHITECTURE.md` – design principles, message protocol examples, connection lifecycle, and rationale for simplifications from v1.
- `GEMINI.md` – assistant-oriented summary of project purpose, components, and configuration.
- `QUICK_START.md` – concise setup instructions and a small set of common commands.

Future instances of Warp should refer to `worker/worker.py` and `extension/background.js` as the primary entry points for understanding or modifying system behavior, and to the docs above for conceptual background before making non-trivial changes.