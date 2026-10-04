@echo off
title Daily Complaint Report Automation - Manual Run
cd /d "%~dp0"

echo ============================================================
echo   DAILY COMPLAINT PENDING REPORT - MANUAL RUN
echo ============================================================
echo.

venv\Scripts\python.exe main.py --test-local --generate-only

echo.
echo ============================================================
echo Finished. Check 'output' folder for generated report image.
echo ============================================================
pause
