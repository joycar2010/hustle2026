# Hustle2026 Backend - NSSM Windows Service Installer
# Run as Administrator

$SERVICE_NAME  = "HustleBackend"
$PYTHON_EXE    = "C:\Python39\python.exe"
$APP_DIR       = "C:\app\hustle2026\backend"
$LOG_FILE      = "C:\app\hustle2026\backend\backend_live.log"
$TASK_NAME     = "HustleBackendService"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Hustle2026 Backend NSSM Service Installer " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Pre-checks
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] nssm not found in PATH." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $PYTHON_EXE)) {
    Write-Host "[ERROR] Python not found: $PYTHON_EXE" -ForegroundColor Red
    exit 1
}

# Step 1: Kill any process on port 8000
Write-Host "[1/6] Clearing port 8000..." -ForegroundColor Yellow
$conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Host "      Killing PID $($conn.OwningProcess)"
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
} else {
    Write-Host "      Port 8000 is free." -ForegroundColor Gray
}

# Step 2: Remove old scheduled task
Write-Host "[2/6] Removing old scheduled task ($TASK_NAME)..." -ForegroundColor Yellow
$oldTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($oldTask) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    Write-Host "      Removed." -ForegroundColor Green
} else {
    Write-Host "      Not found, skip." -ForegroundColor Gray
}

# Step 3: Remove existing NSSM service if present
Write-Host "[3/6] Checking for existing NSSM service..." -ForegroundColor Yellow
$existing = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "      Stopping and removing old service..."
    nssm stop $SERVICE_NAME 2>$null
    Start-Sleep -Seconds 2
    nssm remove $SERVICE_NAME confirm 2>$null
    Start-Sleep -Seconds 2
    Write-Host "      Removed." -ForegroundColor Green
} else {
    Write-Host "      No existing service." -ForegroundColor Gray
}

# Step 4: Install NSSM service
Write-Host "[4/6] Installing NSSM service..." -ForegroundColor Yellow

nssm install $SERVICE_NAME $PYTHON_EXE
nssm set $SERVICE_NAME AppDirectory  $APP_DIR
nssm set $SERVICE_NAME AppParameters "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
nssm set $SERVICE_NAME DisplayName   "Hustle2026 Backend API"
nssm set $SERVICE_NAME Description   "Hustle2026 FastAPI/uvicorn backend managed by NSSM"
nssm set $SERVICE_NAME ObjectName    LocalSystem
nssm set $SERVICE_NAME Start         SERVICE_AUTO_START
nssm set $SERVICE_NAME AppStdout     $LOG_FILE
nssm set $SERVICE_NAME AppStderr     $LOG_FILE
nssm set $SERVICE_NAME AppRotateFiles  1
nssm set $SERVICE_NAME AppRotateOnline 1
nssm set $SERVICE_NAME AppRotateBytes  52428800
nssm set $SERVICE_NAME AppRestartDelay 5000
nssm set $SERVICE_NAME AppThrottle     1500
nssm set $SERVICE_NAME DependOnService postgresql-x64-16

Write-Host "      Service installed." -ForegroundColor Green

# Step 5: Start service
Write-Host "[5/6] Starting service..." -ForegroundColor Yellow
nssm start $SERVICE_NAME
Start-Sleep -Seconds 10

$svc = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "      Service is RUNNING." -ForegroundColor Green
} else {
    $status = if ($svc) { $svc.Status } else { "NOT FOUND" }
    Write-Host "      WARNING: Service status = $status" -ForegroundColor Red
    Write-Host "      Check log: $LOG_FILE" -ForegroundColor Gray
}

# Step 6: Verify port
Write-Host "[6/6] Verifying port 8000..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
$portCheck = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($portCheck) {
    $proc = Get-Process -Id $portCheck.OwningProcess -ErrorAction SilentlyContinue
    Write-Host "      Port 8000 LISTENING - PID=$($portCheck.OwningProcess) ($($proc.Name))" -ForegroundColor Green
} else {
    Write-Host "      Port 8000 not listening yet - backend may still be initialising." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Done! Service commands:" -ForegroundColor Green
Write-Host "  nssm status  HustleBackend" -ForegroundColor Gray
Write-Host "  nssm start   HustleBackend" -ForegroundColor Gray
Write-Host "  nssm stop    HustleBackend" -ForegroundColor Gray
Write-Host "  nssm restart HustleBackend" -ForegroundColor Gray
Write-Host "  nssm edit    HustleBackend" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor Cyan
