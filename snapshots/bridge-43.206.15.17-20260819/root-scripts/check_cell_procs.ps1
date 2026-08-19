Write-Host "=== 8061/8063 bridge processes ==="
Get-Process -Id 5244,5928,6556 -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime | Format-Table -AutoSize

Write-Host "=== listeners 8061/8063 ==="
netstat -ano | findstr LISTENING | findstr "8061 8063"

Write-Host "=== cell.py watchdog process ==="
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like "*cell.py*" } | Select-Object ProcessId,CommandLine | Format-List

Write-Host "=== restart 8063 bridge (PID from listener) ==="
$conn8063 = Get-NetTCPConnection -LocalPort 8063 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$conn8061 = Get-NetTCPConnection -LocalPort 8061 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
Write-Host "8063 PID: $($conn8063.OwningProcess)  8061 PID: $($conn8061.OwningProcess)"
