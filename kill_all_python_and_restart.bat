@echo off
echo ========================================
echo Force Kill All Python Processes
echo ========================================

echo Killing all Python processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM pythonw.exe /T 2>nul

timeout /t 3 /nobreak >nul

echo.
echo Checking port 8000...
netstat -ano | findstr ":8000.*LISTENING"

echo.
echo Starting backend server...
cd /d C:\app\hustle2026\backend
start "Backend Server" python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

echo.
echo Backend server is starting in a new window...
echo Please wait 5-10 seconds for the server to initialize.
pause
