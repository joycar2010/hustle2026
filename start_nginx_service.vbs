Set WshShell = CreateObject("WScript.Shell")
' Check if Nginx is already running
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
Set colProcesses = objWMIService.ExecQuery("SELECT * FROM Win32_Process WHERE Name = 'nginx.exe'")

If colProcesses.Count = 0 Then
    ' Nginx not running, start it
    WshShell.Run "cmd /c cd /d C:\nginx && start nginx.exe", 0, False
End If

Set colProcesses = Nothing
Set objWMIService = Nothing
Set WshShell = Nothing
