$key = "<REDACTED_API_KEY>"

Write-Host "[1] kill 8041 agent"
$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($p41) { taskkill /F /PID $p41 2>&1; Start-Sleep -Seconds 3 }

Write-Host "[2] restart 8041 via run_agent.ps1 -Portable"
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 12

$new41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "new PID=$new41"

Write-Host "[3] verify connection/status"
try {
    $s = Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10
    $s | ConvertTo-Json -Compress
} catch { "FAIL: $_" }

Write-Host "[4] verify positions"
try {
    $p = Invoke-RestMethod "http://127.0.0.1:8041/mt5/positions" -Headers @{"x-api-key"=$key} -TimeoutSec 10
    $p | ConvertTo-Json -Compress
} catch { "FAIL: $_" }
