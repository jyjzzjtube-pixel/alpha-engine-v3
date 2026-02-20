@echo off
title AI Command Center - Master Bot
echo ============================================
echo   AI COMMAND CENTER - Starting...
echo ============================================
cd /d "%~dp0"
call venv\Scripts\activate
python master_bot.py
pause
