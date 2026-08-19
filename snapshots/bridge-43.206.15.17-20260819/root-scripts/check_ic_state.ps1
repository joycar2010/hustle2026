Write-Host "=== IC terminal process ==="
$term = Get-Process | Where-Object { $_.Path -like "*terminals*ic*terminal*" } | Select-Object -First 1
if ($term) {
    Write-Host "PID=$($term.Id)  running=$(-not $term.HasExited)  start=$($term.StartTime)"
    Write-Host "=== IC terminal 443 connections ==="
    Get-NetTCPConnection -RemotePort 443 -State Established -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq $term.Id | Format-Table LocalPort,RemoteAddress,State -AutoSize
} else { Write-Host "IC terminal NOT running" }

Write-Host "=== meta.json freshness ==="
$f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
$age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
Write-Host "age=${age}s last_ok=$(((Get-Content $f -Raw | ConvertFrom-Json).last_ok_at))"

Write-Host "=== account.json freshness ==="
$fa = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\account.json"
if (Test-Path $fa) { $age2=[int]((Get-Date)-(Get-Item $fa).LastWriteTime).TotalSeconds; Write-Host "age=${age2}s" }

Write-Host "=== ticks.json freshness ==="
$ft = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\ticks.json"
if (Test-Path $ft) { $age3=[int]((Get-Date)-(Get-Item $ft).LastWriteTime).TotalSeconds; Write-Host "age=${age3}s" }
