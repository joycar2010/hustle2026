# MT5 GUI Launcher - PowerShell Version
# Start MT5 clients with GUI in RDP session

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MT5 GUI Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running in RDP session
$currentSession = query session | Select-String "Active" | Select-Object -First 1
if ($currentSession -notmatch "rdp-tcp") {
    Write-Host "[ERROR] This script must be run in an RDP session!" -ForegroundColor Red
    Write-Host "Please connect via RDP and run this script again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[INFO] Running in RDP session - OK" -ForegroundColor Green
Write-Host ""

# Function to start MT5 instance
function Start-MT5Instance {
    param(
        [string]$Name,
        [string]$Path,
        [string]$WorkingDir
    )

    Write-Host "Starting $Name..." -ForegroundColor Yellow

    if (-not (Test-Path $Path)) {
        Write-Host "  [WARNING] Not found: $Path" -ForegroundColor Yellow
        Write-Host "  Skipping $Name..." -ForegroundColor Gray
        return $false
    }

    # Check if already running (by exact path)
    $targetPath = [System.IO.Path]::GetFullPath($Path).ToLower()
    $alreadyRunning = $false

    Get-Process -Name terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $procPath = $_.Path
            if ($procPath) {
                $procPath = [System.IO.Path]::GetFullPath($procPath).ToLower()
                if ($procPath -eq $targetPath) {
                    $alreadyRunning = $true
                    Write-Host "  [INFO] Already running (PID: $($_.Id))" -ForegroundColor Gray
                }
            }
        } catch {}
    }

    if (-not $alreadyRunning) {
        try {
            Start-Process -FilePath $Path -ArgumentList "/portable" -WorkingDirectory $WorkingDir
            Start-Sleep -Seconds 2

            # Verify started
            $started = $false
            Get-Process -Name terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
                try {
                    $procPath = $_.Path
                    if ($procPath) {
                        $procPath = [System.IO.Path]::GetFullPath($procPath).ToLower()
                        if ($procPath -eq $targetPath) {
                            $started = $true
                            Write-Host "  [SUCCESS] Started (PID: $($_.Id), SessionId: $($_.SessionId))" -ForegroundColor Green
                        }
                    }
                } catch {}
            }

            if (-not $started) {
                Write-Host "  [WARNING] Failed to verify startup" -ForegroundColor Yellow
            }

            return $started
        } catch {
            Write-Host "  [ERROR] Failed to start: $_" -ForegroundColor Red
            return $false
        }
    }

    return $true
}

# ========================================
# Start MT5 Instances
# ========================================

Write-Host "Step 1: Starting MT5 Instances..." -ForegroundColor Cyan
Write-Host ""

# MT5-01 Instance
$mt5_01_started = Start-MT5Instance `
    -Name "MT5-01" `
    -Path "D:\MetaTrader 5-01\terminal64.exe" `
    -WorkingDir "D:\MetaTrader 5-01"

Write-Host ""

# MT5 System Service Instance
$mt5_sys_started = Start-MT5Instance `
    -Name "MT5 System Service" `
    -Path "D:\MetaTrader 5\terminal64.exe" `
    -WorkingDir "D:\MetaTrader 5"

Write-Host ""

# ========================================
# Verify MT5 Processes
# ========================================

Write-Host "Step 2: Verifying MT5 processes..." -ForegroundColor Cyan
Write-Host ""

$mt5Processes = Get-Process -Name terminal64 -ErrorAction SilentlyContinue

if ($mt5Processes) {
    $mt5Processes | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize

    # Check if any process has MainWindowHandle = 0 (no GUI)
    $noGuiProcesses = $mt5Processes | Where-Object { $_.MainWindowHandle -eq 0 }
    if ($noGuiProcesses) {
        Write-Host "[WARNING] Some MT5 processes have no GUI window (MainWindowHandle = 0)" -ForegroundColor Yellow
        Write-Host "This usually means they were started in Session 0 (system service session)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "To fix this:" -ForegroundColor Yellow
        Write-Host "1. Stop all MT5 processes" -ForegroundColor Gray
        Write-Host "2. Run this script again in RDP session" -ForegroundColor Gray
    } else {
        Write-Host "[SUCCESS] All MT5 processes have GUI windows" -ForegroundColor Green
    }
} else {
    Write-Host "[WARNING] No MT5 processes found" -ForegroundColor Yellow
}

Write-Host ""

# ========================================
# Summary
# ========================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MT5 GUI Launcher Complete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($mt5_01_started -or $mt5_sys_started) {
    Write-Host "MT5 clients are now running in this RDP session." -ForegroundColor Green
    Write-Host "You can now use the admin panel to start/stop MT5 Bridge services." -ForegroundColor Green
    Write-Host ""
    Write-Host "IMPORTANT: Keep this RDP session active!" -ForegroundColor Yellow
    Write-Host "If you disconnect, MT5 windows will remain running." -ForegroundColor Gray
} else {
    Write-Host "No MT5 instances were started." -ForegroundColor Yellow
    Write-Host "Please check the paths and try again." -ForegroundColor Yellow
}

Write-Host ""
Read-Host "Press Enter to exit"
