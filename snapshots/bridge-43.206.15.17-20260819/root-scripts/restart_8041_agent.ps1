Write-Host "=== 8041 agent进程状态 ==="
$conn = Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
Write-Host "8041 PID: $($conn.OwningProcess)"

Write-Host "=== MT4LAB任务状态 ==="
Get-ScheduledTask | Where-Object {$_.TaskName -like "MT4LAB*"} | Select-Object TaskName,State | Format-Table -AutoSize

Write-Host "=== IC terminal进程(portable) ==="
Get-Process | Where-Object {$_.Path -like "*MT4LAB*terminal*ic*"} | Select-Object Id,Path,StartTime

Write-Host "=== 重启MT4LAB-Agent-ic ==="
Start-ScheduledTask -TaskName "MT4LAB-Agent-ic" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 12

Write-Host "=== 8041 listener after restart ==="
Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Format-Table -AutoSize

Write-Host "=== health check ==="
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8041/health" -TimeoutSec 10
    $h | ConvertTo-Json -Compress
} catch { "FAIL: $_" }

Write-Host "=== connection/status ==="
try {
    $s = Invoke-RestMethod -Uri "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"="<REDACTED_API_KEY>"} -TimeoutSec 10
    $s | ConvertTo-Json -Compress
} catch { "FAIL: $_" }
