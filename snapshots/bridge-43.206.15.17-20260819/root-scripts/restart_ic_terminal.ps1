$key = "<REDACTED_API_KEY>"

Write-Host "[1] kill IC terminal PID 5496 (portable ic)"
Stop-Process -Id 5496 -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

Write-Host "[2] restart IC terminal via MT4LAB-Startup"
Start-ScheduledTask -TaskName "MT4LAB-Startup" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 20

Write-Host "[3] check IC terminal"
Get-Process | Where-Object { $_.Path -like "*terminals*ic*terminal*" } | Select-Object Id,Path,StartTime | Format-Table -AutoSize

Write-Host "[4] check IC meta.json freshness"
$f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
if (Test-Path $f) {
    $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
    Write-Host "meta.json age=${age}s"
    Get-Content $f -Raw
}

Write-Host "[5] 8041 connection/status"
try {
    Start-Sleep -Seconds 5
    $s = Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10
    $s | ConvertTo-Json -Compress
} catch { "FAIL: $_" }
