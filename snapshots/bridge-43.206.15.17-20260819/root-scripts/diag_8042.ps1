$key = "<REDACTED_API_KEY>"

Write-Host "[1] Exness ticks.json freshness"
$f = "D:\MT4LAB\terminals\exness\MQL4\Files\qhbridge\state\ticks.json"
if (Test-Path $f) {
    $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
    Write-Host "age=${age}s  size=$((Get-Item $f).Length)bytes"
    if ($age -lt 30) { "FRESH" } else { "STALE" }
} else { "FILE NOT FOUND: $f" }

Write-Host "[2] IC ticks.json freshness"
$f2 = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\ticks.json"
if (Test-Path $f2) {
    $age2 = [int]((Get-Date) - (Get-Item $f2).LastWriteTime).TotalSeconds
    Write-Host "age=${age2}s  size=$((Get-Item $f2).Length)bytes"
} else { "NOT FOUND: $f2" }

Write-Host "[3] Exness terminal process"
Get-Process | Where-Object { $_.Path -like "*terminals*exness*" } | Select-Object Id,Path,StartTime | Format-Table -AutoSize

Write-Host "[4] Exness qhbridge dir"
$dir = "D:\MT4LAB\terminals\exness\MQL4\Files\qhbridge"
if (Test-Path $dir) {
    Get-ChildItem $dir -Recurse | Select-Object FullName,LastWriteTime,Length | Format-Table -AutoSize
} else { "NOT FOUND: $dir" }

Write-Host "[5] Try force reconnect via 8042 API"
try {
    Invoke-RestMethod "http://127.0.0.1:8042/mt5/connection/reconnect" -Method POST -Headers @{"x-api-key"=$key} -TimeoutSec 10 | ConvertTo-Json -Compress
    Start-Sleep -Seconds 5
    Invoke-RestMethod "http://127.0.0.1:8042/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10 | ConvertTo-Json -Compress
} catch { "FAIL: $_" }
