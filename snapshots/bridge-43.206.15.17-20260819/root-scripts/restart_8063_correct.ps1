$venv_py = "D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe"
$inst    = "D:\QHCELL\pool\s3\inst"
$log_out = "$inst\logs\bridge.out.log"
$log_err = "$inst\logs\bridge.err.log"

Write-Host "=== [1] kill existing 8063 ==="
$old = Get-NetTCPConnection -LocalPort 8063 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($old) {
    Write-Host "Killing PID $($old.OwningProcess)"
    Stop-Process -Id $old.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
} else {
    Write-Host "No listener found"
}

Write-Host "=== [2] start 8063 with correct venv ==="
Start-Process -FilePath $venv_py `
  -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8063" `
  -WorkingDirectory $inst `
  -WindowStyle Hidden `
  -RedirectStandardOutput $log_out `
  -RedirectStandardError  $log_err

Start-Sleep -Seconds 8

Write-Host "=== [3] verify listener ==="
Get-NetTCPConnection -LocalPort 8063 -State Listen -ErrorAction SilentlyContinue | Format-Table -AutoSize

Write-Host "=== [4] health check ==="
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8063/health" -TimeoutSec 10
    $h | ConvertTo-Json -Compress
} catch { Write-Host "ERROR: $_" }

Write-Host "=== [5] err log tail ==="
Get-Content $log_err -Tail 8 -ErrorAction SilentlyContinue
