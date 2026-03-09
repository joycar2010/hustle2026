@echo off
cd /d C:\app\hustle2026\frontend

:RESTART
echo [%date% %time%] Starting frontend server...
npm run dev

echo [%date% %time%] Frontend crashed. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto RESTART
