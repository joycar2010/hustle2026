# MT5 Health Monitor V2 - API Based (English version)
param(
    [int[]]$Ports = @(8001, 8002),
    [int]$CheckInterval = 30,
    [string]$ApiBaseUrl = "https://admin.hustle2026.xyz",
    [string]$AdminUsername = "",
    [string]$AdminPassword = "",
    [bool]$EnableAlert = $true,
    [string]$LogPath = "C:\MT5Agent\logs\health_monitor.log"
)

$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$script:AccessToken = $null
$script:TokenExpiry = $null

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage
    Add-Content -Path $LogPath -Value $logMessage
}

function Get-ApiToken {
    if ($script:AccessToken -and $script:TokenExpiry -and (Get-Date) -lt $script:TokenExpiry) {
        return $script:AccessToken
    }

    if ([string]::IsNullOrEmpty($AdminUsername) -or [string]::IsNullOrEmpty($AdminPassword)) {
        Write-Log "No admin credentials configured" "ERROR"
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
        $script:TokenExpiry = (Get-Date).AddHours(23)
        Write-Log "API token obtained successfully" "INFO"
        return $script:AccessToken
    } catch {
        Write-Log "Failed to get API token: $_" "ERROR"
        return $null
    }
}

function Send-Alert {
    param(
        [string]$Title,
        [string]$Message,
        [string]$Severity = "Warning",
        [string]$InstanceName = ""
    )

    if (-not $EnableAlert) {
        Write-Log "Alert disabled, skipping: $Title" "INFO"
        return
    }

    $token = Get-ApiToken
    if (-not $token) {
        Write-Log "Cannot send alert: no API token" "ERROR"
        return
    }

    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $hostname = $env:COMPUTERNAME

        $notificationContent = @"
**Server**: $hostname
**Instance**: $InstanceName
**Time**: $timestamp

**Details**:
$Message
"@

        $notifyUrl = "$ApiBaseUrl/api/v1/notifications/send"
        $headers = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }

        $usersUrl = "$ApiBaseUrl/api/v1/users"
        $usersResponse = Invoke-RestMethod -Uri $usersUrl -Method Get -Headers $headers -ErrorAction Stop

        $adminUserIds = $usersResponse.users |
            Where-Object { $_.role -in @('admin', 'super_admin') } |
            Select-Object -ExpandProperty user_id

        if ($adminUserIds.Count -eq 0) {
            Write-Log "No admin users found" "WARNING"
            return
        }

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
            Write-Log "Alert sent: $Title (sent $($notifyResponse.sent_count)/$($notifyResponse.total))" "ALERT"
        } else {
            Write-Log "Alert send failed: $Title" "ERROR"
        }
    } catch {
        Write-Log "Alert exception: $_" "ERROR"
    }
}

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
        try {
            $healthResponse = Invoke-RestMethod -Uri "http://localhost:$Port/health" -Method Get -TimeoutSec 5
            $result.BridgeRunning = $healthResponse.status -eq "healthy"
            $result.Details.BridgeHealth = $healthResponse
        } catch {
            $result.ErrorMessage += "Bridge service not responding; "
            return $result
        }

        try {
            $statusResponse = Invoke-RestMethod -Uri "http://localhost:$Port/mt5/connection/status" -Method Get -TimeoutSec 5
            $result.MT5Connected = $statusResponse.mt5 -eq $true
            $result.Details.ConnectionStatus = $statusResponse

            if (-not $result.MT5Connected) {
                $result.ErrorMessage += "MT5 not connected to server; "
            }
        } catch {
            $result.ErrorMessage += "Cannot get MT5 connection status; "
        }

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
            $result.ErrorMessage += "MT5 process not running; "
        }

        $result.Healthy = $result.BridgeRunning -and $result.MT5Connected -and $result.MT5ProcessRunning

    } catch {
        $result.ErrorMessage += "Health check exception: $_"
        $errorMsg = $_.Exception.Message
        Write-Log "Exception checking port ${Port}: $errorMsg" "ERROR"
    }

    return $result
}

$script:LastStatus = @{}

Write-Log "=== MT5 Health Monitor Started (V2 - API Version) ===" "INFO"
Write-Log "Monitoring ports: $($Ports -join ', ')" "INFO"
Write-Log "Check interval: $CheckInterval seconds" "INFO"
Write-Log "API URL: $ApiBaseUrl" "INFO"
Write-Log "Alert enabled: $EnableAlert" "INFO"

if ($EnableAlert -and ([string]::IsNullOrEmpty($AdminUsername) -or [string]::IsNullOrEmpty($AdminPassword))) {
    Write-Log "WARNING: Alert enabled but no admin credentials configured" "WARNING"
}

try {
    while ($true) {
        foreach ($port in $Ports) {
            $instanceName = switch ($port) {
                8001 { "MT5-System-Service" }
                8002 { "MT5-01" }
                default { "MT5-Port$port" }
            }

            Write-Log "Checking $instanceName (port $port)..." "INFO"
            $status = Test-MT5Instance -Port $port

            $lastHealthy = $script:LastStatus[$port]

            if (-not $status.Healthy) {
                $alertTitle = "MT5 Instance Error: $instanceName"
                $alertMessage = "Port: $port`nError: $($status.ErrorMessage)`n`nStatus:`n" +
                                "- Bridge Service: $(if($status.BridgeRunning){'Running'}else{'Stopped'})`n" +
                                "- MT5 Connection: $(if($status.MT5Connected){'Connected'}else{'Disconnected'})`n" +
                                "- MT5 Process: $(if($status.MT5ProcessRunning){'Running'}else{'Not Running'})"

                Write-Log "Detected error: $instanceName - $($status.ErrorMessage)" "ERROR"

                if ($lastHealthy -eq $true -or $null -eq $lastHealthy) {
                    Send-Alert -Title $alertTitle -Message $alertMessage -Severity "Error" -InstanceName $instanceName
                }
            } else {
                Write-Log "$instanceName status OK" "INFO"

                if ($lastHealthy -eq $false) {
                    $recoveryTitle = "MT5 Instance Recovered: $instanceName"
                    $recoveryMessage = "Port $port MT5 instance has recovered to normal operation"
                    Write-Log $recoveryMessage "INFO"
                    Send-Alert -Title $recoveryTitle -Message $recoveryMessage -Severity "Info" -InstanceName $instanceName
                }
            }

            $script:LastStatus[$port] = $status.Healthy
        }

        Write-Log "Waiting $CheckInterval seconds for next check..." "INFO"
        Start-Sleep -Seconds $CheckInterval
    }
} catch {
    Write-Log "Monitor loop terminated: $_" "ERROR"
    throw
} finally {
    Write-Log "=== MT5 Health Monitor Stopped ===" "INFO"
}
