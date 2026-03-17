Set WshShell = CreateObject("WScript.Shell")
' Check if MT5 is already running
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
Set colProcesses = objWMIService.ExecQuery("SELECT * FROM Win32_Process WHERE Name = 'terminal64.exe'")

If colProcesses.Count = 0 Then
    ' MT5 not running, start it
    WshShell.Run """C:\Program Files\MetaTrader 5\terminal64.exe""", 0, False
End If

Set colProcesses = Nothing
Set objWMIService = Nothing
Set WshShell = Nothing
