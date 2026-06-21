# MT5 Infra Healthcheck — runs every 30s via Task Scheduler.
# Probes Agent /health and each bridge's HTTP liveness.
# On 2 consecutive failures, writes an alert file that healthcheck_alert.ps1 consumes.

$ErrorActionPreference = 'Continue'
$logDir   = 'C:\MT5Agent\logs'
$logFile  = Join-Path $logDir 'healthcheck.log'
$stateFile = Join-Path $logDir 'healthcheck.state.json'
$alertFile = Join-Path $logDir 'healthcheck.alert.json'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$AGENT_URL   = 'http://127.0.0.1:8765/health'
$BRIDGES = @(
    @{ svc='hustle-mt5-mt5-by01';  port=8001 },
    @{ svc='hustle-mt5-mt5-by02';  port=8002 },
    @{ svc='hustle-mt5-mt5-by03';  port=8003 },
    @{ svc='hustle-mt5-mt5-ic01';  port=8021 },
    @{ svc='hustle-mt5-mt5-ic02';  port=8022 },
    @{ svc='hustle-mt5-mt5-bysys'; port=8886 },
    @{ svc='hustle-mt5-mt5-icsys'; port=8888 }
)
$FAIL_THRESHOLD = 2   # consecutive failures before alert
$LOG_ROTATE_KB  = 2048

function Log([string]$level, [string]$msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value "$ts [$level] $msg" -Encoding utf8
}

# Rotate log if oversize
try {
    if ((Test-Path $logFile) -and ((Get-Item $logFile).Length / 1KB -gt $LOG_ROTATE_KB)) {
        Move-Item -Force $logFile "$logFile.1"
    }
} catch {}

# Load previous state
$state = @{ agent_fails = 0; bridge_fails = @{} }
if (Test-Path $stateFile) {
    try {
        $loaded = Get-Content $stateFile -Raw | ConvertFrom-Json
        if ($loaded.agent_fails) { $state.agent_fails = [int]$loaded.agent_fails }
        if ($loaded.bridge_fails) {
            $loaded.bridge_fails.PSObject.Properties | ForEach-Object { $state.bridge_fails[$_.Name] = [int]$_.Value }
        }
    } catch {}
}
foreach ($b in $BRIDGES) { if (-not $state.bridge_fails.ContainsKey($b.svc)) { $state.bridge_fails[$b.svc] = 0 } }

$now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$failures = @()  # [{target, reason, fails}]

# 1. Agent /health
$agentHealthy = $false
$agentData = $null
try {
    $agentData = Invoke-RestMethod -Uri $AGENT_URL -TimeoutSec 3
    if ($agentData -and $agentData.status -eq 'ok') { $agentHealthy = $true }
    elseif ($agentData -and $agentData.status) {
        Log 'WARN' "agent status=$($agentData.status) alive=$($agentData.bridges.alive)/$($agentData.bridges.total)"
    }
} catch {
    Log 'ERROR' "agent /health unreachable: $($_.Exception.Message)"
}
if ($agentHealthy) {
    $state.agent_fails = 0
} else {
    $state.agent_fails += 1
    if ($state.agent_fails -ge $FAIL_THRESHOLD) {
        $failures += @{ target='MT5WindowsAgent'; reason='Agent /health unreachable or degraded'; fails=$state.agent_fails }
    }
}

# 2. Each bridge HTTP probe (expects 404 on /, or any 2xx/4xx — means socket alive)
foreach ($b in $BRIDGES) {
    $healthy = $false
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:$($b.port)/" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        $healthy = $true
    } catch [System.Net.WebException] {
        # HTTP error means port is alive but path not defined — that's OK
        if ($_.Exception.Response) { $healthy = $true }
        else { Log 'ERROR' "bridge $($b.svc) port $($b.port) unreachable: $($_.Exception.Message)" }
    } catch {
        Log 'ERROR' "bridge $($b.svc) port $($b.port) err: $($_.Exception.Message)"
    }
    if ($healthy) {
        $state.bridge_fails[$b.svc] = 0
    } else {
        $state.bridge_fails[$b.svc] += 1
        if ($state.bridge_fails[$b.svc] -ge $FAIL_THRESHOLD) {
            $failures += @{ target=$b.svc; reason="bridge port $($b.port) unreachable"; fails=$state.bridge_fails[$b.svc] }
        }
    }
}

# 3. Persist state
try {
    $state | ConvertTo-Json -Depth 4 | Set-Content -Path $stateFile -Encoding utf8
} catch { Log 'ERROR' "state persist failed: $_" }

# 4. Emit alert file when there are new crossings
if ($failures.Count -gt 0) {
    $alert = @{
        timestamp = $now
        host      = $env:COMPUTERNAME
        failures  = $failures
    }
    try {
        $alert | ConvertTo-Json -Depth 4 | Set-Content -Path $alertFile -Encoding utf8
        Log 'ALERT' ("failures=" + (($failures | ForEach-Object { $_.target }) -join ','))
    } catch { Log 'ERROR' "alert write failed: $_" }
    # Trigger alert sender (non-blocking)
    try {
        Start-Process -WindowStyle Hidden -FilePath 'powershell.exe' `
            -ArgumentList '-ExecutionPolicy','Bypass','-NonInteractive','-File','C:\MT5Agent\healthcheck_alert.ps1'
    } catch { Log 'ERROR' "alert dispatch failed: $_" }
} else {
    # All healthy — clear alert file if it exists (auto-recover signal)
    if (Test-Path $alertFile) {
        Remove-Item $alertFile -Force -ErrorAction SilentlyContinue
        Log 'INFO' 'all healthy — cleared alert'
    } else {
        Log 'INFO' "healthy agent=$($agentData.bridges.alive)/$($agentData.bridges.total)"
    }
    # Clear dispatch dedupe state so the next failure re-alerts
    $dispatched = 'C:\MT5Agent\logs\healthcheck.alert.dispatched'
    if (Test-Path $dispatched) { Remove-Item $dispatched -Force -ErrorAction SilentlyContinue }
}
