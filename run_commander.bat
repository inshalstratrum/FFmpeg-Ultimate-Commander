@echo off
title FFmpeg Ultimate Commander
cd /d "%~dp0"

echo ========================================================
echo   FFmpeg Ultimate Commander - Launching...
echo ========================================================

where pythonw >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" pythonw ffmpeg_gui.py
    exit /b 0
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" python ffmpeg_gui.py
    exit /b 0
)

echo [ERROR] Python not found on PATH.
pause
