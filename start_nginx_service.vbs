Set WshShell = CreateObject("WScript.Shell")

' Use PowerShell to start nginx with proper permissions
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\app\hustle2026\start_nginx.ps1", 0, False

Set WshShell = Nothing
