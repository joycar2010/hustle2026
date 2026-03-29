# Hustle2026 Backend — start/restart via NSSM Windows Service
# Called by: start_backend_service.vbs (scheduled task fallback) OR manually

$SERVICE_NAME = "HustleBackend"

$svc = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue

if ($svc) {
    # NSSM service exists — use it
    if ($svc.Status -eq "Running") {
        Write-Host "[HustleBackend] Service already running, restarting..."
        nssm restart $SERVICE_NAME
    } else {
        Write-Host "[HustleBackend] Starting NSSM service..."
        nssm start $SERVICE_NAME
    }
} else {
    # Fallback: NSSM service not installed — use direct launch
    Write-Host "[HustleBackend] WARNING: NSSM service not found, using direct launch fallback"
    Write-Host "[HustleBackend] Run install_backend_service.ps1 as Administrator to fix this"

    $conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }

    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c cd /d C:\app\hustle2026\backend && C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> backend_live.log 2>&1" `
        -WindowStyle Hidden
}
