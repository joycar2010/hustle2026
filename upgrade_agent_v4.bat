@echo off
REM MT5 Agent V4 Upgrade Script
REM Run this on MT5 server to upgrade to V4

echo ========================================
echo MT5 Agent V4 Upgrade
echo ========================================
echo.

cd C:\MT5Agent

echo [1/5] Stopping current Agent...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq main.py*" 2>nul
timeout /t 2 >nul
echo   Done
echo.

echo [2/5] Backing up current version...
set timestamp=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set timestamp=%timestamp: =0%
copy /Y main.py main.py.backup_%timestamp%
echo   Backed up to main.py.backup_%timestamp%
echo.

echo [3/5] Upgrading to V4...
copy /Y main_v4.py main.py
echo   main_v4.py copied to main.py
echo.

echo [4/5] Starting Agent...
start /B python main.py
timeout /t 3 >nul
echo   Agent started
echo.

echo [5/5] Verifying service...
timeout /t 2 >nul
curl http://localhost:9000/ 2>nul
if %errorLevel% equ 0 (
    echo.
    echo   Agent is running normally
) else (
    echo.
    echo   Warning: Health check failed
)
echo.

echo ========================================
echo Upgrade Complete!
echo ========================================
echo.
echo V4 New Features:
echo   - Complete MT5 client stop functionality
echo   - Precise stop in multi-process environment
echo   - Better error handling and logging
echo.
echo Backup: main.py.backup_%timestamp%
echo.
pause
