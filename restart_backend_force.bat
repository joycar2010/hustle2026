@echo off
echo ========================================
echo Backend Server FORCE Restart
echo ========================================
echo.
echo This script will forcefully:
echo 1. Stop ALL processes on port 8000
echo 2. Start the backend server
echo.
echo Requesting administrator privileges...
echo.

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& {Start-Process PowerShell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0restart_backend_force.ps1\"' -Verb RunAs}"

echo.
echo Script launched. Check the new PowerShell window.
timeout /t 2
