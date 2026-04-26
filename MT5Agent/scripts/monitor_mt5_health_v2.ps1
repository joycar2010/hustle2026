<#
.SYNOPSIS
    MT5 客户端健康监控脚本 V2 - 通过后端 API 发送警报

.DESCRIPTION
    监控 MT5 Bridge 服务和客户端状态，检测异常并通过后端 API 发送弹窗和飞书通知

.PARAMETER Ports
    MT5 Bridge 服务端口列表（默认：8001 和 8002）

.PARAMETER CheckInterval
    健康检查间隔（秒），默认 30 秒

.PARAMETER ApiBaseUrl
    后端 API 基础 URL

.PARAMETER AdminUsername
    管理员用户名（用于 API 认证）

.PARAMETER AdminPassword
    管理员密码（用于 API 认证）

.PARAMETER EnableAlert
    是否启用警报通知（默认：true）

.EXAMPLE
    .\monitor_mt5_health_v2.ps1 -CheckInterval 60

.EXAMPLE
    .\monitor_mt5_health_v2.ps1 -AdminUsername "admin" -AdminPassword "password"
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

# 全局变量
$script:AccessToken = $null
$script:TokenExpiry = $null

# 日志函数
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage
    Add-Content -Path $LogPath -Value $logMessage
}

# 获取 API 访问令牌
function Get-ApiToken {
    if ($script:AccessToken -and $script:TokenExpiry -and (Get-Date) -lt $script:TokenExpiry) {
        return $script:AccessToken
    }

    if ([string]::IsNullOrEmpty($AdminUsername) -or [string]::IsNullOrEmpty($AdminPassword)) {
        Write-Log "未配置管理员凭据，无法获取 API 令牌" "ERROR"
        return $null
    }

    try {
        $loginUrl = "$ApiBaseUrl/api/v1/auth/login"
        $loginBody = @{
            username = $AdminUsername
            password = $AdminPassword
        } | ConvertTo-Json

        $response = Invoke-RestMethod -Uri $loginUrl -Method Post -Body $loginBody -ContentType "application/json" -ErrorAction Stop

        $script:AccessToken = $response.access_token
        # Token 有效期通常 24 小时，提前 1 小时刷新
        $script:TokenExpiry = (Get-Date).AddHours(23)

        Write-Log "API 令牌获取成功" "INFO"
        return $script:AccessToken
    } catch {
        Write-Log "获取 API 令牌失败: $_" "ERROR"
        return $null
    }
}

# 发送警报通知（通过后端 API）
function Send-Alert {
    param(
        [string]$Title,
        [string]$Message,
        [string]$Severity = "Warning",
        [string]$InstanceName = ""
    )

    if (-not $EnableAlert) {
        Write-Log "警报已禁用，跳过发送: $Title" "INFO"
        return
    }

    $token = Get-ApiToken
    if (-not $token) {
        Write-Log "无法发送警报：未获取到 API 令牌" "ERROR"
        return
    }

    try {
        # 构建通知内容
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $hostname = $env:COMPUTERNAME

        $notificationContent = @"
**服务器**: $hostname
**实例**: $InstanceName
**时间**: $timestamp

**详情**:
$Message
"@

        # 调用后端通知 API
        $notifyUrl = "$ApiBaseUrl/api/v1/notifications/send"
        $headers = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }

        # 获取所有管理员用户 ID
        $usersUrl = "$ApiBaseUrl/api/v1/users"
        $usersResponse = Invoke-RestMethod -Uri $usersUrl -Method Get -Headers $headers -ErrorAction Stop

        $adminUserIds = $usersResponse.users |
            Where-Object { $_.role -in @('系统管理员', '管理员', 'admin', 'super_admin') } |
            Select-Object -ExpandProperty user_id

        if ($adminUserIds.Count -eq 0) {
            Write-Log "未找到管理员用户，无法发送通知" "WARNING"
            return
        }

        # 根据严重程度选择模板
        $templateKey = switch ($Severity) {
            "Error" { "mt5_client_error" }
            "Warning" { "mt5_client_warning" }
            default { "mt5_client_info" }
        }

        $notifyBody = @{
            template_key = $templateKey
            user_ids = @($adminUserIds)
            variables = @{
                title = $Title
                content = $notificationContent
                instance_name = $InstanceName
                severity = $Severity
                hostname = $hostname
            }
        } | ConvertTo-Json -Depth 10

        $notifyResponse = Invoke-RestMethod -Uri $notifyUrl -Method Post -Headers $headers -Body $notifyBody -ErrorAction Stop

        if ($notifyResponse.success) {
            Write-Log "警报通知已发送: $Title (发送 $($notifyResponse.sent_count)/$($notifyResponse.total))" "ALERT"
        } else {
            Write-Log "警报通知发送失败: $Title" "ERROR"
        }
    } catch {
        Write-Log "发送警报通知异常: $_" "ERROR"
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
Write-Log "=== MT5 健康监控启动 (V2 - API 版本) ===" "INFO"
Write-Log "监控端口: $($Ports -join ', ')" "INFO"
Write-Log "检查间隔: $CheckInterval 秒" "INFO"
Write-Log "API 地址: $ApiBaseUrl" "INFO"
Write-Log "警报通知: $EnableAlert" "INFO"

if ($EnableAlert -and ([string]::IsNullOrEmpty($AdminUsername) -or [string]::IsNullOrEmpty($AdminPassword))) {
    Write-Log "警告: 已启用警报但未配置管理员凭据" "WARNING"
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
                    Send-Alert -Title $alertTitle -Message $alertMessage -Severity "Error" -InstanceName $instanceName
                }
            } else {
                Write-Log "$instanceName 状态正常" "INFO"

                # 如果从不健康恢复到健康，发送恢复通知
                if ($lastHealthy -eq $false) {
                    $recoveryTitle = "MT5 实例已恢复: $instanceName"
                    $recoveryMessage = "端口 $port 的 MT5 实例已恢复正常运行"
                    Write-Log $recoveryMessage "INFO"
                    Send-Alert -Title $recoveryTitle -Message $recoveryMessage -Severity "Info" -InstanceName $instanceName
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

