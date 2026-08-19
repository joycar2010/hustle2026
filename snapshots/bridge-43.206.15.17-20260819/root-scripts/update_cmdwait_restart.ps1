$ErrorActionPreference = "Continue"

Write-Host "=== [1] 更新 run_agent.ps1 wait值 (IC:12->30, Exness:8->20) ==="
$content = Get-Content D:\MT4LAB\agent\run_agent.ps1 -Raw
$newContent = $content -replace 'port = 8041; wait = 12;', 'port = 8041; wait = 30;'
$newContent = $newContent -replace 'port = 8042; wait = 8;',  'port = 8042; wait = 20;'
$newContent | Set-Content D:\MT4LAB\agent\run_agent.ps1 -NoNewline

# 验证
Get-Content D:\MT4LAB\agent\run_agent.ps1 | Select-String "wait" | ForEach-Object { $_.Line }

Write-Host "`n=== [2] 停止旧的8041/8042进程 ==="
$p8041 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$p8042 = (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($p8041) { Write-Host "Kill 8041 PID=$p8041"; Stop-Process -Id $p8041 -Force -ErrorAction SilentlyContinue }
if ($p8042) { Write-Host "Kill 8042 PID=$p8042"; Stop-Process -Id $p8042 -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

Write-Host "`n=== [3] 用正确 venv 重启两 agent ==="
# IC
$env:API_KEY            = '<REDACTED_API_KEY>'
$env:INSTANCE_NAME      = "qhmt4-ic"
$env:TERMINAL_FILES_DIR = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge"
$env:SERVICE_PORT       = "8041"
$env:CMD_WAIT_SEC       = "30"
Start-Process -FilePath "D:\MT4LAB\agent\venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","main:app","--host","0.0.0.0","--port","8041" `
  -WorkingDirectory "D:\MT4LAB\agent" `
  -WindowStyle Hidden `
  -RedirectStandardOutput "D:\MT4LAB\agent\logs\ic.log" `
  -RedirectStandardError  "D:\MT4LAB\agent\logs\ic.err.log"

# Exness
$env:INSTANCE_NAME      = "qhmt4-exness"
$env:TERMINAL_FILES_DIR = "D:\MT4LAB\terminals\exness\MQL4\Files\qhbridge"
$env:SERVICE_PORT       = "8042"
$env:CMD_WAIT_SEC       = "20"
Start-Process -FilePath "D:\MT4LAB\agent\venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","main:app","--host","0.0.0.0","--port","8042" `
  -WorkingDirectory "D:\MT4LAB\agent" `
  -WindowStyle Hidden `
  -RedirectStandardOutput "D:\MT4LAB\agent\logs\exness.log" `
  -RedirectStandardError  "D:\MT4LAB\agent\logs\exness.err.log"

Start-Sleep -Seconds 12

Write-Host "`n=== [4] 验证 listener + CMD_WAIT_SEC ==="
Get-NetTCPConnection -LocalPort 8041,8042 -State Listen -ErrorAction SilentlyContinue | Format-Table LocalPort,OwningProcess -AutoSize
$p8041new = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$p8042new = (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "8041 new PID=$p8041new  8042 new PID=$p8042new"
(Get-CimInstance Win32_Process -Filter "ProcessId=$p8041new").CommandLine
(Get-CimInstance Win32_Process -Filter "ProcessId=$p8042new").CommandLine

Write-Host "`n=== [5] health check ==="
Start-Sleep -Seconds 3
try { Invoke-RestMethod -Uri "http://127.0.0.1:8041/health" -TimeoutSec 5 | ConvertTo-Json -Compress } catch { "8041 health FAIL" }
try { Invoke-RestMethod -Uri "http://127.0.0.1:8042/health" -TimeoutSec 5 | ConvertTo-Json -Compress } catch { "8042 health FAIL" }
