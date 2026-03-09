@echo off
REM ========================================
REM Start All Services
REM ========================================

echo Starting all services...
echo.

echo [1/2] Starting Backend Service...
schtasks /run /tn "HustleBackendService"
if %errorlevel% equ 0 (
    echo [OK] Backend service started
) else (
    echo [ERROR] Failed to start backend service
)

echo.
echo Waiting 5 seconds for backend to initialize...
timeout /t 5 /nobreak >nul

echo.
echo [2/2] Starting Frontend Service...
schtasks /run /tn "HustleFrontendService"
if %errorlevel% equ 0 (
    echo [OK] Frontend service started
) else (
    echo [ERROR] Failed to start frontend service
)

echo.
echo ========================================
echo Services Started
echo ========================================
echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo API Docs: http://localhost:8000/docs
echo.
echo To check service status: schtasks /query /tn "HustleBackendService"
echo.
pause
