@echo off
REM =====================================================
REM  Drive Capture v2 - Windows Auto Installer
REM =====================================================

setlocal enabledelayedexpansion
cls
color 0A

echo =====================================================
echo     Drive Capture v2 - Windows Setup
echo =====================================================
echo.

REM Get script directory (parent of setup folder)
set SCRIPT_DIR=%~dp0..
cd /d "%SCRIPT_DIR%"
set PROJECT_DIR=%CD%

echo Project directory: %PROJECT_DIR%
echo.

REM Step 1: Check Python
echo [1] Checking Python...
set PYTHON_CMD=python
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=python3
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python not found!
        echo Please install Python from python.org
        echo Make sure to check "Add Python to PATH"
        pause
        exit /b 1
    )
)
echo [OK] Python found (%%PYTHON_CMD%%)
%%PYTHON_CMD%% --version
echo.

REM Step 2: Load Extension
echo [2] Chrome Extension Setup
echo ---------------------------
echo.
echo Please:
echo 1. Open Chrome and go to: chrome://extensions
echo 2. Enable "Developer mode" (top right)
echo 3. Click "Load unpacked"
echo 4. Select folder: %PROJECT_DIR%\extension
echo 5. Copy the Extension ID shown
echo.
set /p EXTENSION_ID=Paste Extension ID here: 

if "%EXTENSION_ID%"=="" (
    echo [ERROR] Extension ID required!
    pause
    exit /b 1
)
echo.

REM Step 3: Create Native Messaging Manifest
echo [3] Creating native messaging manifest...

set MANIFEST_FILE=%PROJECT_DIR%\worker\com.drivecapture.worker.json
set LAUNCHER_PATH=%PROJECT_DIR%\worker\launcher.cmd
set LAUNCHER_PATH_JSON=%LAUNCHER_PATH:\=\\%

(
echo {
echo   "name": "com.drivecapture.worker",
echo   "description": "Drive Capture v2 Worker",
echo   "path": "%LAUNCHER_PATH_JSON%",
echo   "type": "stdio",
echo   "allowed_origins": [
echo     "chrome-extension://%EXTENSION_ID%/"
echo   ]
echo }
) > "%MANIFEST_FILE%"

echo [OK] Manifest created
echo.

REM Step 4: Register with Windows
echo [4] Registering with Windows...

set REG_PATH=HKCU\Software\Google\Chrome\NativeMessagingHosts\com.drivecapture.worker
reg add "%REG_PATH%" /ve /d "%MANIFEST_FILE%" /f >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo [OK] Registry updated
) else (
    echo [ERROR] Registry update failed
    echo Try running as Administrator
    pause
    exit /b 1
)
echo.

REM Step 5: Create config
echo [5] Creating configuration...

set /p "rclone_remote=Enter your rclone remote name (default: ngonga339): "
set /p "csv_file_num=Enter the CSV file number to use, 1-20 (default: 1): "
set /p "max_parallel_rclone=Enter the max parallel rclone jobs (default: 3): "
set /p "rclone_path=Enter the absolute path to your rclone executable (e.g., C:\rclone\rclone.exe): "

if not defined rclone_remote set "rclone_remote=ngonga339"
if not defined csv_file_num set "csv_file_num=1"
if not defined max_parallel_rclone set "max_parallel_rclone=3"
if not defined rclone_path set "rclone_path="

set CONFIG_FILE=%PROJECT_DIR%\worker\config.json

(
  echo {
  echo   "rclone_remote": "%rclone_remote%",,
  echo   "csv_file": "../data/list%csv_file_num%.csv",,
  echo   "max_parallel": %max_parallel_rclone%,,
  echo   "max_captures": 1,,
  echo   "rclone_path": "%rclone_path%"
  echo }
) > "%CONFIG_FILE%"

echo [OK] Configuration created: %CONFIG_FILE%
echo.

REM Step 6: Test
echo [6] Testing Python worker...
cd /d "%PROJECT_DIR%\worker"
echo.
echo If you see "Drive Capture Worker v2.0 Starting", it works!
echo This test will run for 5 seconds...
echo.

REM Start the worker in a new window, wait 5s, then kill it.
start "Python Worker Test" %PYTHON_CMD% -u worker.py
timeout /t 5 /nobreak >nul
taskkill /fi "WINDOWTITLE eq Python Worker Test*" /f >nul 2>&1

echo.
echo =====================================================
echo     Installation Complete!
echo =====================================================
echo.
echo Next steps:
echo 1. Place your CSV file in: %PROJECT_DIR%\data\list.csv
echo 2. Configure rclone if not done
echo 3. Restart Chrome
echo 4. Check extension popup for connection status
echo.
echo Extension ID: %EXTENSION_ID%
echo.
pause
