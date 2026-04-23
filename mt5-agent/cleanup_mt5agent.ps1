# MT5Agent 目录清理脚本
# 执行方式：在 Windows 服务器上以管理员身份运行

Write-Host "=== MT5Agent 目录清理脚本 ===" -ForegroundColor Green

# 创建新的备份目录
$backupDir = "C:\MT5Agent\backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# 备份重要文件
Write-Host "`n备份重要文件..." -ForegroundColor Yellow
Copy-Item "C:\MT5Agent\main_v3.py" "$backupDir\main_v3.py" -Force
Copy-Item "C:\MT5Agent\config.json" "$backupDir\config.json" -Force
Copy-Item "C:\MT5Agent\instances.json" "$backupDir\instances.json" -Force
Write-Host "已创建备份: $backupDir" -ForegroundColor Green

# 删除临时和开发文件
Write-Host "`n删除临时和开发文件..." -ForegroundColor Yellow
$filesToDelete = @(
    "C:\MT5Agent\main.py",
    "C:\MT5Agent\main.py.backup",
    "C:\MT5Agent\main.py.backup.20260331_123207",
    "C:\MT5Agent\main.py.backup_",
    "C:\MT5Agent\main_v2.py",
    "C:\MT5Agent\main_v2.py.backup_",
    "C:\MT5Agent\main_v4.py",
    "C:\MT5Agent\add_health_endpoints.py",
    "C:\MT5Agent\apply_mt5_fix.py",
    "C:\MT5Agent\fix_mt5_agent_stop.ps1",
    "C:\MT5Agent\migrate_agent_files.ps1",
    "C:\MT5Agent\migration_report.txt",
    "C:\MT5Agent\restart_agent.ps1",
    "C:\MT5Agent\start-agent.bat",
    "C:\MT5Agent\start.bat",
    "C:\MT5Agent\start.ps1",
    "C:\MT5Agent\start_agent.ps1",
    "C:\MT5Agent\start_mt5_agent.bat",
    "C:\MT5Agent\start_mt5_gui.ps1",
    "C:\MT5Agent\stderr.log",
    "C:\MT5Agent\stdout.log",
    "C:\MT5Agent\agent.log",
    "C:\MT5Agent\agent_error.log",
    "C:\MT5Agent\requirements_hustle_agent.txt"
)

$deletedCount = 0
foreach ($file in $filesToDelete) {
    if (Test-Path $file) {
        Remove-Item $file -Force
        Write-Host "  已删除: $(Split-Path $file -Leaf)" -ForegroundColor Gray
        $deletedCount++
    }
}
Write-Host "共删除 $deletedCount 个文件" -ForegroundColor Green

# 删除旧的备份目录（保留最新的3个）
Write-Host "`n清理旧备份..." -ForegroundColor Yellow
$backups = Get-ChildItem "C:\MT5Agent" -Directory -Filter "backup_*" | Sort-Object LastWriteTime -Descending
if ($backups -and $backups.Count -gt 3) {
    $backups | Select-Object -Skip 3 | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force
        Write-Host "  已删除旧备份: $($_.Name)" -ForegroundColor Gray
    }
    Write-Host "保留最新的 3 个备份" -ForegroundColor Green
} else {
    Write-Host "备份数量合理，无需清理" -ForegroundColor Green
}

Write-Host "`n=== 清理完成 ===" -ForegroundColor Green
Write-Host "`n保留的主要文件:" -ForegroundColor Cyan
Get-ChildItem "C:\MT5Agent" -File | Select-Object Name, @{Name="Size(KB)";Expression={[math]::Round($_.Length/1KB,2)}}, LastWriteTime | Format-Table -AutoSize
