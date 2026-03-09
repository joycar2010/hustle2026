@echo off
REM ========================================
REM Install Frontend Service (Auto-start on Boot)
REM ========================================

echo Installing Frontend Service...
echo.

REM Create a VBS script to run frontend without showing console window
set "FRONTEND_VBS=%~dp0start_frontend_service.vbs"
set "FRONTEND_BAT=%~dp0start_frontend.bat"

echo Set WshShell = CreateObject("WScript.Shell") > "%FRONTEND_VBS%"
echo WshShell.Run """%FRONTEND_BAT%""", 0, False >> "%FRONTEND_VBS%"

REM Create scheduled task to run at startup (with 30 second delay to ensure backend starts first)
schtasks /create /tn "HustleFrontendService" /tr "%FRONTEND_VBS%" /sc onstart /ru "SYSTEM" /rl highest /delay 0000:30 /f

if %errorlevel% equ 0 (
    echo [SUCCESS] Frontend service installed successfully
    echo Service will start automatically on system boot (30 seconds after backend)
) else (
    echo [ERROR] Failed to install frontend service
    echo Please run this script as Administrator
)

echo.
pause
