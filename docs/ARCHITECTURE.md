# Architecture Overview

## Design Principles

1. **Simplicity First**: Remove all unnecessary complexity
2. **Robust Connection**: Basic but reliable reconnection
3. **Clear Separation**: Extension handles capture, Worker handles transfer
4. **Easy Debugging**: All logs to stderr, clear error messages

## Component Communication

```
Chrome Extension                    Python Worker
     (JS)                              (Python)
       |                                  |
       |---- Native Messaging Port -------|
       |                                  |
   background.js <---> stdio <---> worker.py
       |                                  |
   - Open tabs                     - Read CSV
   - Attach debugger               - Queue jobs  
   - Capture URLs                  - Run rclone
   - Send results                  - Track progress
```

## Message Protocol

### Simple JSON messages over Native Messaging:

```json
// Extension → Worker
{ "type": "hello", "version": "2.0" }
{ "type": "pong" }
{ "type": "result", "file_id": "xxx", "url": "...", "error": null }

// Worker → Extension  
{ "type": "ready" }
{ "type": "ping" }
{ "type": "capture", "file_id": "xxx" }
```

## Connection Lifecycle

1. **Startup**
   - Extension connects to native host
   - Worker sends `ready`
   - Connection established

2. **Heartbeat**
   - Worker sends `ping` every 20s
   - Extension responds with `pong`
   - Keeps connection alive

3. **Capture Flow**
   - Worker sends `capture` request
   - Extension opens tab, captures URL
   - Extension sends `result` back
   - Worker runs rclone transfer

4. **Reconnection**
   - On disconnect, exponential backoff
   - 1s → 2s → 4s → 8s → 16s → 30s (max)
   - Chrome alarms as backup (30s)

## File Structure Reasoning

```
extension/          # Chrome-specific code only
worker/            # Python-specific code only  
setup/             # Platform-specific installers
data/              # User data (CSV, progress)
docs/              # Documentation
```

## Simplifications from v1

### Removed:
- ACK mechanism (unnecessary complexity)
- Correlation IDs (not needed with simple protocol)
- Idempotency store (CSV tracking is enough)
- Multiple message queues (one queue is simpler)
- Complex retry logic (basic retry is sufficient)

### Kept:
- Core capture logic
- Rclone integration
- Progress tracking
- Auto-reconnection
- Cross-platform support

## Error Handling

### Simple approach:
1. Log errors clearly
2. Continue processing other jobs
3. Mark failed jobs in completed file
4. No complex recovery mechanisms

## Performance

### Designed for:
- 1-5 concurrent captures
- 1-10 parallel transfers
- 100-10,000 files per session
- Long-running sessions (hours/days)

### Not optimized for:
- High-frequency captures (>10/sec)
- Massive parallelism (>20 concurrent)
- Real-time requirements

## Security

- Extension only accesses drive.google.com
- Worker runs with user permissions
- No external dependencies
- No network calls except rclone

## Platform Differences

### Windows:
- Binary mode for stdin/stdout
- Registry for native messaging
- .cmd launcher script

### macOS:
- Text mode stdio (default)
- ~/Library path for manifest
- .sh launcher script

Both use identical Python code and Chrome extension.
