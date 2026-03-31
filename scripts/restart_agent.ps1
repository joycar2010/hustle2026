# Restart Windows Agent
Write-Host "Stopping Windows Agent..." -ForegroundColor Yellow

# Find and stop MT5Agent process
$procs = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*MT5Agent*" }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force
    Write-Host "Stopped process $($p.ProcessId)" -ForegroundColor Green
}

Start-Sleep -Seconds 2

# Start Windows Agent
Write-Host "Starting Windows Agent..." -ForegroundColor Yellow
Start-Process -FilePath "python" -ArgumentList "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent" -WindowStyle Hidden
Write-Host "Windows Agent started" -ForegroundColor Green
