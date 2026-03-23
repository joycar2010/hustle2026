@echo off
cd /d C:\app\hustle2026\backend

:: ===== Log Rotation: rotate backend_live.log when > 50MB (52428800 bytes) =====
if exist backend_live.log (
    for %%A in (backend_live.log) do (
        if %%~zA GTR 52428800 (
            echo [%date% %time%] Log rotation triggered >> backend_live.log
            if exist backend_live.log.5 del /f /q backend_live.log.5
            if exist backend_live.log.4 ren backend_live.log.4 backend_live.log.5
            if exist backend_live.log.3 ren backend_live.log.3 backend_live.log.4
            if exist backend_live.log.2 ren backend_live.log.2 backend_live.log.3
            if exist backend_live.log.1 ren backend_live.log.1 backend_live.log.2
            ren backend_live.log backend_live.log.1
        )
    )
)

:: ===== Start uvicorn backend =====
echo [%date% %time%] Backend starting (PID will be logged by uvicorn) >> backend_live.log
C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> backend_live.log 2>&1
echo [%date% %time%] Backend process exited with code %errorlevel% >> backend_live.log
