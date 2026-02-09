# GitHub仓库自动备份脚本
# 版本：1.0
# 日期：2024-02-10

param(
    [string]$repoUrl = "https://github.com/joycar2010/hustle.git",
    [string]$backupDir = "D:\backups\github",
    [string]$logDir = "D:\logs\backup",
    [int]$daysToKeep = 30
)

# 初始化目录
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

# 获取时间戳
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = "$logDir\backup_$timestamp.log"

# 日志函数
function Write-Log {
    param([string]$message)
    $logMessage = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
    Write-Host $logMessage
    Add-Content -Path $logFile -Value $logMessage
}

Write-Log "=== GitHub仓库备份任务开始 ==="
Write-Log "仓库URL: $repoUrl"
Write-Log "备份目录: $backupDir"
Write-Log "日志目录: $logDir"

# 创建备份子目录
$backupSubDir = "$backupDir\$timestamp"
New-Item -ItemType Directory -Path $backupSubDir -Force | Out-Null
Write-Log "创建备份目录: $backupSubDir"

try {
    # 1. 克隆完整仓库镜像
    Write-Log "开始克隆仓库镜像..."
    $mirrorDir = "$backupSubDir\hustle-mirror.git"
    git clone --mirror $repoUrl $mirrorDir 2>&1 | ForEach-Object { Write-Log "git: $_" }
    
    if ($LASTEXITCODE -ne 0) {
        throw "仓库克隆失败，退出码: $LASTEXITCODE"
    }
    
    # 2. 导出分支信息
    Write-Log "导出分支信息..."
    cd $mirrorDir
    git branch -a > "$backupSubDir\branches.txt"
    
    # 3. 导出标签信息
    Write-Log "导出标签信息..."
    git tag -l > "$backupSubDir\tags.txt"
    
    # 4. 导出提交历史
    Write-Log "导出提交历史..."
    git log --oneline --all > "$backupSubDir\commit_history.txt"
    
    # 5. 导出仓库信息
    Write-Log "导出仓库信息..."
    git remote show origin > "$backupSubDir\repo_info.txt"
    
    # 6. 计算备份大小
    $backupSize = (Get-ChildItem -Path $backupSubDir -Recurse | Measure-Object -Property Length -Sum).Sum
    $backupSizeMB = [math]::Round($backupSize / 1MB, 2)
    Write-Log "备份完成，总大小: ${backupSizeMB} MB"
    
    # 7. 清理过期备份
    Write-Log "开始清理过期备份（保留$daysToKeep天）..."
    $expireDate = (Get-Date).AddDays(-$daysToKeep)
    Get-ChildItem -Path $backupDir -Directory | Where-Object { $_.CreationTime -lt $expireDate } | ForEach-Object {
        Write-Log "删除过期备份: $($_.FullName)"
        Remove-Item -Path $_.FullName -Recurse -Force
    }
    
    Write-Log "=== GitHub仓库备份任务完成 ==="
    
} catch {
    Write-Log "ERROR: 备份任务失败 - $_"
    # 发送错误通知
    $errorMessage = "GitHub备份失败: $_"
    # 这里可以添加邮件或即时通讯通知逻辑
    exit 1
}

# 清理临时目录
cd $PSScriptRoot

# 验证备份文件
if (Test-Path "$backupSubDir\hustle-mirror.git\config") {
    Write-Log "备份文件验证成功"
    exit 0
} else {
    Write-Log "ERROR: 备份文件验证失败"
    exit 1
}