@echo off
chcp 65001 >nul
title Hustle2026 Services

echo ========================================
echo Starting Hustle2026 Services
echo ========================================
echo.

REM Change to project directory
cd /d C:\app\hustle2026

REM Check and Start MetaTrader 5 Client
echo [1/3] Checking MetaTrader 5 Client...
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I /N "terminal64.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo MetaTrader 5 is already running, skipping...
) else (
    echo Starting MetaTrader 5 Client...
    start "MetaTrader 5" "C:\Program Files\MetaTrader 5\terminal64.exe"
    echo Waiting for MT5 to initialize...
    timeout /t 10 /nobreak >nul
)

REM Start Backend Service
echo [2/3] Checking Backend Service...
netstat -ano | findstr ":8000" >NUL
if "%ERRORLEVEL%"=="0" (
    echo Backend service is already running on port 8000, skipping...
) else (
    echo Starting Backend Service...
    start "Hustle2026-Backend" /D "C:\app\hustle2026\backend" cmd /k "C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    timeout /t 5 /nobreak >nul
)

REM Start Frontend Service
echo [3/3] Checking Frontend Service...
netstat -ano | findstr ":5173" >NUL
if "%ERRORLEVEL%"=="0" (
    echo Frontend service is already running on port 5173, skipping...
) else (
    echo Starting Frontend Service...
    start "Hustle2026-Frontend" /D "C:\app\hustle2026\frontend" cmd /k "npm run dev"
    timeout /t 2 /nobreak >nul
)

echo.
echo ========================================
echo All Services Started Successfully!
echo ========================================
echo MetaTrader 5: Running
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo Press any key to close this window...
pause >nul
