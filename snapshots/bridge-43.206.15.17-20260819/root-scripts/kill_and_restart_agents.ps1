$ErrorActionPreference = "Continue"
Write-Host "=== [1] kill 7784/6020 (旧 C:\Python311 agent) ==="
taskkill /F /PID 7784 /PID 6020 2>&1
Start-Sleep -Seconds 3

Write-Host "`n=== [2] 确认端口已释放 ==="
$l41 = Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue
$l42 = Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue
if ($l41) { "8041 仍被 PID=$($l41.OwningProcess) 占用" } else { "8041 已释放" }
if ($l42) { "8042 仍被 PID=$($l42.OwningProcess) 占用" } else { "8042 已释放" }

Write-Host "`n=== [3] 用 run_agent.ps1 -Portable 启动(CMD_WAIT_SEC=30/20) ==="
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance exness -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 15

Write-Host "`n=== [4] 新进程确认 ==="
$new41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$new42 = (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
"8041 PID=$new41"
"8042 PID=$new42"
if ($new41) { (Get-CimInstance Win32_Process -Filter "ProcessId=$new41").CommandLine }
if ($new42) { (Get-CimInstance Win32_Process -Filter "ProcessId=$new42").CommandLine }

Write-Host "`n=== [5] health check ==="
Start-Sleep -Seconds 5
try { $h41 = Invoke-RestMethod -Uri "http://127.0.0.1:8041/health" -TimeoutSec 8; "8041: " + ($h41 | ConvertTo-Json -Compress) } catch { "8041 FAIL: $_" }
try { $h42 = Invoke-RestMethod -Uri "http://127.0.0.1:8042/health" -TimeoutSec 8; "8042: " + ($h42 | ConvertTo-Json -Compress) } catch { "8042 FAIL: $_" }

Write-Host "`n=== [6] connection/status (验证 MT4 terminal 连接) ==="
$key = "<REDACTED_API_KEY>"
try { $s = Invoke-RestMethod -Uri "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 8; "8041: " + ($s | ConvertTo-Json -Compress) } catch { "8041 conn FAIL" }
try { $s = Invoke-RestMethod -Uri "http://127.0.0.1:8042/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 8; "8042: " + ($s | ConvertTo-Json -Compress) } catch { "8042 conn FAIL" }
