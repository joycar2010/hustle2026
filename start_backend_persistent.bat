@echo off
cd /d C:\app\hustle2026\backend

:RESTART
echo [%date% %time%] Starting backend server...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

echo [%date% %time%] Backend crashed. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto RESTART
