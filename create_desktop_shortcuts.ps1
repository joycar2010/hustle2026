# Hustle2026 Desktop Shortcuts Creator
# This script creates desktop shortcuts for managing Hustle2026 services

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Creating Hustle2026 Desktop Shortcuts" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get desktop path
$desktopPath = [Environment]::GetFolderPath('Desktop')
Write-Host "Desktop path: $desktopPath" -ForegroundColor Gray
Write-Host ""

# Create WScript.Shell COM object
$WshShell = New-Object -ComObject WScript.Shell

# Shortcut 1: Start Services
Write-Host "[1/2] Creating 'Start Hustle2026 Services' shortcut..." -ForegroundColor Yellow
$shortcut1 = $WshShell.CreateShortcut("$desktopPath\Start Hustle2026 Services.lnk")
$shortcut1.TargetPath = 'C:\app\hustle2026\start_services.bat'
$shortcut1.WorkingDirectory = 'C:\app\hustle2026'
$shortcut1.Description = 'Start all Hustle2026 services (Nginx, MT5, Backend, Frontend)'
$shortcut1.IconLocation = 'C:\Windows\System32\shell32.dll,21'  # Green play icon
$shortcut1.WindowStyle = 1  # Normal window
$shortcut1.Save()
Write-Host "    Created: Start Hustle2026 Services.lnk" -ForegroundColor Green

# Shortcut 2: Check Services Status
Write-Host "[2/2] Creating 'Check Hustle2026 Services' shortcut..." -ForegroundColor Yellow
$shortcut2 = $WshShell.CreateShortcut("$desktopPath\Check Hustle2026 Services.lnk")
$shortcut2.TargetPath = 'C:\app\hustle2026\check_services.bat'
$shortcut2.WorkingDirectory = 'C:\app\hustle2026'
$shortcut2.Description = 'Check status of all Hustle2026 services'
$shortcut2.IconLocation = 'C:\Windows\System32\shell32.dll,23'  # Information icon
$shortcut2.WindowStyle = 1  # Normal window
$shortcut2.Save()
Write-Host "    Created: Check Hustle2026 Services.lnk" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Shortcuts Created Successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Desktop shortcuts:" -ForegroundColor White
Write-Host "  1. Start Hustle2026 Services - Start all services" -ForegroundColor Gray
Write-Host "  2. Check Hustle2026 Services - Check service status" -ForegroundColor Gray
Write-Host ""
Write-Host "Location: $desktopPath" -ForegroundColor Cyan
Write-Host ""
