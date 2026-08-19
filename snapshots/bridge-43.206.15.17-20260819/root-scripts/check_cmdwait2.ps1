Write-Host "=== run_agent.ps1 CMD_WAIT lines ==="
Get-Content D:\MT4LAB\agent\run_agent.ps1 | Select-String -Pattern "CMD_WAIT" | ForEach-Object { $_.Line }

Write-Host "=== 8041 listener PID ==="
$p8041 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$p8042 = (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "8041 PID=$p8041  8042 PID=$p8042"

Write-Host "=== cmdline ==="
(Get-CimInstance Win32_Process -Filter "ProcessId=$p8041").CommandLine
(Get-CimInstance Win32_Process -Filter "ProcessId=$p8042").CommandLine
