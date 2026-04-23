@echo off
REM Bridge Services Auto-Start Script
REM Runs on Administrator login to start all MT5 Bridge services in user session
REM Wait 15 seconds for MT5 terminals to fully start first
ping 127.0.0.1 -n 16 > nul

REM Start each bridge if not already listening
for %%S in (hustle-mt5-mt5-icsys hustle-mt5-mt5-bysys hustle-mt5-mt5-by01 hustle-mt5-mt5-by02 hustle-mt5-mt5-ic01) do (
    call :start_bridge %%S
)
exit /b

:start_bridge
set SVC=%1
set LOG=D:\%SVC%\logs\startup.log
echo %DATE% %TIME% Starting %SVC%... >> %LOG%

REM Get port from .env
for /f "tokens=2 delims==" %%P in ('findstr "SERVICE_PORT" D:\%SVC%\.env') do set PORT=%%P

REM Check if already listening on port
netstat -an | findstr ":%PORT% " | findstr "LISTENING" > nul
if %ERRORLEVEL% EQU 0 (
    echo %DATE% %TIME% %SVC% already running on port %PORT% >> %LOG%
    goto :eof
)

REM Start uvicorn bridge
start /b "" "D:\%SVC%\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port %PORT% >> %LOG% 2>&1
echo %DATE% %TIME% %SVC% started on port %PORT% >> %LOG%
goto :eof
