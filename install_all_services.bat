@echo off
REM ========================================
REM Install All Services (Backend + Frontend)
REM ========================================

echo ========================================
echo Installing Hustle Services
echo ========================================
echo.
echo This will install:
echo   1. Backend Service (Port 8000)
echo   2. Frontend Service (Port 3000)
echo.
echo Both services will start automatically on system boot.
echo.
pause

echo.
echo [1/2] Installing Backend Service...
call "%~dp0install_backend_service.bat"

echo.
echo [2/2] Installing Frontend Service...
call "%~dp0install_frontend_service.bat"

echo.
echo ========================================
echo Installation Complete
echo ========================================
echo.
echo Services installed:
echo   - HustleBackendService
echo   - HustleFrontendService
echo.
echo To start services now, run: start_all_services.bat
echo To stop services, run: stop_all_services.bat
echo To uninstall services, run: uninstall_all_services.bat
echo.
pause
