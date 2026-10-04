@echo off
title WhatsApp Test Send - Anoop P
cd /d "%~dp0"

echo ============================================================
echo   WHATSAPP TEST SEND TO: +919633889430
echo ============================================================
echo.
echo A Chrome window will open.
echo If it asks to scan QR code, scan it using WhatsApp Linked Devices.
echo Once connected, it will automatically send the report image!
echo.

venv\Scripts\python.exe login_whatsapp.py

echo.
pause
