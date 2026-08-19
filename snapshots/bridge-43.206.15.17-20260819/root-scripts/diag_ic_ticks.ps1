$key = "<REDACTED_API_KEY>"

Write-Host "=== IC ticks.json ==="
$f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\ticks.json"
if (Test-Path $f) {
    $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
    Write-Host "age=${age}s  size=$((Get-Item $f).Length)bytes"
    if ($age -lt 10) { "FRESH - EA is writing OK" } else { "STALE $age s - EA not writing" }
} else { "NOT FOUND: $f" }

Write-Host "`n=== IC terminal 443 connections ==="
$term = Get-Process | Where-Object { $_.Path -like "*terminals*ic*terminal*" } | Select-Object -First 1
if ($term) {
    Write-Host "PID=$($term.Id)  started=$($term.StartTime)"
    Get-NetTCPConnection -RemotePort 443 -State Established -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq $term.Id | Select-Object RemoteAddress,RemotePort,LocalPort | Format-Table -AutoSize
} else { "IC terminal NOT running" }

Write-Host "`n=== 8041 agent env: CMD_WAIT_SEC ==="
$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "PID=$p41"
# read env via tasklist /v or check process module
$envFile = [System.IO.Path]::Combine($env:TEMP, "env_check.txt")
# Alternative: read from process environment using kernel32
# Simpler: just print the run_agent.ps1 current settings
$content = Get-Content D:\MT4LAB\agent\run_agent.ps1 -Raw
if ($content -match 'wait\s*=\s*(\d+)') { "IC wait value in script: $($Matches[1])" }

Write-Host "`n=== reconnect 8041 ==="
Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/reconnect" -Method POST -Headers @{"x-api-key"=$key} -TimeoutSec 10 | ConvertTo-Json -Compress
Start-Sleep -Seconds 5
Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10 | ConvertTo-Json -Compress
