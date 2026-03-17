@echo off
chcp 65001 >nul
title Hustle2026 Services Status Check
color 0A

echo.
echo ========================================
echo   Hustle2026 Services Status Check
echo ========================================
echo.

REM Check PostgreSQL
echo [1/5] PostgreSQL Database Service
sc query postgresql-x64-16 | findstr "RUNNING" >nul
if %ERRORLEVEL%==0 (
    echo     Status: ✓ Running
) else (
    echo     Status: ✗ Not Running
)
echo.

REM Check Nginx
echo [2/5] Nginx Web Server
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if %ERRORLEVEL%==0 (
    echo     Status: ✓ Running
    echo     URL: https://app.hustle2026.xyz
) else (
    echo     Status: ✗ Not Running
)
echo.

REM Check MetaTrader 5
echo [3/5] MetaTrader 5 Client
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I /N "terminal64.exe">NUL
if %ERRORLEVEL%==0 (
    echo     Status: ✓ Running
) else (
    echo     Status: ✗ Not Running
)
echo.

REM Check Backend
echo [4/5] Backend API Service
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo     Status: ✓ Running
    echo     URL: http://localhost:8000
    echo     Health:
    curl -s http://localhost:8000/api/v1/health 2>nul
) else (
    echo     Status: ✗ Not Running
)
echo.

REM Check Frontend
echo [5/5] Frontend Dev Server
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo     Status: ✓ Running
    echo     URL: http://localhost:5173
) else (
    echo     Status: ✗ Not Running
)
echo.

echo ========================================
echo   Scheduled Tasks Status
echo ========================================
echo.
powershell -Command "Get-ScheduledTask | Where-Object {$_.TaskName -like 'Hustle*'} | Select-Object TaskName, State | Format-Table -AutoSize"

echo.
echo ========================================
echo Press any key to exit...
pause >nul
