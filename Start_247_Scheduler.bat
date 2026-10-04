@echo off
title Daily Complaint Report Automation - 24/7 Scheduler
cd /d "%~dp0"

echo ============================================================
echo   DAILY COMPLAINT PENDING REPORT - 24/7 SCHEDULER
echo   Scheduled Times: 08:00 AM and 03:00 PM
echo ============================================================
echo.
echo Keeping background service active... (Minimize this window)
echo.

venv\Scripts\python.exe main.py --schedule

pause
