# Hustle2026 System Startup Configuration Script
# This script configures Windows Task Scheduler to start all required services on system boot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Hustle2026 Startup Configuration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Define services to configure
$services = @(
    @{
        Name = "HustleNginxService"
        Description = "Start Nginx web server for Hustle2026"
        Script = "C:\app\hustle2026\start_nginx_service.vbs"
        Delay = "PT30S"  # 30 seconds delay
    },
    @{
        Name = "HustleMT5Service"
        Description = "Start MetaTrader 5 client for Hustle2026"
        Script = "C:\app\hustle2026\start_mt5_service.vbs"
        Delay = "PT1M"  # 1 minute delay
    },
    @{
        Name = "HustleBackendService"
        Description = "Start backend API service for Hustle2026"
        Script = "C:\app\hustle2026\start_backend_service.vbs"
        Delay = "PT1M30S"  # 1.5 minutes delay
    },
    @{
        Name = "HustleFrontendService"
        Description = "Start frontend development server for Hustle2026"
        Script = "C:\app\hustle2026\start_frontend_service.vbs"
        Delay = "PT2M"  # 2 minutes delay
    }
)

# Function to create or update scheduled task
function Set-StartupTask {
    param(
        [string]$TaskName,
        [string]$Description,
        [string]$ScriptPath,
        [string]$Delay
    )

    Write-Host "[*] Configuring task: $TaskName" -ForegroundColor Yellow

    # Check if task exists
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    if ($existingTask) {
        Write-Host "    Task exists, removing old configuration..." -ForegroundColor Gray
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    # Create trigger (at system startup with delay)
    $trigger = New-ScheduledTaskTrigger -AtStartup
    if ($Delay) {
        $trigger.Delay = $Delay
    }

    # Create action
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument """$ScriptPath"""

    # Create settings
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0)

    # Create principal (run as SYSTEM)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    # Register task
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $Description `
        -Trigger $trigger `
        -Action $action `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host "    Task configured successfully!" -ForegroundColor Green
}

# Configure each service
foreach ($service in $services) {
    Set-StartupTask `
        -TaskName $service.Name `
        -Description $service.Description `
        -ScriptPath $service.Script `
        -Delay $service.Delay
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Configuration Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configured services:" -ForegroundColor White
Write-Host "  1. Nginx (30s delay)" -ForegroundColor Gray
Write-Host "  2. MetaTrader 5 (1m delay)" -ForegroundColor Gray
Write-Host "  3. Backend API (1m 30s delay)" -ForegroundColor Gray
Write-Host "  4. Frontend Dev Server (2m delay)" -ForegroundColor Gray
Write-Host ""
Write-Host "Note: PostgreSQL is already configured as a Windows Service" -ForegroundColor Yellow
Write-Host ""
Write-Host "To verify configuration, run:" -ForegroundColor White
Write-Host "  Get-ScheduledTask | Where-Object {`$_.TaskName -like 'Hustle*'}" -ForegroundColor Gray
Write-Host ""
