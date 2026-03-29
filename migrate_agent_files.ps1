# MT5 Agent File Migration Script
# Migrate useful files from D:\hustle-agent to C:\MT5Agent

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MT5 Agent File Migration Tool" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path "D:\hustle-agent")) {
    Write-Host "[ERROR] Source directory D:\hustle-agent does not exist" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "C:\MT5Agent")) {
    Write-Host "[ERROR] Target directory C:\MT5Agent does not exist" -ForegroundColor Red
    exit 1
}

Write-Host "[1/5] Analyzing source directory..." -ForegroundColor Yellow
$sourceFiles = Get-ChildItem "D:\hustle-agent" -File
Write-Host "Found $($sourceFiles.Count) files:" -ForegroundColor Green
$sourceFiles | ForEach-Object {
    Write-Host "  - $($_.Name) ($([math]::Round($_.Length/1KB, 2)) KB)"
}
Write-Host ""

$filesToMigrate = @{
    "agent_v4.py" = "main_v4.py"
    "install-agent-service.ps1" = "install-agent-service.ps1"
    "install-service.ps1" = "install-service.ps1"
    "install-task.ps1" = "install-task.ps1"
    "start-agent.bat" = "start-agent.bat"
    "requirements.txt" = "requirements_hustle_agent.txt"
}

Write-Host "[2/5] Backing up target directory..." -ForegroundColor Yellow
$backupDir = "C:\MT5Agent\backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Write-Host "Backup directory: $backupDir" -ForegroundColor Green

Get-ChildItem "C:\MT5Agent" -File | ForEach-Object {
    Copy-Item $_.FullName -Destination $backupDir -Force
    Write-Host "  Backed up: $($_.Name)" -ForegroundColor Gray
}
Write-Host ""

Write-Host "[3/5] Migrating files..." -ForegroundColor Yellow
$migratedCount = 0
$skippedCount = 0

foreach ($sourceFile in $filesToMigrate.Keys) {
    $sourcePath = "D:\hustle-agent\$sourceFile"
    $targetFile = $filesToMigrate[$sourceFile]
    $targetPath = "C:\MT5Agent\$targetFile"

    if (Test-Path $sourcePath) {
        try {
            Copy-Item $sourcePath -Destination $targetPath -Force
            Write-Host "  OK $sourceFile -> $targetFile" -ForegroundColor Green
            $migratedCount++
        } catch {
            Write-Host "  FAIL $sourceFile - $($_.Exception.Message)" -ForegroundColor Red
        }
    } else {
        Write-Host "  SKIP $sourceFile (not found)" -ForegroundColor Gray
        $skippedCount++
    }
}
Write-Host ""

Write-Host "[4/5] Generating migration report..." -ForegroundColor Yellow
$reportPath = "C:\MT5Agent\migration_report.txt"
$reportContent = "MT5 Agent File Migration Report`n"
$reportContent += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n`n"
$reportContent += "Source: D:\hustle-agent`n"
$reportContent += "Target: C:\MT5Agent`n"
$reportContent += "Backup: $backupDir`n`n"
$reportContent += "Statistics:`n"
$reportContent += "- Migrated: $migratedCount files`n"
$reportContent += "- Skipped: $skippedCount files`n`n"
$reportContent += "Migrated files:`n"

foreach ($sourceFile in $filesToMigrate.Keys) {
    $targetFile = $filesToMigrate[$sourceFile]
    $sourcePath = "D:\hustle-agent\$sourceFile"
    if (Test-Path $sourcePath) {
        $fileInfo = Get-Item $sourcePath
        $reportContent += "  - $sourceFile -> $targetFile ($([math]::Round($fileInfo.Length/1KB, 2)) KB)`n"
    }
}

$reportContent | Out-File -FilePath $reportPath -Encoding UTF8
Write-Host "Report saved: $reportPath" -ForegroundColor Green
Write-Host ""

Write-Host "[5/5] Verifying migration..." -ForegroundColor Yellow
Write-Host "Target directory files:" -ForegroundColor Cyan
Get-ChildItem "C:\MT5Agent" -File | Sort-Object Name | ForEach-Object {
    $size = [math]::Round($_.Length/1KB, 2)
    $modified = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    Write-Host "  $($_.Name.PadRight(40)) $($size.ToString().PadLeft(8)) KB  $modified"
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Migration Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Original files kept in D:\hustle-agent" -ForegroundColor White
Write-Host "2. Old files backed up to $backupDir" -ForegroundColor White
Write-Host "3. agent_v4.py copied as main_v4.py (latest version)" -ForegroundColor White
Write-Host "4. To use the new version, run:" -ForegroundColor White
Write-Host "   cd C:\MT5Agent" -ForegroundColor Cyan
Write-Host "   copy main_v4.py main.py" -ForegroundColor Cyan
Write-Host "   Restart-Service MT5Agent" -ForegroundColor Cyan
Write-Host ""
Write-Host "5. After verification, D:\hustle-agent can be deleted" -ForegroundColor White
Write-Host ""
