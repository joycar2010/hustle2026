$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($p41) { taskkill /F /PID $p41 2>&1; Start-Sleep -Seconds 3 }
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 14
$new41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "new 8041 PID=$new41"
$key = "<REDACTED_API_KEY>"
try {
    $s = Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10
    Write-Host "conn=$($s.connected) healthy=$($s.healthy)"
} catch { Write-Host "status fail" }

Write-Host "=== STALE constants in filebridge.py ==="
Select-String -Path D:\MT4LAB\agent\filebridge.py -Pattern "STALE_" | Select-Object -First 10 | ForEach-Object { $_.Line }

Write-Host "=== meta.json freshness ==="
$f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
if (Test-Path $f) {
    $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
    $ageStr = $age.ToString() + "s"
    Write-Host "meta.json age=$ageStr"
    Get-Content $f -Raw
} else { Write-Host "meta.json NOT FOUND" }

Write-Host "=== QHBridge.mq4 presence ==="
$mq4 = "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.mq4"
if (Test-Path $mq4) {
    $sz = (Get-Item $mq4).Length
    Write-Host "Found QHBridge.mq4 size=$sz bytes"
    $lines = Get-Content $mq4
    $cnt = $lines.Count
    Write-Host "Lines: $cnt"
    Write-Host "--- meta-writing logic ---"
    $lines | Select-String -Pattern "meta|WriteFile|AccountLogin|AccountNumber|OnTimer" | Select-Object -First 20 | ForEach-Object { $_.Line }
} else { Write-Host "QHBridge.mq4 not found at $mq4" }
