# Windows VPS Quick Setup

## 🚀 One-Line Clone & Setup

Open Command Prompt and run:

```cmd
git clone https://github.com/dige04/drive-capture-v2.git && cd drive-capture-v2 && setup\install.cmd
```

Or PowerShell:
```powershell
git clone https://github.com/dige04/drive-capture-v2.git; cd drive-capture-v2; .\setup\install.cmd
```

## 📋 Manual Steps

### 1. Clone Repository
```cmd
git clone https://github.com/dige04/drive-capture-v2.git
cd drive-capture-v2
```

### 2. Run Installer
```cmd
setup\install.cmd
```

### 3. Load Extension in Chrome
1. Open Chrome: `chrome://extensions`
2. Enable Developer Mode
3. Load unpacked → Select `drive-capture-v2\extension` folder
4. Copy Extension ID

### 4. Complete Setup
- Paste Extension ID when prompted
- Restart Chrome

## ✅ Verify Connection

1. Click extension icon in Chrome
2. Should show "✅ Connected to worker"

## 🔍 Troubleshooting

### Python Not Found
```cmd
# Check if Python installed
python --version

# If not, download from python.org
# IMPORTANT: Check "Add Python to PATH" during install
```

### Registry Issues
Run as Administrator:
```cmd
cd drive-capture-v2
setup\install.cmd
```

### Test Worker Manually
```cmd
cd drive-capture-v2\worker
python -u worker.py
```

## 📁 Important Paths

- Extension: `C:\...\drive-capture-v2\extension\`
- Worker: `C:\...\drive-capture-v2\worker\`
- CSV: `C:\...\drive-capture-v2\data\list.csv`
- Config: `C:\...\drive-capture-v2\worker\config.json`

## 🎯 Quick Test

After setup, test with dummy CSV:
```cmd
copy data\list.csv.example data\list.csv
```

Then check extension popup - it should connect!

---

**GitHub:** https://github.com/dige04/drive-capture-v2
