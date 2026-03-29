@echo off
chcp 437 >nul
title Hustle2026 Services
cd /d C:\app\hustle2026

echo ========================================
echo   Hustle2026 Services Startup
echo ========================================
echo.

echo [1/3] Nginx...
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I "nginx.exe" >NUL
if %ERRORLEVEL%==0 (
    echo     Already running.
) else (
    echo     Starting Nginx...
    cd /d C:\nginx
    start "" nginx.exe
    cd /d C:\app\hustle2026
    timeout /t 2 /nobreak >nul
    echo     Done.
)

echo [2/3] MetaTrader 5...
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if %ERRORLEVEL%==0 (
    echo     Already running.
) else (
    echo     Starting MT5...
    start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
    timeout /t 10 /nobreak >nul
    echo     Done.
)

echo [3/3] Backend (port 8000)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo     Killing stale PID %%a...
    taskkill /PID %%a /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq Hustle2026-Backend" /F >nul 2>&1
timeout /t 2 /nobreak >nul

netstat -ano | findstr ":8000" | findstr "LISTENING" >NUL
if %ERRORLEVEL%==0 (
    echo     WARNING: Port 8000 still in use!
) else (
    echo     Starting backend...
    start "Hustle2026-Backend" C:\app\hustle2026\backend_runner.bat
    timeout /t 8 /nobreak >nul
    echo     Done.
)

echo.
echo ========================================
echo   All services started.
echo   Nginx  : https://app.hustle2026.xyz
echo   Backend: http://172.31.5.62:8000
echo ========================================
echo.
echo Press any key to close...
pause >nul
