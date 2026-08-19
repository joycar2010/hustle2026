Write-Host "=== kill旧8041 agent(PID 1520) ==="
Stop-Process -Id 1520 -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

Write-Host "=== 触发MT4LAB-Agent-ic重新拉起 ==="
Start-ScheduledTask -TaskName "MT4LAB-Agent-ic" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 15

Write-Host "=== 新listener ==="
Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Format-Table -AutoSize

Write-Host "=== IC terminal 443连接(确认broker在线) ==="
Get-NetTCPConnection -RemotePort 443 -State Established -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq 5496 } | Format-Table -AutoSize

Write-Host "=== ticks.json新鲜度 ==="
$f1 = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\ticks.json"
if (Test-Path $f1) {
    $age = (Get-Date) - (Get-Item $f1).LastWriteTime
    Write-Host "ticks.json age: $([int]$age.TotalSeconds)s  size: $((Get-Item $f1).Length) bytes"
    Get-Content $f1 -Raw | ConvertFrom-Json | Select-Object -First 1 | ConvertTo-Json -Compress
} else { Write-Host "file not found: $f1" }

Write-Host "=== 连接状态 ==="
try {
    $s = Invoke-RestMethod -Uri "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"="<REDACTED_API_KEY>"} -TimeoutSec 10
    $s | ConvertTo-Json -Compress
} catch { "status FAIL: $_" }
