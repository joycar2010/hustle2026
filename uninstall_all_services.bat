@echo off
REM ========================================
REM Uninstall All Services
REM ========================================

echo ========================================
echo Uninstalling Hustle Services
echo ========================================
echo.
echo This will remove:
echo   1. Backend Service
echo   2. Frontend Service
echo.
pause

echo.
echo Stopping services first...
call "%~dp0stop_all_services.bat"

echo.
echo [1/2] Uninstalling Backend Service...
schtasks /delete /tn "HustleBackendService" /f
if %errorlevel% equ 0 (
    echo [OK] Backend service uninstalled
) else (
    echo [INFO] Backend service was not installed
)

echo.
echo [2/2] Uninstalling Frontend Service...
schtasks /delete /tn "HustleFrontendService" /f
if %errorlevel% equ 0 (
    echo [OK] Frontend service uninstalled
) else (
    echo [INFO] Frontend service was not installed
)

REM Clean up VBS files
echo.
echo Cleaning up service files...
del "%~dp0start_backend_service.vbs" 2>nul
del "%~dp0start_frontend_service.vbs" 2>nul

echo.
echo ========================================
echo Uninstallation Complete
echo ========================================
echo.
pause
