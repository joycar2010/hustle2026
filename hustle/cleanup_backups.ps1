# 备份清理脚本
# 版本：1.0
# 日期：2024-02-10

param(
    [string]$backupDir = "D:\backups\github",
    [string]$encryptedDir = "D:\backups\encrypted",
    [int]$dailyKeepDays = 30,
    [int]$weeklyKeepMonths = 3,
    [int]$monthlyKeepYears = 1
)

# 日志函数
function Write-Log {
    param([string]$message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
}

Write-Log "=== 备份清理任务开始 ==="

# 1. 清理每日备份（保留30天）
Write-Log "开始清理每日备份（保留$dailyKeepDays天）..."
$dailyExpireDate = (Get-Date).AddDays(-$dailyKeepDays)
$dailyBackups = Get-ChildItem -Path $backupDir -Directory | Where-Object { $_.CreationTime -lt $dailyExpireDate }

foreach ($backup in $dailyBackups) {
    # 检查是否是每周或每月备份（特殊标记）
    if ($backup.Name -match "-weekly-" -or $backup.Name -match "-monthly-") {
        Write-Log "跳过特殊备份: $($backup.Name)"
        continue
    }
    
    Write-Log "删除过期每日备份: $($backup.Name)"
    Remove-Item -Path $backup.FullName -Recurse -Force
}

# 2. 清理加密备份
Write-Log "开始清理加密备份..."
$encryptedExpireDate = (Get-Date).AddDays(-$dailyKeepDays)
$encryptedBackups = Get-ChildItem -Path $encryptedDir -Filter "*.7z" | Where-Object { $_.CreationTime -lt $encryptedExpireDate }

foreach ($backup in $encryptedBackups) {
    Write-Log "删除过期加密备份: $($backup.Name)"
    Remove-Item -Path $backup.FullName -Force
    
    # 删除对应的哈希文件
    $hashFile = "$encryptedDir\$($backup.BaseName).hash"
    if (Test-Path $hashFile) {
        Remove-Item -Path $hashFile -Force
    }
}

# 3. 清理每周备份（保留3个月）
Write-Log "开始清理每周备份（保留$weeklyKeepMonths个月）..."
$weeklyExpireDate = (Get-Date).AddMonths(-$weeklyKeepMonths)
$weeklyBackups = Get-ChildItem -Path $backupDir -Directory | Where-Object { $_.Name -match "-weekly-" -and $_.CreationTime -lt $weeklyExpireDate }

foreach ($backup in $weeklyBackups) {
    Write-Log "删除过期每周备份: $($backup.Name)"
    Remove-Item -Path $backup.FullName -Recurse -Force
}

# 4. 清理每月备份（保留1年）
Write-Log "开始清理每月备份（保留$monthlyKeepYears年）..."
$monthlyExpireDate = (Get-Date).AddYears(-$monthlyKeepYears)
$monthlyBackups = Get-ChildItem -Path $backupDir -Directory | Where-Object { $_.Name -match "-monthly-" -and $_.CreationTime -lt $monthlyExpireDate }

foreach ($backup in $monthlyBackups) {
    Write-Log "删除过期每月备份: $($backup.Name)"
    Remove-Item -Path $backup.FullName -Recurse -Force
}

# 5. 计算存储节省
$totalSaved = 0
$allBackups = Get-ChildItem -Path $backupDir -Directory -Recurse | Measure-Object -Property Length -Sum
if ($allBackups.Sum) {
    $totalSaved = [math]::Round($allBackups.Sum / 1GB, 2)
}

Write-Log "备份清理任务完成"
Write-Log "已释放存储: ${totalSaved} GB"

# 6. 生成清理报告
$reportFile = "D:\logs\backup\cleanup_report_$(Get-Date -Format 'yyyyMMdd').log"
$reportContent = @"
备份清理报告
生成时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

保留策略:
- 每日备份: $dailyKeepDays天
- 每周备份: $weeklyKeepMonths个月
- 每月备份: $monthlyKeepYears年

已删除:
- 每日备份: $($dailyBackups.Count)个
- 加密备份: $($encryptedBackups.Count)个
- 每周备份: $($weeklyBackups.Count)个
- 每月备份: $($monthlyBackups.Count)个

释放空间: ${totalSaved} GB
"@

Set-Content -Path $reportFile -Value $reportContent
Write-Log "清理报告已生成: $reportFile"

exit 0