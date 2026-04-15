# Hustle MT5 Agent - Windows Service Installation Script
# Register Agent as Windows Service for auto-start

$ServiceName = "HustleMT5Agent"
$DisplayName = "Hustle MT5 Agent Service"
$Description = "MT5 microservice management agent for deploying and managing MT5 instances"
$AgentPath = "D:\hustle-agent"
$PythonExe = (Get-Command python).Source
$AgentScript = "$AgentPath\agent.py"

Write-Host "=== Hustle MT5 Agent Service Installer ===" -ForegroundColor Cyan

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

# Stop and remove existing service
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "Stopping existing service..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    
    Write-Host "Removing existing service..." -ForegroundColor Yellow
    sc.exe delete $ServiceName
    Start-Sleep -Seconds 2
}

# Create service startup script
Write-Host "Creating service startup script..." -ForegroundColor Green
$startScript = @"
@echo off
cd /d $AgentPath
$PythonExe agent.py
"@
$startScript | Out-File -FilePath "$AgentPath\start-agent.bat" -Encoding ASCII

# Create Windows service using sc.exe
Write-Host "Registering Windows service..." -ForegroundColor Green
$binPath = "cmd.exe /c `"$AgentPath\start-agent.bat`""
sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $DisplayName

# Set service description
sc.exe description $ServiceName $Description

# Configure service auto-restart on failure
sc.exe failure $ServiceName reset= 86400 actions= restart/60000/restart/60000/restart/60000

Write-Host "`n=== Service Installation Complete ===" -ForegroundColor Green
Write-Host "Service Name: $ServiceName" -ForegroundColor Cyan
Write-Host "Display Name: $DisplayName" -ForegroundColor Cyan
Write-Host "Startup Type: Automatic" -ForegroundColor Cyan
Write-Host "`nStarting service..." -ForegroundColor Yellow
Start-Service -Name $ServiceName

Start-Sleep -Seconds 3

# Verify service status
$service = Get-Service -Name $ServiceName
if ($service.Status -eq "Running") {
    Write-Host "`nService started successfully!" -ForegroundColor Green
    Write-Host "API Endpoint: http://127.0.0.1:9000" -ForegroundColor Cyan
    
    # Test API
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:9000/" -TimeoutSec 5
        Write-Host "`nAPI test successful!" -ForegroundColor Green
        Write-Host ($response | ConvertTo-Json) -ForegroundColor Gray
    } catch {
        Write-Host "`nAPI test failed, please check logs" -ForegroundColor Yellow
    }
} else {
    Write-Host "`nService failed to start, status: $($service.Status)" -ForegroundColor Red
    Write-Host "Please check Event Viewer for error logs" -ForegroundColor Yellow
}

Write-Host "`nCommon Commands:" -ForegroundColor Cyan
Write-Host "  Start:   Start-Service $ServiceName" -ForegroundColor Gray
Write-Host "  Stop:    Stop-Service $ServiceName" -ForegroundColor Gray
Write-Host "  Restart: Restart-Service $ServiceName" -ForegroundColor Gray
Write-Host "  Status:  Get-Service $ServiceName" -ForegroundColor Gray
Write-Host "  Remove:  sc.exe delete $ServiceName" -ForegroundColor Gray
