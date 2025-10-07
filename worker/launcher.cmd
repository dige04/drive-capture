@echo off
REM Windows launcher for native messaging host

cd /d "%~dp0"

REM Add common rclone paths to PATH
set "PATH=%~dp0;%~dp0..\;%PROGRAMFILES%\rclone;%PROGRAMFILES(x86)%\rclone;%USERPROFILE%\rclone;%PATH%"

REM Try different Python commands
where python >nul 2>&1 && goto :python
where python3 >nul 2>&1 && goto :python3
where py >nul 2>&1 && goto :py

REM No Python found
echo Python not found! Please install Python and add to PATH
exit /b 1

:python
python -u worker.py
exit /b %ERRORLEVEL%

:python3
python3 -u worker.py
exit /b %ERRORLEVEL%

:py
py -u worker.py
exit /b %ERRORLEVEL%
