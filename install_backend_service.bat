@echo off
REM ========================================
REM Install Backend Service (Auto-start on Boot)
REM ========================================

echo Installing Backend Service...
echo.

REM Create a VBS script to run backend without showing console window
set "BACKEND_VBS=%~dp0start_backend_service.vbs"
set "BACKEND_BAT=%~dp0start_backend.bat"

echo Set WshShell = CreateObject("WScript.Shell") > "%BACKEND_VBS%"
echo WshShell.Run """%BACKEND_BAT%""", 0, False >> "%BACKEND_VBS%"

REM Create scheduled task to run at startup
schtasks /create /tn "HustleBackendService" /tr "%BACKEND_VBS%" /sc onstart /ru "SYSTEM" /rl highest /f

if %errorlevel% equ 0 (
    echo [SUCCESS] Backend service installed successfully
    echo Service will start automatically on system boot
) else (
    echo [ERROR] Failed to install backend service
    echo Please run this script as Administrator
)

echo.
pause
