D:\MT4LAB\agent\venv\Scripts\python.exe D:\patch_stale_sec.py
D:\MT4LAB\agent\venv\Scripts\python.exe -m py_compile D:\MT4LAB\agent\filebridge.py
if ($?) { Write-Host "SYNTAX-OK" } else { Write-Host "SYNTAX-FAIL" }

Write-Host "`n=== kill old 8041 agent ==="
$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($p41) { taskkill /F /PID $p41 2>&1 }
Start-Sleep -Seconds 3

Write-Host "`n=== restart 8041 via run_agent.ps1 -Portable ==="
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 12

$new41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "New 8041 PID=$new41"
(Get-CimInstance Win32_Process -Filter "ProcessId=$new41").CommandLine

Write-Host "`n=== 8041 health ==="
Start-Sleep -Seconds 3
try { Invoke-RestMethod "http://127.0.0.1:8041/health" -TimeoutSec 8 | ConvertTo-Json -Compress } catch { "FAIL" }

Write-Host "`n=== 8041 connection/status ==="
$key = "<REDACTED_API_KEY>"
try { Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 8 | ConvertTo-Json -Compress } catch { "FAIL" }
