# 备份失败通知脚本
# 版本：1.0
# 日期：2024-02-10

param(
    [string]$errorMessage = "备份任务失败",
    [string]$logFile = ""
)

# 配置参数
$smtpServer = "smtp.example.com"
$smtpPort = 587
$smtpUser = "backup@example.com"
$smtpPassFile = "D:\secrets\smtp_password.txt"
$toEmail = "devops@example.com"

# 企业微信机器人配置
$wechatWebhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-webhook-key"

# 日志函数
function Write-Log {
    param([string]$message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
}

Write-Log "=== 发送备份失败通知 ==="

# 读取SMTP密码
if (Test-Path $smtpPassFile) {
    $smtpPass = Get-Content $smtpPassFile -Raw
} else {
    Write-Log "ERROR: SMTP密码文件不存在"
    exit 1
}

# 构建邮件内容
$subject = "[紧急] GitHub备份任务失败"
$body = @"
GitHub备份任务于 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 失败。

错误信息: $errorMessage

日志文件: $logFile

请尽快检查备份系统并处理问题。

-- 自动备份系统
"@

try {
    # 发送邮件通知
    Write-Log "发送邮件通知到: $toEmail"
    $smtpCredential = New-Object System.Management.Automation.PSCredential($smtpUser, (ConvertTo-SecureString $smtpPass -AsPlainText -Force))
    Send-MailMessage -To $toEmail -From $smtpUser -Subject $subject -Body $body -SmtpServer $smtpServer -Port $smtpPort -UseSsl -Credential $smtpCredential
    
    # 发送企业微信通知
    Write-Log "发送企业微信通知..."
    $wechatBody = @{
        msgtype = "text"
        text = @{
            content = "⚠️ GitHub备份任务失败\n\n错误信息: $errorMessage\n\n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        }
    } | ConvertTo-Json
    
    Invoke-RestMethod -Uri $wechatWebhook -Method Post -Body $wechatBody -ContentType "application/json"
    
    Write-Log "通知发送成功"
    exit 0
    
} catch {
    Write-Log "ERROR: 发送通知失败 - $_"
    exit 1
}