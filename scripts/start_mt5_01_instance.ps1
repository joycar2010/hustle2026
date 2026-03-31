# Start MT5-01 Instance (Account: 2325036, Port: 8002)
# This script starts the MT5 client for MT5-01 instance in RDP session

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting MT5-01 Instance" -ForegroundColor Cyan
Write-Host "Account: 2325036" -ForegroundColor Cyan
Write-Host "Port: 8002" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running in RDP session
$currentSession = query session | Select-String "Active" | Select-Object -First 1
if ($currentSession -notmatch "rdp-tcp") {
    Write-Host "[WARNING] Not running in RDP session!" -ForegroundColor Yellow
    Write-Host "MT5 GUI may not be visible if started from SSH/Console session." -ForegroundColor Yellow
    Write-Host "For best results, run this script in RDP session." -ForegroundColor Yellow
    Write-Host ""
}

# MT5-01 Instance Configuration
$mt5Path = "D:\MetaTrader 5-01\terminal64.exe"
$mt5Dir = "D:\MetaTrader 5-01"

# Check if MT5 executable exists
if (-not (Test-Path $mt5Path)) {
    Write-Host "[ERROR] MT5 executable not found: $mt5Path" -ForegroundColor Red
    Write-Host "Please check the path and try again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[INFO] MT5 executable found: $mt5Path" -ForegroundColor Green
Write-Host ""

# Check if MT5 is already running (by exact path)
Write-Host "Checking if MT5-01 is already running..." -ForegroundColor Yellow
$targetPath = [System.IO.Path]::GetFullPath($mt5Path).ToLower()
$alreadyRunning = $false
$existingProcess = $null

Get-Process -Name terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $procPath = $_.Path
        if ($procPath) {
            $procPath = [System.IO.Path]::GetFullPath($procPath).ToLower()
            if ($procPath -eq $targetPath) {
                $alreadyRunning = $true
                $existingProcess = $_
            }
        }
    } catch {}
}

if ($alreadyRunning) {
    Write-Host "[INFO] MT5-01 is already running" -ForegroundColor Green
    Write-Host ""
    Write-Host "Process Details:" -ForegroundColor Cyan
    $existingProcess | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize

    if ($existingProcess.SessionId -eq 0) {
        Write-Host "[WARNING] MT5 is running in Session 0 (system service session)" -ForegroundColor Yellow
        Write-Host "The GUI window will NOT be visible in RDP session." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "To fix this:" -ForegroundColor Yellow
        Write-Host "1. Stop the MT5 process" -ForegroundColor Gray
        Write-Host "2. Run this script again in RDP session" -ForegroundColor Gray
        Write-Host ""

        $response = Read-Host "Do you want to stop and restart MT5 in user session? (Y/N)"
        if ($response -eq "Y" -or $response -eq "y") {
            Write-Host "Stopping MT5 process..." -ForegroundColor Yellow
            Stop-Process -Id $existingProcess.Id -Force
            Start-Sleep -Seconds 2
            Write-Host "MT5 stopped. Restarting..." -ForegroundColor Yellow
        } else {
            Write-Host "Keeping existing MT5 process." -ForegroundColor Gray
            Read-Host "Press Enter to exit"
            exit 0
        }
    } elseif ($existingProcess.MainWindowHandle -eq 0) {
        Write-Host "[WARNING] MT5 has no GUI window (MainWindowHandle = 0)" -ForegroundColor Yellow
        Write-Host "This may indicate the process is running without GUI." -ForegroundColor Yellow
    } else {
        Write-Host "[SUCCESS] MT5-01 is running with GUI in user session" -ForegroundColor Green
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Cyan
        Write-Host "1. Verify MT5 window is visible in RDP session" -ForegroundColor Gray
        Write-Host "2. Check MT5 is logged in (Account: 2325036)" -ForegroundColor Gray
        Write-Host "3. Go to https://admin.hustle2026.xyz/users" -ForegroundColor Gray
        Write-Host "4. Click 'Start' button for MT5-01 instance" -ForegroundColor Gray
        Write-Host "5. The Bridge service will connect to this MT5 client" -ForegroundColor Gray
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 0
    }
}

# Start MT5 client
Write-Host "Starting MT5-01 client..." -ForegroundColor Yellow
try {
    Start-Process -FilePath $mt5Path -ArgumentList "/portable" -WorkingDirectory $mt5Dir
    Start-Sleep -Seconds 3

    # Verify startup
    Write-Host "Verifying MT5 startup..." -ForegroundColor Yellow
    $started = $false
    $newProcess = $null

    Get-Process -Name terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $procPath = $_.Path
            if ($procPath) {
                $procPath = [System.IO.Path]::GetFullPath($procPath).ToLower()
                if ($procPath -eq $targetPath) {
                    $started = $true
                    $newProcess = $_
                }
            }
        } catch {}
    }

    if ($started) {
        Write-Host ""
        Write-Host "[SUCCESS] MT5-01 started successfully" -ForegroundColor Green
        Write-Host ""
        Write-Host "Process Details:" -ForegroundColor Cyan
        $newProcess | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize

        if ($newProcess.SessionId -eq 0) {
            Write-Host "[WARNING] MT5 started in Session 0 (system service session)" -ForegroundColor Yellow
            Write-Host "The GUI window will NOT be visible in RDP session." -ForegroundColor Yellow
            Write-Host ""
            Write-Host "This usually happens when:" -ForegroundColor Yellow
            Write-Host "- The script is run via SSH instead of RDP" -ForegroundColor Gray
            Write-Host "- The script is run as a system service" -ForegroundColor Gray
            Write-Host ""
            Write-Host "To fix this, run this script in RDP session." -ForegroundColor Yellow
        } elseif ($newProcess.MainWindowHandle -eq 0) {
            Write-Host "[WARNING] MT5 has no GUI window yet" -ForegroundColor Yellow
            Write-Host "Wait a few seconds for MT5 to fully initialize..." -ForegroundColor Gray
        } else {
            Write-Host "[SUCCESS] MT5-01 is running with GUI in user session" -ForegroundColor Green
        }

        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "MT5-01 Instance Started" -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Cyan
        Write-Host "1. Verify MT5 window is visible in RDP session" -ForegroundColor Gray
        Write-Host "2. Check MT5 is logged in (Account: 2325036)" -ForegroundColor Gray
        Write-Host "3. Go to https://admin.hustle2026.xyz/users" -ForegroundColor Gray
        Write-Host "4. Click 'Start' button for MT5-01 instance" -ForegroundColor Gray
        Write-Host "5. The Bridge service will connect to this MT5 client" -ForegroundColor Gray

    } else {
        Write-Host ""
        Write-Host "[ERROR] Failed to verify MT5 startup" -ForegroundColor Red
        Write-Host "The process may have started but could not be detected." -ForegroundColor Yellow
        Write-Host "Please check manually if MT5 window is visible." -ForegroundColor Yellow
    }

} catch {
    Write-Host ""
    Write-Host "[ERROR] Failed to start MT5: $_" -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to exit"
