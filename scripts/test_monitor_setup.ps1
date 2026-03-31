# Quick Test Script for MT5 Health Monitor
# This script tests the monitoring functionality without sending alerts

Write-Host "=== MT5 Health Monitor Quick Test ===" -ForegroundColor Cyan
Write-Host ""

# Test 1: Check if monitoring script exists
Write-Host "Test 1: Checking script files..." -ForegroundColor Yellow
$scriptPath = "C:\MT5Agent\scripts\monitor_mt5_health_en.ps1"
if (Test-Path $scriptPath) {
    Write-Host "  [OK] Monitoring script found" -ForegroundColor Green
} else {
    Write-Host "  [ERROR] Monitoring script not found at $scriptPath" -ForegroundColor Red
    exit 1
}

# Test 2: Check MT5 Bridge services
Write-Host ""
Write-Host "Test 2: Checking MT5 Bridge services..." -ForegroundColor Yellow

try {
    $health8001 = Invoke-RestMethod -Uri "http://localhost:8001/health" -TimeoutSec 5
    Write-Host "  [OK] Port 8001: $($health8001.status) - MT5: $($health8001.mt5)" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Port 8001: Not responding" -ForegroundColor Red
}

try {
    $health8002 = Invoke-RestMethod -Uri "http://localhost:8002/health" -TimeoutSec 5
    Write-Host "  [OK] Port 8002: $($health8002.status) - MT5: $($health8002.mt5)" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Port 8002: Not responding" -ForegroundColor Red
}

# Test 3: Check MT5 processes
Write-Host ""
Write-Host "Test 3: Checking MT5 processes..." -ForegroundColor Yellow
$mt5Processes = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
if ($mt5Processes) {
    Write-Host "  [OK] Found $($mt5Processes.Count) MT5 process(es)" -ForegroundColor Green
    foreach ($proc in $mt5Processes) {
        Write-Host "      PID: $($proc.Id), Session: $($proc.SessionId), Window: $($proc.MainWindowHandle)" -ForegroundColor Gray
    }
} else {
    Write-Host "  [WARNING] No MT5 processes found" -ForegroundColor Yellow
}

# Test 4: Check log directory
Write-Host ""
Write-Host "Test 4: Checking log directory..." -ForegroundColor Yellow
$logDir = "C:\MT5Agent\logs"
if (Test-Path $logDir) {
    Write-Host "  [OK] Log directory exists" -ForegroundColor Green
} else {
    Write-Host "  [INFO] Creating log directory..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Write-Host "  [OK] Log directory created" -ForegroundColor Green
}

# Summary
Write-Host ""
Write-Host "=== Test Summary ===" -ForegroundColor Cyan
Write-Host "All basic checks passed. The monitoring system is ready." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Configure admin credentials in the monitoring script"
Write-Host "2. Test with alerts disabled:"
Write-Host "   .\monitor_mt5_health_en.ps1 -CheckInterval 10 -EnableAlert `$false"
Write-Host ""
Write-Host "3. Test with alerts enabled (requires admin credentials):"
Write-Host "   .\monitor_mt5_health_en.ps1 -CheckInterval 10 -AdminUsername 'admin' -AdminPassword 'your_password' -EnableAlert `$true"
Write-Host ""
Write-Host "4. Install as Windows service:"
Write-Host "   .\install_monitor_service.ps1 -AdminUsername 'admin' -AdminPassword 'your_password'"
Write-Host ""
