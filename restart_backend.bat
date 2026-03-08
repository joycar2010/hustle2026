@echo off
echo Stopping backend processes...
taskkill /F /PID 33436 2>nul
taskkill /F /PID 15452 2>nul

echo Waiting for ports to be released...
timeout /t 3 /nobreak >nul

echo Checking if port 8000 is free...
netstat -ano | findstr :8000 | findstr LISTENING
if %errorlevel% equ 0 (
    echo Port 8000 is still in use. Trying to kill all Python processes on port 8000...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
        echo Killing process %%a
        taskkill /F /PID %%a 2>nul
    )
    timeout /t 2 /nobreak >nul
)

echo Starting backend server...
cd /d c:\app\hustle2026\backend
start "Backend Server" cmd /k "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo Backend server is starting...
echo Please wait a few seconds for the server to initialize.
timeout /t 5 /nobreak >nul

echo Done! Backend server should be running now.
pause
