Set WshShell = CreateObject("WScript.Shell")

' Use PowerShell script to kill existing process and start backend
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\app\hustle2026\start_backend.ps1", 0, False

Set WshShell = Nothing
