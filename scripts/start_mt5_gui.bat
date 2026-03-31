@echo off
REM MT5 GUI Launcher - Start MT5 clients with GUI in RDP session
REM This script must be run in RDP session, not via SSH

echo ========================================
echo MT5 GUI Launcher
echo ========================================
echo.

REM Check if running in RDP session
query session | findstr "Active" | findstr "rdp-tcp" >nul
if errorlevel 1 (
    echo [ERROR] This script must be run in an RDP session!
    echo Please connect via RDP and run this script again.
    pause
    exit /b 1
)

echo [INFO] Running in RDP session - OK
echo.

REM ========================================
REM Step 1: Start MT5-01 Instance
REM ========================================
echo Step 1: Starting MT5-01 Instance...
set MT5_01_PATH=D:\MetaTrader 5-01\terminal64.exe
set MT5_01_DIR=D:\MetaTrader 5-01

if not exist "%MT5_01_PATH%" (
    echo [WARNING] MT5-01 not found: %MT5_01_PATH%
    echo Skipping MT5-01...
) else (
    REM Check if already running
    tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
    if not errorlevel 1 (
        echo [INFO] MT5 client already running
    ) else (
        echo [INFO] Starting MT5-01 client...
        cd /d "%MT5_01_DIR%"
        start "" "%MT5_01_PATH%" /portable
        timeout /t 3 /nobreak >nul
        echo [SUCCESS] MT5-01 started
    )
)

echo.

REM ========================================
REM Step 2: Start MT5 System Service Instance
REM ========================================
echo Step 2: Starting MT5 System Service Instance...
set MT5_SYS_PATH=D:\MetaTrader 5\terminal64.exe
set MT5_SYS_DIR=D:\MetaTrader 5

if not exist "%MT5_SYS_PATH%" (
    echo [WARNING] MT5 System Service not found: %MT5_SYS_PATH%
    echo Skipping MT5 System Service...
) else (
    REM Check if already running (by path)
    echo [INFO] Starting MT5 System Service client...
    cd /d "%MT5_SYS_DIR%"
    start "" "%MT5_SYS_PATH%" /portable
    timeout /t 3 /nobreak >nul
    echo [SUCCESS] MT5 System Service started
)

echo.

REM ========================================
REM Step 3: Verify MT5 Processes
REM ========================================
echo Step 3: Verifying MT5 processes...
powershell -Command "Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize"

echo.
echo ========================================
echo MT5 GUI Launcher Complete
echo ========================================
echo.
echo MT5 clients are now running in this RDP session.
echo You can now use the admin panel to start/stop MT5 Bridge services.
echo.
echo IMPORTANT: Keep this RDP session active!
echo If you disconnect, MT5 windows will remain running.
echo.
pause
