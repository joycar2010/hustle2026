@echo off
echo ========================================
echo Backend Server Restart Script
echo ========================================
echo.
echo This script will:
echo 1. Stop all processes on port 8000
echo 2. Start the backend server
echo.
echo Running with administrator privileges...
echo.

PowerShell -NoProfile -ExecutionPolicy Bypass -Command "& {Start-Process PowerShell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0restart_backend.ps1\"' -Verb RunAs}"

echo.
echo Script launched. Check the new PowerShell window.
timeout /t 3
