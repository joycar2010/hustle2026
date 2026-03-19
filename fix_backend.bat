@echo off
chcp 437 >nul
title Hustle2026 Backend Fix

echo.
echo ========================================
echo   Hustle2026 Backend Fix Tool
echo ========================================
echo.

echo [1/3] Checking port 8000...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
        echo     Found process PID: %%a - killing...
        taskkill /PID %%a /F >nul 2>&1
    )
) else (
    echo     Port 8000 is free.
)
taskkill /FI "WINDOWTITLE eq Hustle2026-Backend" /F >nul 2>&1
timeout /t 3 /nobreak >nul

echo [2/3] Starting backend...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo     WARNING: Port 8000 still in use!
    goto :check
)
start "Hustle2026-Backend" C:\app\hustle2026\backend_runner.bat
echo     Backend started, waiting 8s...
timeout /t 8 /nobreak >nul

:check
echo [3/3] Verifying...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo     OK - Backend port 8000 is listening!
) else (
    echo     FAIL - Port 8000 not listening. Check: C:\app\hustle2026\backend\backend_live.log
)

echo.
echo Press any key to close...
pause >nul
