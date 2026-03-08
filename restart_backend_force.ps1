# PowerShell script to forcefully restart backend server
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Backend Server Force Restart" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Method 1: Try using Get-NetTCPConnection
Write-Host "Method 1: Using Get-NetTCPConnection..." -ForegroundColor Yellow
$processes = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if ($processes) {
    foreach ($processId in $processes) {
        Write-Host "  Stopping process $processId..." -ForegroundColor Cyan
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "  Process $processId stopped successfully" -ForegroundColor Green
        } catch {
            Write-Host "  Failed to stop process $processId" -ForegroundColor Red
        }
    }
    Start-Sleep -Seconds 2
}

# Method 2: Try using netstat and taskkill
Write-Host ""
Write-Host "Method 2: Using netstat and taskkill..." -ForegroundColor Yellow
$netstatOutput = netstat -ano | Select-String ":8000.*LISTENING"
if ($netstatOutput) {
    foreach ($line in $netstatOutput) {
        $processId = ($line -split '\s+')[-1]
        Write-Host "  Killing process $processId with taskkill..." -ForegroundColor Cyan
        taskkill /F /PID $processId 2>$null
    }
    Start-Sleep -Seconds 2
}

# Verify port is free
Write-Host ""
Write-Host "Verifying port 8000 status..." -ForegroundColor Yellow
$stillRunning = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

if ($stillRunning) {
    Write-Host ""
    Write-Host "ERROR: Port 8000 is still in use!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please manually stop the processes:" -ForegroundColor Yellow
    Write-Host "1. Open Task Manager (Ctrl+Shift+Esc)" -ForegroundColor White
    Write-Host "2. Go to 'Details' tab" -ForegroundColor White
    Write-Host "3. Find and end these processes:" -ForegroundColor White

    $stillRunning | ForEach-Object {
        Write-Host "   - PID: $($_.OwningProcess)" -ForegroundColor Cyan
    }

    Write-Host ""
    Write-Host "Press any key to exit..." -ForegroundColor Cyan
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

Write-Host "SUCCESS: Port 8000 is now free!" -ForegroundColor Green
Write-Host ""

# Start backend server
Write-Host "Starting backend server..." -ForegroundColor Yellow
Set-Location "c:\app\hustle2026\backend"

Write-Host "Launching server in new window..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd c:\app\hustle2026\backend; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Backend server is starting!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "A new window has opened with the server." -ForegroundColor White
Write-Host "Please wait 5-10 seconds for initialization." -ForegroundColor White
Write-Host ""
Write-Host "Verify at: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
