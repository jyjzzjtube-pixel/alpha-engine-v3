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
    set PYTHONW=AI_Command_Center\venv\Scripts\pythonw.exe
) else (
    set PYTHON=python
    set PYTHONW=pythonw
)

echo [*] Python: %PYTHON%

:: Check PyQt6 installed
%PYTHON% -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo [!] PyQt6 not found. Installing dependencies...
    %PYTHON% -m pip install PyQt6 requests python-dotenv google-genai anthropic
    echo.
)

echo [*] Starting Command Center...
echo.

:: Run with python.exe (not pythonw) so errors are visible in console
%PYTHON% -m command_center.main

if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════
    echo   [ERROR] Command Center crashed!
    echo ══════════════════════════════════════════
    echo.
    echo Check logs: command_center\logs\
    echo.
    echo Try reinstalling: %PYTHON% -m pip install --upgrade PyQt6 requests python-dotenv google-genai anthropic
    echo.
    pause
)
