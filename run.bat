@echo off
title Jimeng AI Assistant Launcher
cls

echo ============================================================
echo      Jimeng AI Prompt Extractor and Video Downloader
echo ============================================================
echo.

:: 1. Check Local Embed Python
if not exist "%~dp0python-embed\python.exe" (
    echo [ERROR] Embedded Python environment is missing!
    echo Please make sure the 'python-embed' folder exists in the project root.
    echo.
    pause
    exit
)

:: 2. Start Web Service
echo [INFO] Starting Local Web Server using embedded Python...
echo [INFO] Opening default browser...
echo.

start "" "http://127.0.0.1:5000"
"%~dp0python-embed\python.exe" "%~dp0app.py"

pause
