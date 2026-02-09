# 备份日志记录系统
# 版本：1.0
# 日期：2024-02-10

param(
    [string]$logDir = "D:\logs\backup",
    [string]$logLevel = "INFO",  # DEBUG, INFO, WARNING, ERROR
    [int]$maxLogDays = 180
)

# 初始化目录
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

# 日志级别
$logLevels = @{
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
}

# 当前日志级别
$currentLevel = $logLevels[$logLevel]

# 日志文件路径
$logFile = "$logDir\backup_$(Get-Date -Format 'yyyyMMdd').log"

# 日志函数
function Write-Log {
    param(
        [string]$message,
        [string]$level = "INFO"
    )
    
    # 检查日志级别
    if ($logLevels[$level] -lt $currentLevel) {
        return
    }
    
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $logMessage = "[$timestamp] [$level] $message"
    
    # 输出到控制台
    switch ($level) {
        "ERROR" { Write-Host $logMessage -ForegroundColor Red }
        "WARNING" { Write-Host $logMessage -ForegroundColor Yellow }
        "DEBUG" { Write-Host $logMessage -ForegroundColor Gray }
        default { Write-Host $logMessage }
    }
    
    # 写入日志文件
    Add-Content -Path $logFile -Value $logMessage
}

# 系统信息日志
Write-Log "=== 备份日志系统初始化 ===" "INFO"
Write-Log "日志级别: $logLevel" "INFO"
Write-Log "日志目录: $logDir" "INFO"
Write-Log "最大保留天数: $maxLogDays" "INFO"

# 清理过期日志
Write-Log "开始清理过期日志..." "INFO"
$expireDate = (Get-Date).AddDays(-$maxLogDays)
$oldLogs = Get-ChildItem -Path $logDir -Filter "*.log" | Where-Object { $_.CreationTime -lt $expireDate }

foreach ($log in $oldLogs) {
    Write-Log "删除过期日志: $($log.Name)" "INFO"
    Remove-Item -Path $log.FullName -Force
}

Write-Log "日志系统初始化完成" "INFO"

# 导出日志函数供其他脚本使用
Export-ModuleMember -Function Write-Log

# 示例用法
# Write-Log "备份任务开始" "INFO"
# Write-Log "磁盘空间不足" "WARNING"
# Write-Log "备份失败: 网络错误" "ERROR"
# Write-Log "详细调试信息" "DEBUG"