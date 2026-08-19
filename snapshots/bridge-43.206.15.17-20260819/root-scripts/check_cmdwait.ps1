Write-Host "=== run_agent.ps1 CMD_WAIT_SEC ==="
Get-Content D:\MT4LAB\agent\run_agent.ps1 | Select-String -Pattern "CMD_WAIT" | ForEach-Object { $_.Line }

Write-Host "=== active processes env: CMD_WAIT_SEC ==="
$pids = (Get-NetTCPConnection -LocalPort 8041,8042 -State Listen -ErrorAction SilentlyContinue).OwningProcess
foreach ($p in $pids) {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$p").CommandLine
    Write-Host "PID=$p: $cmd"
}

# Read env from running agent processes
Write-Host "=== 8041 agent cmdwait env ==="
Get-Process python -ErrorAction SilentlyContinue | Where-Object { (Get-NetTCPConnection -OwningProcess $_.Id -State Listen -ErrorAction SilentlyContinue | Where-Object LocalPort -eq 8041) } | ForEach-Object {
    Write-Host "PID=$($_.Id)"
}
