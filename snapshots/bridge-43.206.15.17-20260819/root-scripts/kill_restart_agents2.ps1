$ErrorActionPreference = "Continue"
Write-Host "[1] kill old agents 7784 6020"
taskkill /F /PID 7784 /PID 6020 2>&1
Start-Sleep -Seconds 3

Write-Host "[2] check ports freed"
$l41 = Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue
$l42 = Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue
if ($l41) { Write-Host "8041 still taken PID=$($l41.OwningProcess)" } else { Write-Host "8041 free OK" }
if ($l42) { Write-Host "8042 still taken PID=$($l42.OwningProcess)" } else { Write-Host "8042 free OK" }

Write-Host "[3] start agents via run_agent.ps1 -Portable (CMD_WAIT_SEC IC=30 Exness=20)"
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance exness -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 15

Write-Host "[4] verify new processes"
$new41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$new42 = (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "8041 PID=$new41"
Write-Host "8042 PID=$new42"
if ($new41) { (Get-CimInstance Win32_Process -Filter "ProcessId=$new41").CommandLine }
if ($new42) { (Get-CimInstance Win32_Process -Filter "ProcessId=$new42").CommandLine }

Write-Host "[5] health"
Start-Sleep -Seconds 5
try { $h = Invoke-RestMethod "http://127.0.0.1:8041/health" -TimeoutSec 8; Write-Host "8041:"; $h | ConvertTo-Json -Compress } catch { Write-Host "8041 health FAIL" }
try { $h = Invoke-RestMethod "http://127.0.0.1:8042/health" -TimeoutSec 8; Write-Host "8042:"; $h | ConvertTo-Json -Compress } catch { Write-Host "8042 health FAIL" }

Write-Host "[6] connection/status"
$key = "<REDACTED_API_KEY>"
try { $s = Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10; Write-Host "8041:"; $s | ConvertTo-Json -Compress } catch { Write-Host "8041 conn FAIL" }
try { $s = Invoke-RestMethod "http://127.0.0.1:8042/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10; Write-Host "8042:"; $s | ConvertTo-Json -Compress } catch { Write-Host "8042 conn FAIL" }
