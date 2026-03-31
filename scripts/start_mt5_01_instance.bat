@echo off
REM Start MT5-01 Instance (Account: 2325036, Port: 8002)
REM This script starts the MT5 client for MT5-01 instance

echo ========================================
echo Starting MT5-01 Instance
echo Account: 2325036
echo Port: 8002
echo ========================================
echo.

REM MT5-01 Instance Path
set MT5_PATH=D:\MetaTrader 5-01\terminal64.exe
set MT5_DIR=D:\MetaTrader 5-01

REM Check if MT5 executable exists
if not exist "%MT5_PATH%" (
    echo [ERROR] MT5 executable not found: %MT5_PATH%
    echo Please check the path and try again.
    pause
    exit /b 1
)

REM Check if already running
echo Checking if MT5 is already running...
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if not errorlevel 1 (
    echo [INFO] MT5 client is already running
    echo.
    echo Verifying process details...
    powershell -Command "Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize"
    echo.
    echo If the MT5 window is not visible, the process may be running in Session 0.
    echo To fix this, stop all MT5 processes and run this script again in RDP session.
    pause
    exit /b 0
)

REM Start MT5 client
echo Starting MT5 client...
cd /d "%MT5_DIR%"
start "" "%MT5_PATH%" /portable

REM Wait for startup
timeout /t 3 /nobreak >nul

REM Verify startup
echo.
echo Verifying MT5 startup...
powershell -Command "Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize"

echo.
echo ========================================
echo MT5-01 Instance Started
echo ========================================
echo.
echo Next steps:
echo 1. Verify MT5 window is visible in RDP session
echo 2. Check MT5 is logged in (Account: 2325036)
echo 3. Go to https://admin.hustle2026.xyz/users
echo 4. Click "Start" button for MT5-01 instance
echo 5. The Bridge service will connect to this MT5 client
echo.
pause
