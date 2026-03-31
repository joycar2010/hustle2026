<#
.SYNOPSIS
    MT5 客户端健康监控脚本 - 持续监控并在异常时发送警报

.DESCRIPTION
    监控 MT5 Bridge 服务和客户端状态，检测异常并通过 Go 服务器 API 发送弹窗和飞书通知

.PARAMETER Port
    MT5 Bridge 服务端口（默认：8001 和 8002）

.PARAMETER CheckInterval
    健康检查间隔（秒），默认 30 秒

.PARAMETER ApiBaseUrl
    后端 API 基础 URL（默认：https://admin.hustle2026.xyz）

.PARAMETER AdminUsername
    管理员用户名（用于 API 认证）

.PARAMETER AdminPassword
    管理员密码（用于 API 认证）

.PARAMETER EnableAlert
    是否启用警报通知（默认：true）

.EXAMPLE
    .\monitor_mt5_health.ps1 -CheckInterval 60

.EXAMPLE
    .\monitor_mt5_health.ps1 -ApiBaseUrl "https://admin.hustle2026.xyz" -AdminUsername "admin" -AdminPassword "password"
#>

param(
    [int[]]$Ports = @(8001, 8002),
    [int]$CheckInterval = 30,
    [string]$ApiBaseUrl = "https://admin.hustle2026.xyz",
    [string]$AdminUsername = "",
    [string]$AdminPassword = "",
    [bool]$EnableAlert = $true,
    [string]$LogPath = "C:\MT5Agent\logs\health_monitor.log"
)

# 确保日志目录存在
$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# 日志函数
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage
    Add-Content -Path $LogPath -Value $logMessage
}

# 显示弹窗警报
function Show-Alert {
    param(
        [string]$Title,
        [string]$Message,
        [string]$Severity = "Warning"
    )

    if (-not $EnablePopup) { return }

    try {
        Add-Type -AssemblyName System.Windows.Forms
        $icon = switch ($Severity) {
            "Error" { [System.Windows.Forms.MessageBoxIcon]::Error }
            "Warning" { [System.Windows.Forms.MessageBoxIcon]::Warning }
            default { [System.Windows.Forms.MessageBoxIcon]::Information }
        }

        [System.Windows.Forms.MessageBox]::Show($Message, $Title, 0, $icon)
        Write-Log "弹窗警报已显示: $Title - $Message" "ALERT"
    } catch {
        Write-Log "显示弹窗失败: $_" "ERROR"
    }
}

# 发送飞书通知
function Send-FeishuAlert {
    param(
        [string]$Title,
        [string]$Message,
        [string]$Severity = "Warning"
    )

    if (-not $EnableFeishu -or [string]::IsNullOrEmpty($FeishuWebhook)) { return }

    try {
        $color = switch ($Severity) {
            "Error" { "red" }
            "Warning" { "orange" }
            default { "blue" }
        }

        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $hostname = $env:COMPUTERNAME

        $body = @{
            msg_type = "interactive"
            card = @{
                header = @{
                    title = @{
                        tag = "plain_text"
                        content = "🚨 MT5 监控警报"
                    }
                    template = $color
                }
                elements = @(
                    @{
                        tag = "div"
                        text = @{
                            tag = "lark_md"
                            content = "**警报级别**: $Severity`n**服务器**: $hostname`n**时间**: $timestamp`n`n**标题**: $Title`n`n**详情**: $Message"
                        }
                    }
                )
            }
        } | ConvertTo-Json -Depth 10

        $response = Invoke-RestMethod -Uri $FeishuWebhook -Method Post -Body $body -ContentType "application/json"
        Write-Log "飞书通知已发送: $Title" "ALERT"
    } catch {
        Write-Log "发送飞书通知失败: $_" "ERROR"
    }
}

