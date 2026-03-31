# Windows Agent V3 Deployment Script
# This script helps deploy the Windows Agent to the MT5 server

Write-Host "=== Windows Agent V3 Deployment Script ===" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[WARNING] Not running as Administrator. Some operations may fail." -ForegroundColor Yellow
    Write-Host ""
}

# Configuration
$AgentDir = "C:\MT5Agent"
$LogDir = "$AgentDir\logs"
$ConfigFile = "$AgentDir\config.json"
$InstancesFile = "$AgentDir\instances.json"

# Step 1: Create directories
Write-Host "Step 1: Creating directories..." -ForegroundColor Yellow
if (-not (Test-Path $AgentDir)) {
    New-Item -ItemType Directory -Path $AgentDir -Force | Out-Null
    Write-Host "  [OK] Created $AgentDir" -ForegroundColor Green
} else {
    Write-Host "  [OK] Directory already exists: $AgentDir" -ForegroundColor Green
}

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Host "  [OK] Created $LogDir" -ForegroundColor Green
} else {
    Write-Host "  [OK] Directory already exists: $LogDir" -ForegroundColor Green
}

# Step 2: Check Python
Write-Host ""
Write-Host "Step 2: Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  [OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Python not found. Please install Python 3.8+" -ForegroundColor Red
    exit 1
}

# Step 3: Install dependencies
Write-Host ""
Write-Host "Step 3: Installing Python dependencies..." -ForegroundColor Yellow
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
if (Test-Path $requirementsPath) {
    pip install -r $requirementsPath
    Write-Host "  [OK] Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  [WARNING] requirements.txt not found, installing manually..." -ForegroundColor Yellow
    pip install fastapi uvicorn psutil httpx pydantic python-multipart
    Write-Host "  [OK] Dependencies installed" -ForegroundColor Green
}

# Step 4: Copy files
Write-Host ""
Write-Host "Step 4: Copying agent files..." -ForegroundColor Yellow
$sourceFiles = @(
    "main_v3.py",
    "config.example.json",
    "instances.example.json"
)

foreach ($file in $sourceFiles) {
    $sourcePath = Join-Path $PSScriptRoot $file
    if (Test-Path $sourcePath) {
        $destPath = Join-Path $AgentDir $file
        Copy-Item -Path $sourcePath -Destination $destPath -Force
        Write-Host "  [OK] Copied $file" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] File not found: $file" -ForegroundColor Yellow
    }
}

# Step 5: Create config files if not exist
Write-Host ""
Write-Host "Step 5: Setting up configuration files..." -ForegroundColor Yellow

if (-not (Test-Path $ConfigFile)) {
    $exampleConfig = Join-Path $AgentDir "config.example.json"
    if (Test-Path $exampleConfig) {
        Copy-Item -Path $exampleConfig -Destination $ConfigFile
        Write-Host "  [OK] Created config.json from example" -ForegroundColor Green
        Write-Host "  [INFO] Please edit $ConfigFile to configure your settings" -ForegroundColor Cyan
    }
} else {
    Write-Host "  [OK] config.json already exists" -ForegroundColor Green
}

if (-not (Test-Path $InstancesFile)) {
    $exampleInstances = Join-Path $AgentDir "instances.example.json"
    if (Test-Path $exampleInstances) {
        Copy-Item -Path $exampleInstances -Destination $InstancesFile
        Write-Host "  [OK] Created instances.json from example" -ForegroundColor Green
        Write-Host "  [INFO] Please edit $InstancesFile to configure your MT5 instances" -ForegroundColor Cyan
    }
} else {
    Write-Host "  [OK] instances.json already exists" -ForegroundColor Green
}

# Step 6: Test agent
Write-Host ""
Write-Host "Step 6: Testing agent..." -ForegroundColor Yellow
Write-Host "  [INFO] Starting agent for 5 seconds to test..." -ForegroundColor Cyan

$agentScript = Join-Path $AgentDir "main_v3.py"
if (Test-Path $agentScript) {
    $job = Start-Job -ScriptBlock {
        param($script)
        python $script
    } -ArgumentList $agentScript

    Start-Sleep -Seconds 5

    # Check if agent is responding
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8765/health" -TimeoutSec 3
        Write-Host "  [OK] Agent is responding: $($response.status)" -ForegroundColor Green
        Write-Host "  [OK] Version: $($response.version)" -ForegroundColor Green
    } catch {
        Write-Host "  [WARNING] Agent not responding yet (this is normal on first run)" -ForegroundColor Yellow
    }

    Stop-Job -Job $job
    Remove-Job -Job $job
} else {
    Write-Host "  [ERROR] main_v3.py not found" -ForegroundColor Red
}

# Step 7: Create startup script
Write-Host ""
Write-Host "Step 7: Creating startup script..." -ForegroundColor Yellow
$startupScript = @"
@echo off
cd /d $AgentDir
python main_v3.py
"@

$startupBat = Join-Path $AgentDir "start_agent.bat"
Set-Content -Path $startupBat -Value $startupScript
Write-Host "  [OK] Created $startupBat" -ForegroundColor Green

# Summary
Write-Host ""
Write-Host "=== Deployment Summary ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Agent Directory: $AgentDir" -ForegroundColor White
Write-Host "Configuration: $ConfigFile" -ForegroundColor White
Write-Host "Instances: $InstancesFile" -ForegroundColor White
Write-Host "Logs: $LogDir" -ForegroundColor White
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Edit configuration files:"
Write-Host "   - $ConfigFile"
Write-Host "   - $InstancesFile"
Write-Host ""
Write-Host "2. Start the agent:"
Write-Host "   cd $AgentDir"
Write-Host "   python main_v3.py"
Write-Host ""
Write-Host "3. Or use the startup script:"
Write-Host "   $startupBat"
Write-Host ""
Write-Host "4. Access API documentation:"
Write-Host "   http://localhost:8765/docs"
Write-Host ""
Write-Host "5. For production, install as Windows service using NSSM"
Write-Host "   See documentation for details"
Write-Host ""
Write-Host "Deployment completed!" -ForegroundColor Green
