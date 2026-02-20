@echo off
chcp 65001 >nul
title YJ Partners Command Center
cd /d "%~dp0\.."

echo ══════════════════════════════════════════
echo   YJ Partners Command Center
echo ══════════════════════════════════════════

:: Check for venv first
if exist "AI_Command_Center\venv\Scripts\python.exe" (
    set PYTHON=AI_Command_Center\venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [*] Python: %PYTHON%
echo [*] Starting Command Center...
echo.

%PYTHON% -m command_center.main

if errorlevel 1 (
    echo.
    echo [ERROR] Command Center failed to start!
    echo Try: pip install PyQt6 requests python-dotenv google-genai anthropic
    pause
)
