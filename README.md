# Drive Capture v2

Simplified, robust video capture system for Google Drive. Works on Windows & macOS.

## 🎯 Features

- **Simple**: Minimal code, easy to understand
- **Robust**: Auto-reconnect, error recovery
- **Cross-platform**: Windows & macOS support
- **Fast setup**: One-click installer scripts

## 📁 Project Structure

```
drive-capture-v2/
├── extension/          # Chrome extension
│   ├── manifest.json
│   ├── background.js   # Service worker
│   ├── popup.html/js   # Status UI
│   └── icon.png
├── worker/            # Python worker
│   ├── worker.py      # Main script
│   ├── launcher.cmd   # Windows launcher
│   ├── launcher.sh    # macOS launcher
│   └── config.json    # Configuration
├── setup/             # Installers
│   ├── install.cmd    # Windows
│   └── install.sh     # macOS/Linux
├── data/              # CSV files
│   └── list.csv       # Your job list
└── README.md
```

## 🚀 Quick Start

### Prerequisites

1. **Python 3.7+** installed
2. **Google Chrome** (version 88+)
3. **rclone** configured with your cloud storage (which rclone)

- User-Agent for Mac/Linux/Win

### Installation

#### Windows

1. Run setup script:
   ```cmd
   setup\install.cmd
   ```
2. Follow the prompts
3. Restart Chrome

#### macOS/Linux

1. Run setup script:
   ```bash
   chmod +x setup/install.sh
   ./setup/install.sh
   ```
2. Follow the prompts
3. Restart Chrome

## 📋 CSV Format

Create `data/list.csv` with this format:

```csv
file_id,folder_path,file_name,size,mime_type,mod_time,md5
abc123def,/Videos,video1.mp4,1048576,video/mp4,2024-01-01T00:00:00,hash1
ghi456jkl,/Videos,video2.mp4,2097152,video/mp4,2024-01-02T00:00:00,hash2
```

Required columns:
- `file_id`: Google Drive file ID
- `folder_path`: Target folder in your cloud storage
- `file_name`: Target filename

## ⚙️ Configuration

Edit `worker/config.json`:

```json
{
  "rclone_remote": "your_remote_name",
  "csv_file": "../data/list.csv",
  "max_parallel": 3,
  "max_captures": 2
}
```

## 🔍 How It Works

1. **Extension** opens Drive URLs and captures video links
2. **Worker** receives URLs and transfers with rclone
3. **Connection** maintained via Chrome Native Messaging
4. **Progress** tracked in `list.completed.txt`

## 🛠️ Troubleshooting

### Worker Not Connected

1. Check Python is installed: `python --version`
2. Verify extension loaded in Chrome
3. Check logs: `python worker/worker.py` (run manually)

### On Windows

- Run installer as Administrator if needed
- Check registry: `reg query "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.drivecapture.worker"`

### On macOS

- Remove quarantine: `xattr -cr drive-capture-v2/`
- Check manifest: `ls ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/`

## 📊 Status Indicators

Extension popup shows:
- 🟢 **Connected**: Worker is ready
- 🔴 **Disconnected**: Worker not running
- **Active tabs**: Current capture tabs
- **Current job**: File being processed

## 🔄 Manual Control

### Start Worker Manually

Windows:
```cmd
cd worker
python -u worker.py
```

macOS:
```bash
cd worker
python3 -u worker.py
```

### Test Connection

1. Open extension popup
2. Click "Test Connection"
3. Check worker console for ping/pong

## 📝 Advanced Usage

### Custom CSV Location

Edit `worker/config.json`:
```json
"csv_file": "C:/path/to/your/file.csv"
```

### Change Parallel Limits

```json
"max_parallel": 5,     // rclone transfers
"max_captures": 3      // Chrome tabs
```

### Different rclone Remote

```json
"rclone_remote": "mydrive"
```

## 🐛 Debug Mode

Run worker directly to see all logs:

```bash
cd worker
python3 -u worker.py 2>&1 | tee debug.log
```

## 📄 License

MIT License - Use freely

## 🤝 Support

Issues? Check:
1. Extension console: chrome://extensions → Service Worker → Console
2. Worker output: Run `python worker.py` manually
3. CSV format: Ensure proper columns and encoding

---

**Version 2.0** - Simplified & Robust
