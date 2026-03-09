@echo off
REM ========================================
REM Stop All Services
REM ========================================

echo Stopping all services...
echo.

echo [1/2] Stopping Frontend Service...
taskkill /F /FI "WINDOWTITLE eq Hustle XAU Frontend*" 2>nul
if %errorlevel% equ 0 (
    echo [OK] Frontend service stopped
) else (
    echo [INFO] Frontend service was not running
)

echo.
echo [2/2] Stopping Backend Service...
taskkill /F /FI "WINDOWTITLE eq Hustle XAU Backend*" 2>nul
if %errorlevel% equ 0 (
    echo [OK] Backend service stopped
) else (
    echo [INFO] Backend service was not running
)

REM Also kill any Python processes on port 8000
echo.
echo Checking for processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo Killing process %%a
    taskkill /F /PID %%a 2>nul
)

REM Kill any Node processes on port 3000
echo.
echo Checking for processes on port 3000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000 ^| findstr LISTENING') do (
    echo Killing process %%a
    taskkill /F /PID %%a 2>nul
)

echo.
echo ========================================
echo Services Stopped
echo ========================================
echo.
pause
