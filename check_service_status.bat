@echo off
REM ========================================
REM Check Service Status
REM ========================================

echo ========================================
echo Hustle Service Status
echo ========================================
echo.

echo [1] Scheduled Tasks Status:
echo.
schtasks /query /tn "HustleBackendService" /fo LIST | findstr "State:"
schtasks /query /tn "HustleFrontendService" /fo LIST | findstr "State:"

echo.
echo [2] Port Status:
echo.
echo Backend (Port 8000):
netstat -ano | findstr ":8000.*LISTENING"
if %errorlevel% equ 0 (
    echo [OK] Backend is running
) else (
    echo [ERROR] Backend is not running
)

echo.
echo Frontend (Port 3000):
netstat -ano | findstr ":3000.*LISTENING"
if %errorlevel% equ 0 (
    echo [OK] Frontend is running
) else (
    echo [ERROR] Frontend is not running
)

echo.
echo [3] Service URLs:
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:3000
echo API Docs: http://localhost:8000/docs
echo.
echo ========================================
pause
