# PowerShell script to restart backend server
Write-Host "Stopping backend processes..." -ForegroundColor Yellow

# Get all processes listening on port 8000
$processes = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if ($processes) {
    foreach ($processId in $processes) {
        Write-Host "Stopping process $processId..." -ForegroundColor Cyan
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Waiting for processes to stop..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
} else {
    Write-Host "No processes found on port 8000" -ForegroundColor Green
}

# Verify port is free
$stillRunning = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($stillRunning) {
    Write-Host "Warning: Port 8000 is still in use!" -ForegroundColor Red
    Write-Host "Please manually stop the processes using Task Manager" -ForegroundColor Red
    exit 1
}

Write-Host "Port 8000 is now free" -ForegroundColor Green
Write-Host ""
Write-Host "Starting backend server..." -ForegroundColor Yellow

# Change to backend directory
Set-Location "c:\app\hustle2026\backend"

# Start backend server in a new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host ""
Write-Host "Backend server is starting in a new window..." -ForegroundColor Green
Write-Host "Please wait a few seconds for initialization." -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