# 检查单个实例健康状态
function Test-MT5Instance {
    param([int]$Port)

    $result = @{
        Port = $Port
        Healthy = $false
        BridgeRunning = $false
        MT5Connected = $false
        MT5ProcessRunning = $false
        ErrorMessage = ""
        Details = @{}
    }

    try {
        # 1. 检查 Bridge 服务健康
        try {
            $healthResponse = Invoke-RestMethod -Uri "http://localhost:$Port/health" -Method Get -TimeoutSec 5
            $result.BridgeRunning = $healthResponse.status -eq "healthy"
            $result.Details.BridgeHealth = $healthResponse
        } catch {
            $result.ErrorMessage += "Bridge 服务无响应; "
            return $result
        }

        # 2. 检查 MT5 连接状态
        try {
            $statusResponse = Invoke-RestMethod -Uri "http://localhost:$Port/mt5/connection/status" -Method Get -TimeoutSec 5
            $result.MT5Connected = $statusResponse.mt5 -eq $true
            $result.Details.ConnectionStatus = $statusResponse

            if (-not $result.MT5Connected) {
                $result.ErrorMessage += "MT5 未连接到服务器; "
            }
        } catch {
            $result.ErrorMessage += "无法获取 MT5 连接状态; "
        }

        # 3. 检查 MT5 进程
        $mt5Process = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue |
                      Where-Object { $_.MainWindowTitle -match "MetaTrader 5" }

        if ($mt5Process) {
            $result.MT5ProcessRunning = $true
            $result.Details.ProcessInfo = @{
                PID = $mt5Process.Id
                SessionId = $mt5Process.SessionId
                MainWindowHandle = $mt5Process.MainWindowHandle
            }
        } else {
            $result.ErrorMessage += "MT5 进程未运行; "
        }

        # 判断整体健康状态
        $result.Healthy = $result.BridgeRunning -and $result.MT5Connected -and $result.MT5ProcessRunning

    } catch {
        $result.ErrorMessage += "健康检查异常: $_"
        Write-Log "检查端口 $Port 时发生异常: $_" "ERROR"
    }

    return $result
}

# 状态缓存（用于检测状态变化）
$script:LastStatus = @{}

# 主监控循环
Write-Log "=== MT5 健康监控启动 ===" "INFO"
Write-Log "监控端口: $($Ports -join ', ')" "INFO"
Write-Log "检查间隔: $CheckInterval 秒" "INFO"
Write-Log "弹窗警报: $EnablePopup" "INFO"
Write-Log "飞书通知: $EnableFeishu" "INFO"

if ($EnableFeishu -and [string]::IsNullOrEmpty($FeishuWebhook)) {
    Write-Log "警告: 已启用飞书通知但未配置 Webhook URL" "WARNING"
}

try {
    while ($true) {
        foreach ($port in $Ports) {
            $instanceName = switch ($port) {
                8001 { "MT5-系统服务" }
                8002 { "MT5-01" }
                default { "MT5-端口$port" }
            }

            Write-Log "检查 $instanceName (端口 $port)..." "INFO"
            $status = Test-MT5Instance -Port $port

            # 获取上次状态
            $lastHealthy = $script:LastStatus[$port]

            if (-not $status.Healthy) {
                $alertTitle = "MT5 实例异常: $instanceName"
                $alertMessage = "端口: $port`n错误: $($status.ErrorMessage)`n`n详细状态:`n" +
                                "- Bridge 服务: $(if($status.BridgeRunning){'运行中'}else{'已停止'})`n" +
                                "- MT5 连接: $(if($status.MT5Connected){'已连接'}else{'未连接'})`n" +
                                "- MT5 进程: $(if($status.MT5ProcessRunning){'运行中'}else{'未运行'})"

                Write-Log "检测到异常: $instanceName - $($status.ErrorMessage)" "ERROR"

                # 只在状态从健康变为不健康时发送警报（避免重复通知）
                if ($lastHealthy -eq $true -or $null -eq $lastHealthy) {
                    Show-Alert -Title $alertTitle -Message $alertMessage -Severity "Error"
                    Send-FeishuAlert -Title $alertTitle -Message $alertMessage -Severity "Error"
                }
            } else {
                Write-Log "$instanceName 状态正常" "INFO"

                # 如果从不健康恢复到健康，发送恢复通知
                if ($lastHealthy -eq $false) {
                    $recoveryTitle = "MT5 实例已恢复: $instanceName"
                    $recoveryMessage = "端口 $port 的 MT5 实例已恢复正常运行"
                    Write-Log $recoveryMessage "INFO"
                    Show-Alert -Title $recoveryTitle -Message $recoveryMessage -Severity "Information"
                    Send-FeishuAlert -Title $recoveryTitle -Message $recoveryMessage -Severity "Info"
                }
            }

            # 更新状态缓存
            $script:LastStatus[$port] = $status.Healthy
        }

        Write-Log "等待 $CheckInterval 秒后进行下次检查..." "INFO"
        Start-Sleep -Seconds $CheckInterval
    }
} catch {
    Write-Log "监控循环异常终止: $_" "ERROR"
    throw
} finally {
    Write-Log "=== MT5 健康监控停止 ===" "INFO"
}
