[CmdletBinding()]
param(
    [int]$LogLimitMB = 100,
    [int]$FailureThreshold = 2,
    [int]$RestartCooldownSec = 300,
    [int]$MaxArchives = 5
)

$ErrorActionPreference = 'Stop'
$baseDir = 'D:\MT4LAB\agent'
$statePath = Join-Path $baseDir 'watchdog-state.json'
$watchdogLog = Join-Path $baseDir 'watchdog.log'
$apiKey = $null
try {
    $keyLine = Get-Content -LiteralPath (Join-Path $baseDir 'run_agent.ps1') |
        Where-Object { $_ -match '^\$env:API_KEY\s*=' } | Select-Object -First 1
    if ($keyLine) { $apiKey = ($keyLine -split "'")[1] }
} catch {}
$instances = @(
    [pscustomobject]@{ Name = 'ic'; Task = 'MT4LAB-Agent-ic'; Port = 8041; Log = (Join-Path $baseDir 'logs\ic.log') },
    [pscustomobject]@{ Name = 'exness'; Task = 'MT4LAB-Agent-exness'; Port = 8042; Log = (Join-Path $baseDir 'logs\exness.log') }
)

$mutex = New-Object System.Threading.Mutex($false, 'Global\QH-MT4-Agent-Watchdog')
if (-not $mutex.WaitOne(0)) { exit 0 }

function Write-WatchdogLog([string]$Message) {
    if (Test-Path -LiteralPath $watchdogLog) {
        $current = Get-Item -LiteralPath $watchdogLog
        if ($current.Length -gt 5MB) {
            Move-Item -LiteralPath $watchdogLog -Destination ($watchdogLog + '.previous') -Force
        }
    }
    Add-Content -LiteralPath $watchdogLog -Value ((Get-Date).ToUniversalTime().ToString('o') + ' ' + $Message)
}

function Get-AgentHealth([int]$Port) {
    try {
        $result = Invoke-RestMethod -Uri ("http://127.0.0.1:$Port/health") -TimeoutSec 3
        $connected = $null
        if ($apiKey) {
            try {
                $status = Invoke-RestMethod -Uri ("http://127.0.0.1:$Port/mt5/connection/status") `
                    -Headers @{'X-API-Key'=$apiKey} -TimeoutSec 3
                $connected = [bool]$status.connected
            } catch {}
        }
        return [pscustomobject]@{ HttpUp = $true; Connected = $connected; Detail = $result }
    } catch {
        return [pscustomobject]@{ HttpUp = $false; Connected = $false; Detail = $_.Exception.Message }
    }
}

function Stop-Agent([pscustomobject]$Instance) {
    Stop-ScheduledTask -TaskName $Instance.Task -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(12)
    do {
        $listener = Get-NetTCPConnection -LocalPort $Instance.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $listener) { return }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)

    $listener = Get-NetTCPConnection -LocalPort $Instance.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener -and $listener.OwningProcess) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Restart-Agent([pscustomobject]$Instance, [bool]$RotateLog, [string]$Reason) {
    Write-WatchdogLog ("restart_begin instance={0} reason={1}" -f $Instance.Name, $Reason)
    Stop-Agent $Instance
    if ($RotateLog -and (Test-Path -LiteralPath $Instance.Log)) {
        $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
        $archive = $Instance.Log + '.' + $stamp
        Move-Item -LiteralPath $Instance.Log -Destination $archive -Force
        Write-WatchdogLog ("log_rotated instance={0} archive={1}" -f $Instance.Name, $archive)
    }
    Start-ScheduledTask -TaskName $Instance.Task
    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        $health = Get-AgentHealth $Instance.Port
        if ($health.HttpUp) {
            Write-WatchdogLog ("restart_ok instance={0} connected={1}" -f $Instance.Name, $health.Connected)
            return $true
        }
    } while ((Get-Date) -lt $deadline)
    Write-WatchdogLog ("restart_timeout instance={0}" -f $Instance.Name)
    return $false
}

try {
    $state = @{}
    if (Test-Path -LiteralPath $statePath) {
        try {
            $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            foreach ($property in $saved.PSObject.Properties) { $state[$property.Name] = $property.Value }
        } catch {
            Write-WatchdogLog 'state_invalid reset=true'
        }
    }

    foreach ($instance in $instances) {
        if (-not $state.ContainsKey($instance.Name)) {
            $state[$instance.Name] = [pscustomobject]@{ Failures = 0; LastRestartEpoch = 0; Connected = $null }
        }
        $entry = $state[$instance.Name]
        $health = Get-AgentHealth $instance.Port
        $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $rotate = (Test-Path -LiteralPath $instance.Log) -and ((Get-Item -LiteralPath $instance.Log).Length -ge ($LogLimitMB * 1MB))

        if ($rotate) {
            if (Restart-Agent $instance $true 'log_limit') {
                $entry.LastRestartEpoch = $nowEpoch
                $entry.Failures = 0
            }
        } elseif (-not $health.HttpUp) {
            $entry.Failures = [int]$entry.Failures + 1
            Write-WatchdogLog ("health_fail instance={0} failures={1} detail={2}" -f $instance.Name, $entry.Failures, $health.Detail)
            if ($entry.Failures -ge $FailureThreshold -and ($nowEpoch - [long]$entry.LastRestartEpoch) -ge $RestartCooldownSec) {
                if (Restart-Agent $instance $false 'http_unreachable') {
                    $entry.LastRestartEpoch = $nowEpoch
                    $entry.Failures = 0
                }
            }
        } else {
            $entry.Failures = 0
            if ($null -ne $health.Connected -and $entry.Connected -ne $health.Connected) {
                Write-WatchdogLog ("health_state instance={0} connected={1}" -f $instance.Name, $health.Connected)
            }
            if ($null -ne $health.Connected) { $entry.Connected = $health.Connected }
        }

        $archives = @(Get-ChildItem -LiteralPath (Split-Path $instance.Log) -Filter ((Split-Path $instance.Log -Leaf) + '.*') -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending)
        if ($archives.Count -gt $MaxArchives) {
            $archives | Select-Object -Skip $MaxArchives | Remove-Item -Force
        }
        $state[$instance.Name] = $entry
    }

    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
} catch {
    Write-WatchdogLog ("watchdog_error type={0} detail={1}" -f $_.Exception.GetType().Name, $_.Exception.Message)
    exit 1
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
