$ErrorActionPreference = "Continue"

Write-Host "=== [1] kill 8063 bridge (PID 6556) ==="
Stop-Process -Id 6556 -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "=== [2] restart 8063 from s3 inst dir (new code with _pick_filling) ==="
Start-Process -FilePath "C:\Python311\python.exe" `
  -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8063" `
  -WorkingDirectory "D:\QHCELL\pool\s3\inst" `
  -WindowStyle Hidden `
  -RedirectStandardOutput "D:\QHCELL\pool\s3\inst\logs\bridge.out.log" `
  -RedirectStandardError  "D:\QHCELL\pool\s3\inst\logs\bridge.err.log"

Start-Sleep -Seconds 8

Write-Host "=== [3] verify listener ==="
Get-NetTCPConnection -LocalPort 8063 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalPort,OwningProcess | Format-Table -AutoSize

Write-Host "=== [4] health ==="
try {
  $h = Invoke-RestMethod -Uri "http://127.0.0.1:8063/health" -TimeoutSec 10
  $h | ConvertTo-Json -Compress
} catch { Write-Host "health FAIL: $_" }

Write-Host "=== [5] err log tail ==="
Get-Content "D:\QHCELL\pool\s3\inst\logs\bridge.err.log" -Tail 5 -ErrorAction SilentlyContinue
