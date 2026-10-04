@echo off
title Asianet Regional Operations Manager - Web Server
cd /d "%~dp0"
echo ============================================================
echo  Asianet Kerala Network Tracker - Regional Operations Manager
echo ============================================================
echo Starting Web Dashboard on http://127.0.0.1:8201 ...
echo Press Ctrl+C to stop the server.
echo.

python -m uvicorn web_server:app --host 127.0.0.1 --port 8201 --reload
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Trying with virtual environment python...
    venv\Scripts\python.exe -m uvicorn web_server:app --host 127.0.0.1 --port 8201 --reload
)
pause
