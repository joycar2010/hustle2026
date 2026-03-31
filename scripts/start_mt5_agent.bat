@echo off
REM MT5 Windows Agent Launcher
REM Double-click this file in RDP session to start Windows Agent

echo ========================================
echo MT5 Windows Agent Launcher
echo ========================================
echo.

REM Stop existing Windows Agent processes
echo Stopping existing Windows Agent processes...
for /f "tokens=2" %%i in ('tasklist ^| findstr python.exe') do (
    wmic process where "ProcessId=%%i" get CommandLine 2^>nul | findstr "main_v2.py" >nul
    if not errorlevel 1 (
        echo Stopping PID: %%i
        taskkill /F /PID %%i >nul 2>&1
    )
)

timeout /t 2 /nobreak >nul

REM Start Windows Agent
echo.
echo Starting Windows Agent in user session...
cd /d C:\MT5Agent
start "MT5 Windows Agent" /MIN python main_v2.py

timeout /t 3 /nobreak >nul

REM Verify service status
echo.
echo Verifying service status...
curl -s http://localhost:9000/ 2>nul | findstr "healthy" >nul
if errorlevel 1 (
    echo [ERROR] Windows Agent may not have started properly
    echo Please check the MT5 Windows Agent window for errors
) else (
    echo [SUCCESS] Windows Agent started successfully
    echo.
    echo You can now use the admin panel to start MT5 instances
    echo MT5 windows will appear in this RDP session
)

echo.
echo ========================================
echo Press any key to exit...
pause >nul
