@echo off
REM Quick test for Windows setup
echo =====================================
echo   Drive Capture v2 - Windows Test
echo =====================================
echo.

REM Test Python
echo Checking Python...
python --version 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Python is installed
    echo.
    echo Ready to run: setup\install.cmd
) else (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python from python.org
    echo IMPORTANT: Check "Add Python to PATH"
    echo.
    echo After installing Python, run this test again
)
echo.
pause
