# Gemini Code Assistant Context

## Project Overview

This project, "Drive Capture v2," is a system for automating the capture of video stream URLs from Google Drive and downloading them using `rclone`. It is designed to be simple, robust, and cross-platform (Windows & macOS).

The system consists of two main components:

1.  **Chrome Extension:** A browser extension that runs in Google Chrome. It is responsible for programmatically opening Google Drive video pages, capturing the underlying video stream URLs, and passing them to the Python worker.

2.  **Python Worker:** A background process that communicates with the Chrome extension via Native Messaging. It manages a queue of video files to be downloaded (from a CSV file), receives stream URLs from the extension, and uses the `rclone` command-line tool to download the files to a configured cloud storage remote.

The communication between the extension and the worker is handled via standard input/output, using a simple JSON-based messaging protocol.

## Building and Running

### Prerequisites

*   Python 3.7+
*   Google Chrome (version 88+)
*   `rclone` configured with a cloud storage remote.

### Installation

The project includes interactive installation scripts for different operating systems:

*   **Windows:** `setup\install.cmd`
*   **macOS/Linux:** `setup/install.sh`

These scripts handle the following:
*   Verifying Python installation.
*   Guiding the user to load the Chrome extension and providing its ID.
*   Creating the Native Messaging manifest (`com.drivecapture.worker.json`) and registering it with Chrome.
*   Generating a `worker/config.json` file based on user input for the `rclone` remote, CSV file, and other settings.

### Running the Application

The Python worker is designed to be launched automatically by the Chrome extension through the Native Messaging interface. The launcher scripts are:

*   **Windows:** `worker\launcher.cmd`
*   **macOS/Linux:** `worker/launcher.sh`

To start the process, the user needs to:
1.  Ensure the `rclone` remote is correctly configured.
2.  Create a `data/list.csv` file with the Google Drive `file_id` of the videos to be downloaded.
3.  The extension's popup provides connection status and basic progress information.

### Manual Execution for Debugging

The worker can be run manually to view logs and debug issues:

*   **Windows:**
    ```cmd
    cd worker
    python -u worker.py
    ```

*   **macOS/Linux:**
    ```bash
    cd worker
    python3 -u worker.py
    ```

## Development Conventions

### Code Structure

The project is organized into the following directories:

*   `extension/`: Contains the Chrome extension files (manifest, background scripts, UI).
*   `worker/`: Contains the Python worker script, launchers, and configuration.
*   `setup/`: Contains the installation scripts.
*   `data/`: Contains the user-provided CSV files and completion logs.
*   `docs/`: Contains architecture and other documentation.

### Communication Protocol

The `docs/ARCHITECTURE.md` file outlines the simple JSON-based message protocol used for communication between the extension and the worker. Key messages include:

*   `hello`/`ready`: For the initial handshake.
*   `ping`/`pong`: For heartbeat and keeping the connection alive.
*   `capture`: Sent from the worker to the extension to request a video capture.
*   `result`: Sent from the extension to the worker with the captured URL or an error.

### Configuration

The primary configuration is done via `worker/config.json`, which includes:

*   `rclone_remote`: The name of the `rclone` remote to use for uploads.
*   `csv_file`: The path to the input CSV file.
*   `max_parallel`: The number of concurrent `rclone` transfers.
*   `max_captures`: The number of concurrent Chrome tabs to open for capturing.
*   `rclone_path`: An optional absolute path to the `rclone` executable.

### CSV Format

The input `data/list.csv` file requires the following columns:
*   `file_id`: The Google Drive file ID.
*   `folder_path`: The target folder in the cloud storage.
*   `file_name`: The target filename.
