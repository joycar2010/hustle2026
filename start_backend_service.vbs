Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d C:\app\hustle2026\backend && C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend_live.log 2>&1", 0, False
Set WshShell = Nothing
