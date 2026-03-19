@echo off
chcp 437 >nul
title Hustle2026 Services Status
color 0A

echo.
echo ========================================
echo   Hustle2026 Services Status Check
echo ========================================
echo.

echo [1/4] PostgreSQL
sc query postgresql-x64-16 | findstr "RUNNING" >nul
if %ERRORLEVEL%==0 (
    echo     Status: [OK] Running
) else (
    echo     Status: [!!] Not Running
)
echo.

echo [2/4] Nginx
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I "nginx.exe" >NUL
if %ERRORLEVEL%==0 (
    echo     Status: [OK] Running  -  https://app.hustle2026.xyz
) else (
    echo     Status: [!!] Not Running  -  run start_services.bat
)
echo.

echo [3/4] MetaTrader 5
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if %ERRORLEVEL%==0 (
    echo     Status: [OK] Running
) else (
    echo     Status: [!!] Not Running
)
echo.

echo [4/4] Backend API (port 8000)
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo     Status: [OK] Port 8000 listening  -  http://172.31.5.62:8000
) else (
    echo     Status: [!!] Not Running  -  run fix_backend.bat
)
echo.

echo ========================================
echo   Frontend: served by Nginx (static)
echo   Log: C:\app\hustle2026\backend\backend_live.log
echo ========================================
echo.
echo Press any key to exit...
pause >nul
