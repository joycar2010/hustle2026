Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d C:\app\hustle2026\frontend && npm run dev > frontend_dev.log 2>&1", 0, False
Set WshShell = Nothing
