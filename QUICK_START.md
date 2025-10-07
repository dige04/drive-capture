# 🚀 Quick Start Guide

## 3-Minute Setup

### macOS/Linux
```bash
# 1. Run installer
./setup/install.sh

# 2. Follow prompts (paste Extension ID)

# 3. Done! Check Chrome extension popup
```

### Windows
```cmd
# 1. Run installer
setup\install.cmd

# 2. Follow prompts (paste Extension ID)  

# 3. Done! Check Chrome extension popup
```

## That's it! 

The system is now ready. Place your `list.csv` in the `data/` folder and the worker will start processing.

---

## Key Differences from v1

| Feature | Old (v1) | New (v2) |
|---------|----------|----------|
| Setup | Manual, complex | One-click |
| Code | 500+ lines | ~300 lines |
| Connection | Complex ACK system | Simple ping-pong |
| Files | 30+ files | 10 files |
| Debugging | Difficult | Easy - clear logs |

## File Locations

- **CSV file**: `data/list.csv`
- **Completed tracking**: `data/list.completed.txt`
- **Config**: `worker/config.json`
- **Logs**: Run `python worker/worker.py` to see

## Common Commands

```bash
# Test worker manually
cd worker && python3 -u worker.py

# Check extension ID
chrome://extensions

# View connection status
Click extension icon in Chrome
```

## If Something Goes Wrong

1. **Python not found?**
   - Install from python.org
   - Windows: Check "Add to PATH"

2. **Worker not connecting?**
   - Restart Chrome completely
   - Re-run installer

3. **Capture not working?**
   - Check CSV format
   - Verify file IDs are correct

---

**Remember**: Simpler is better! This version removes all unnecessary complexity while keeping core functionality intact.
