# Hustle MT5 Agent - Task Scheduler Installation Script
# Use Windows Task Scheduler for auto-start (more reliable than Windows Service)

$TaskName = "HustleMT5Agent"
$AgentPath = "D:\hustle-agent"
$PythonExe = (Get-Command python).Source
$AgentScript = "$AgentPath\agent.py"

Write-Host "=== Hustle MT5 Agent Task Scheduler Installer ===" -ForegroundColor Cyan

# Check admin privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Please run this script as Administrator" -ForegroundColor Red
    exit 1
}

# Check if Agent script exists
if (-not (Test-Path $AgentScript)) {
    Write-Host "ERROR: Agent script not found: $AgentScript" -ForegroundColor Red
    exit 1
}

# Remove existing task
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create scheduled task action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $AgentScript -WorkingDirectory $AgentPath

# Create trigger (at system startup)
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Create settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Create principal (run as SYSTEM)
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Register the task
Write-Host "Registering scheduled task..." -ForegroundColor Green
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Hustle MT5 Agent - Microservice Management"

Write-Host "`n=== Task Registration Complete ===" -ForegroundColor Green
Write-Host "Task Name: $TaskName" -ForegroundColor Cyan
Write-Host "Trigger: At system startup" -ForegroundColor Cyan
Write-Host "Run As: SYSTEM" -ForegroundColor Cyan

# Start the task immediately
Write-Host "`nStarting task..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TaskName

Start-Sleep -Seconds 5

# Test API
Write-Host "`nTesting API..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:9000/" -TimeoutSec 10
    Write-Host "API test successful!" -ForegroundColor Green
    Write-Host ($response | ConvertTo-Json) -ForegroundColor Gray
    Write-Host "`nAgent is running at: http://127.0.0.1:9000" -ForegroundColor Cyan
} catch {
    Write-Host "API test failed. Checking task status..." -ForegroundColor Yellow
    $task = Get-ScheduledTask -TaskName $TaskName
    Write-Host "Task State: $($task.State)" -ForegroundColor Gray
    
    # Check if python process is running
    $pythonProc = Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $PythonExe}
    if ($pythonProc) {
        Write-Host "Python process is running (PID: $($pythonProc.Id))" -ForegroundColor Green
        Write-Host "Agent may still be starting up. Please wait a moment and try again." -ForegroundColor Yellow
    } else {
        Write-Host "Python process not found. Please check Task Scheduler logs." -ForegroundColor Red
    }
}

Write-Host "`nCommon Commands:" -ForegroundColor Cyan
Write-Host "  Start:   Start-ScheduledTask -TaskName $TaskName" -ForegroundColor Gray
Write-Host "  Stop:    Stop-ScheduledTask -TaskName $TaskName" -ForegroundColor Gray
Write-Host "  Status:  Get-ScheduledTask -TaskName $TaskName" -ForegroundColor Gray
Write-Host "  Remove:  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false" -ForegroundColor Gray
Write-Host "  Logs:    Get-WinEvent -LogName Microsoft-Windows-TaskScheduler/Operational -MaxEvents 10" -ForegroundColor Gray
