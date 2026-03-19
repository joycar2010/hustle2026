@echo off
chcp 65001 >nul
title Hustle2026 Services

echo ========================================
echo Starting Hustle2026 Services
echo ========================================
echo.

REM Change to project directory
cd /d C:\app\hustle2026

REM Check and Start Nginx
echo [1/4] Checking Nginx Service...
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Nginx is already running, skipping...
) else (
    echo Starting Nginx Service...
    cd /d C:\nginx
    start "" nginx.exe -c C:\nginx\conf\nginx.conf
    cd /d C:\app\hustle2026
    timeout /t 2 /nobreak >nul
)

REM Check and Start MetaTrader 5 Client
echo [2/4] Checking MetaTrader 5 Client...
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I /N "terminal64.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo MetaTrader 5 is already running, skipping...
) else (
    echo Starting MetaTrader 5 Client...
    start "MetaTrader 5" "C:\Program Files\MetaTrader 5\terminal64.exe"
    echo Waiting for MT5 to initialize...
    timeout /t 10 /nobreak >nul
)

REM Start Backend Service - kill stale processes first
echo [3/4] Checking Backend Service...
REM Kill any stale uvicorn/python processes holding port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Killing stale process on port 8000 (PID: %%a)...
    taskkill /PID %%a /F >nul 2>&1
)
REM Also kill any orphaned uvicorn processes
taskkill /FI "WINDOWTITLE eq Hustle2026-Backend" /F >nul 2>&1
timeout /t 2 /nobreak >nul

REM Now check if port is truly free
netstat -ano | findstr ":8000" | findstr "LISTENING" >NUL
if "%ERRORLEVEL%"=="0" (
    echo WARNING: Port 8000 still in use, backend may already be running...
) else (
    echo Starting Backend Service...
    start "Hustle2026-Backend" /D "C:\app\hustle2026\backend" cmd /k "C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> backend_live.log 2>&1"
    timeout /t 5 /nobreak >nul
)

REM Start Frontend Service
echo [4/4] Checking Frontend Service...
netstat -ano | findstr ":3000" | findstr "LISTENING" >NUL
if "%ERRORLEVEL%"=="0" (
    echo Frontend service is already running on port 3000, skipping...
) else (
    echo Starting Frontend Service...
    start "Hustle2026-Frontend" /D "C:\app\hustle2026\frontend" cmd /k "npm run dev"
    timeout /t 2 /nobreak >nul
)

echo.
echo ========================================
echo All Services Started Successfully!
echo ========================================
echo Nginx: https://app.hustle2026.xyz
echo MetaTrader 5: Running
echo Backend: http://172.31.5.62:8000
echo Frontend: http://172.31.5.62:3000
echo.
echo Press any key to close this window...
pause >nul
