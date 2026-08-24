Get-Date
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in @(8041,8042,8061,8063,8065,8066,8067,8068) } | Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process python,terminal64,terminal -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime