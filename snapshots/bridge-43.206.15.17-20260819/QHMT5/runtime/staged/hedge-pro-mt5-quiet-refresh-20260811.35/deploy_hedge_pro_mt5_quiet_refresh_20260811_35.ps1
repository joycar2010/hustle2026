param(
    [string]$Stage = 'D:\QHMT5\runtime\staged\hedge-pro-mt5-quiet-refresh-20260811.35',
    [switch]$Execute,
    [switch]$QHMaintenanceHeld
)

$ErrorActionPreference = 'Stop'
if (-not $Execute) {
    throw 'Refusing to deploy without the explicit -Execute switch'
}
if (-not $QHMaintenanceHeld) {
    throw 'Refusing to deploy unless QH trading maintenance is already held'
}

$Release = 'hedge-pro-mt5-quiet-refresh-20260811.35'
$LiveApp = 'D:\QHMT5\runtime\releases\v1\ic\app'
$Python = 'D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe'
$BackupRoot = 'D:\QHMT5\backups'
$CellTask = 'QHCELL-Agent'
$CellPort = 8600
$PreflightPath = 'D:\preflight_hedge_pro_mt5_v3.py'
$ExpectedPreflight = 'B426C05F14778DF67EF060319745F622B00C25001C58EAC4D212BA27EB93ED01'
$ExpectedCandidateMain = '75796B08663CC00DCA274A7B50D85781D205B9A3BD939A5CBB1FCA81673E321F'
$ExpectedCandidateRuntime = '5B6B87FE0F37D5FAA65800D4645B9F5A25877B6471B0C030BD39D0D005B91356'
$ExpectedProductionMain = '440C09D7758F3BA4F118F85633CAE4D6ED109F0E735CEB074A802EF57D7B5078'
$ExpectedProductionRuntime = '5B6B87FE0F37D5FAA65800D4645B9F5A25877B6471B0C030BD39D0D005B91356'
$ApiKeyLine = Get-Content -LiteralPath 'D:\QHCELL\cell.env' |
    Where-Object { $_ -match '^API_KEY=' } | Select-Object -First 1
if (-not $ApiKeyLine) { throw 'QHCELL API key is missing' }
$Headers = @{'X-API-Key' = $ApiKeyLine.Substring('API_KEY='.Length).Trim()}
$Legs = @(
    [pscustomobject]@{ slot='s3'; port=8063; role='hedge'; instance='D:\QHCELL\pool\s3\inst' },
    [pscustomobject]@{ slot='s1'; port=8061; role='main';  instance='D:\QHCELL\pool\s1\inst' }
)

$StageMain = Join-Path $Stage 'app\main.py'
$StageRuntime = Join-Path $Stage 'app\runtime.py'
$Backup = $null
$BackupReady = $false
$Installed = $false
$WatchdogTouched = $false
$WatchdogWasEnabled = $false

function Get-Hash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Assert-Hash([string]$Path, [string]$Expected, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    $actual = Get-Hash $Path
    if ($actual -ne $Expected.ToUpperInvariant()) {
        throw "$Label hash mismatch: expected $Expected actual $actual"
    }
}

function Get-Listener([int]$Port) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1) {
        throw "expected one listener on port $Port, found $($listeners.Count)"
    }
    return $listeners[0]
}

function Get-BridgeProcess([int]$Port) {
    $listener = Get-Listener $Port
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f [int]$listener.OwningProcess)
    if (-not $process -or $process.Name -ne 'python.exe' -or
        $process.CommandLine -notlike '*-m uvicorn app.main:app*' -or
        $process.CommandLine -notlike ("*--port {0}*" -f $Port)) {
        throw "refusing unexpected process on port $Port"
    }
    return [ordered]@{ listener=$listener; process=$process }
}

function Get-Terminal([string]$Slot) {
    $terminals = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'terminal64.exe' -and $_.CommandLine -like ("*pool\{0}\terminal*" -f $Slot)
    })
    if ($terminals.Count -ne 1) {
        throw "expected one MT5 terminal for $Slot, found $($terminals.Count)"
    }
    return $terminals[0]
}

function Get-CellAgentPids {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -like '*-m uvicorn cell:app*'
    } | ForEach-Object { [int]$_.ProcessId })
}

function Invoke-Json([string]$Uri, [bool]$Auth = $false, [int]$TimeoutSec = 15) {
    if ($Auth) {
        return Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec
    }
    return Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSec
}

function Get-PositionSnapshot([int]$Port, [bool]$Authoritative = $false) {
    $query = if ($Authoritative) { '?authoritative=true' } else { '' }
    $payload = Invoke-Json ("http://127.0.0.1:{0}/mt5/positions{1}" -f $Port, $query) $true 30
    $lines = foreach ($position in @($payload.positions | Sort-Object ticket)) {
        $volume = ([double]$position.volume).ToString('R', [Globalization.CultureInfo]::InvariantCulture)
        '{0}|{1}|{2}|{3}' -f $position.ticket, $position.symbol, $position.type, $volume
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $signature = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '')
    } finally {
        $sha.Dispose()
    }
    $age = if ($null -eq $payload.snapshot_age_ms) { [double]::PositiveInfinity } else { [double]$payload.snapshot_age_ms }
    if (@($payload.positions).Count -ne 0) {
        throw "deployment requires empty MT5 positions on port $Port"
    }
    if ($payload.snapshot_source -ne 'broker' -or [bool]$payload.snapshot_stale -or $age -lt 0 -or $age -gt 5000) {
        throw "position snapshot is not fresh broker truth on port $Port"
    }
    if ($Authoritative -and -not [bool]$payload.snapshot_authoritative) {
        throw "position snapshot is not authoritative on port $Port"
    }
    return [ordered]@{
        count = @($payload.positions).Count
        signature = $signature
        snapshot_boot = [long]$payload.snapshot_boot
        snapshot_seq = [long]$payload.snapshot_seq
        snapshot_ts_ms = [long]$payload.snapshot_ts_ms
        snapshot_age_ms = $age
        snapshot_source = [string]$payload.snapshot_source
        snapshot_stale = [bool]$payload.snapshot_stale
        snapshot_authoritative = [bool]$payload.snapshot_authoritative
    }
}

function Get-HealthSnapshot([int]$Port) {
    $health = Invoke-Json ("http://127.0.0.1:{0}/health" -f $Port) $false 15
    if ($health.status -ne 'ok' -or $health.mt5 -ne $true -or $health.trade_allowed -eq $false) {
        throw "bridge $Port is not trade-ready"
    }
    if ([int]$health.execution_queue.pending_executions -ne 0 -or
        [int]$health.execution_queue.queued -ne 0 -or [bool]$health.execution_queue.running -or
        [int]$health.mt5_api_queue.queued -ne 0 -or [bool]$health.mt5_api_queue.running -or
        $health.mt5_api_queue.single_thread -ne $true -or
        [int]$health.mt5_trade_gate.pending_trades -ne 0 -or
        [int]$health.mt5_trade_gate.active_reads -ne 0) {
        throw "bridge $Port has active work or an invalid native queue state"
    }
    return [ordered]@{
        status=[string]$health.status; mt5=[bool]$health.mt5; trade_allowed=[bool]$health.trade_allowed
        execution_pending=[int]$health.execution_queue.pending_executions
        execution_queued=[int]$health.execution_queue.queued
        native_queued=[int]$health.mt5_api_queue.queued
        native_running=[bool]$health.mt5_api_queue.running
        single_thread=[bool]$health.mt5_api_queue.single_thread
        pending_trades=[int]$health.mt5_trade_gate.pending_trades
        active_reads=[int]$health.mt5_trade_gate.active_reads
    }
}

function Get-Snapshot([bool]$RequireAuthoritative = $false, [bool]$RequireCandidate = $false) {
    $rows = foreach ($leg in $Legs) {
        $bridge = Get-BridgeProcess $leg.port
        $terminal = Get-Terminal $leg.slot
        $health = Get-HealthSnapshot $leg.port
        $openapi = Invoke-Json ("http://127.0.0.1:{0}/openapi.json" -f $leg.port) $false 15
        $positions = Get-PositionSnapshot $leg.port $RequireAuthoritative
        $mainHash = Get-Hash (Join-Path $LiveApp 'main.py')
        $runtimeHash = Get-Hash (Join-Path $LiveApp 'runtime.py')
        if ($RequireCandidate -and ($mainHash -ne $ExpectedCandidateMain -or $runtimeHash -ne $ExpectedCandidateRuntime)) {
            throw "live bridge source hash mismatch on port $($leg.port)"
        }
        if ($RequireAuthoritative) {
            $parameters = @($openapi.paths.'/mt5/positions'.get.parameters | Where-Object { $_.name -eq 'authoritative' })
            if ($parameters.Count -ne 1 -or $parameters[0].schema.type -ne 'boolean') {
                throw "authoritative positions query is not served on port $($leg.port)"
            }
        }
        [ordered]@{
            role=$leg.role;slot=$leg.slot;port=$leg.port
            bridge_pid=[int]$bridge.process.ProcessId
            terminal_pid=[int]$terminal.ProcessId
            terminal_created_utc=([datetime]$terminal.CreationDate).ToUniversalTime().ToString('o')
            health=$health;positions=$positions;openapi_version=[string]$openapi.info.version
            main_sha256=$mainHash;runtime_sha256=$runtimeHash
        }
    }
    return @($rows)
}

function Assert-SamePositionAndTerminal([object[]]$Before, [object[]]$After) {
    foreach ($old in $Before) {
        $new = $After | Where-Object { $_.role -eq $old.role } | Select-Object -First 1
        if (-not $new -or $new.terminal_pid -ne $old.terminal_pid -or
            $new.positions.signature -ne $old.positions.signature -or
            $new.positions.count -ne $old.positions.count) {
            throw "terminal PID or empty-position signature changed for $($old.role)"
        }
    }
}

function Wait-Bridge([int]$Port, [int]$Seconds = 150) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $health = Get-HealthSnapshot $Port
            return $health
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "bridge $Port did not become healthy within ${Seconds}s"
}

function Restart-BridgeOnly($Leg) {
    $bridge = Get-BridgeProcess $Leg.port
    Stop-Process -Id ([int]$bridge.process.ProcessId) -Force
    $deadline = (Get-Date).AddSeconds(15)
    do {
        if (-not (Get-NetTCPConnection -LocalPort $Leg.port -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if (Get-NetTCPConnection -LocalPort $Leg.port -State Listen -ErrorAction SilentlyContinue) {
        throw "bridge $($Leg.port) did not stop"
    }
    $logs = Join-Path $Leg.instance 'logs'
    Start-Process -FilePath $Python -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port',([string]$Leg.port) `
        -WorkingDirectory $Leg.instance -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'bridge.out.log') `
        -RedirectStandardError (Join-Path $logs 'bridge.err.log') | Out-Null
    Wait-Bridge $Leg.port | Out-Null
}

function Pause-Watchdog {
    $script:WatchdogTouched = $true
    $task = Get-ScheduledTask -TaskName $CellTask -ErrorAction Stop
    $script:WatchdogWasEnabled = $task.Settings.Enabled -ne $false
    if ($script:WatchdogWasEnabled) { Disable-ScheduledTask -TaskName $CellTask | Out-Null }
    foreach ($cellPid in @(Get-CellAgentPids)) { Stop-Process -Id $cellPid -Force }
    $deadline = (Get-Date).AddSeconds(20)
    do {
        $cellPids = @(Get-CellAgentPids)
        $cellListeners = @(Get-NetTCPConnection -LocalPort $CellPort -State Listen -ErrorAction SilentlyContinue)
        if ($cellPids.Count -eq 0 -and $cellListeners.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw 'QHCELL-Agent did not stop cleanly; no bridge deployment performed'
}

function Wait-CellAdopted([int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $health = Invoke-Json ("http://127.0.0.1:{0}/cell/health" -f $CellPort) $false 5
            if ($health.ok -eq $true -and @(Get-CellAgentPids).Count -gt 0) { return }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw 'QHCELL-Agent did not return after watchdog recovery'
}

function Restore-Watchdog {
    if (-not $WatchdogWasEnabled) { $script:WatchdogTouched = $false; return }
    Enable-ScheduledTask -TaskName $CellTask | Out-Null
    Start-ScheduledTask -TaskName $CellTask
    Wait-CellAdopted
    $script:WatchdogTouched = $false
}

Assert-Hash $StageMain $ExpectedCandidateMain 'staged main.py'
Assert-Hash $StageRuntime $ExpectedCandidateRuntime 'staged runtime.py'
Assert-Hash (Join-Path $LiveApp 'main.py') $ExpectedProductionMain 'live main.py predecessor'
Assert-Hash (Join-Path $LiveApp 'runtime.py') $ExpectedProductionRuntime 'live runtime.py predecessor'
Assert-Hash $PreflightPath $ExpectedPreflight 'remote preflight diagnostic'

$preflightPython = & $Python $PreflightPath
if ($LASTEXITCODE -ne 0) { throw 'recent in-flight MT5 execution detected' }

$Before = Get-Snapshot $false $false
$Backup = Join-Path $BackupRoot ("{0}-{1}" -f $Release, (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path $Backup | Out-Null
Copy-Item -LiteralPath (Join-Path $LiveApp 'main.py') -Destination (Join-Path $Backup 'main.py.before')
Copy-Item -LiteralPath (Join-Path $LiveApp 'runtime.py') -Destination (Join-Path $Backup 'runtime.py.before')
Copy-Item -LiteralPath (Join-Path $Stage 'release-manifest.json') -Destination (Join-Path $Backup 'release-manifest.json')
Assert-Hash (Join-Path $Backup 'main.py.before') $ExpectedProductionMain 'backup main.py'
Assert-Hash (Join-Path $Backup 'runtime.py.before') $ExpectedProductionRuntime 'backup runtime.py'
$BackupReady = $true

try {
    Pause-Watchdog
    Assert-SamePositionAndTerminal $Before (Get-Snapshot $false $false)

    Copy-Item -LiteralPath $StageRuntime -Destination (Join-Path $LiveApp 'runtime.py') -Force
    Copy-Item -LiteralPath $StageMain -Destination (Join-Path $LiveApp 'main.py') -Force
    $Installed = $true

    foreach ($leg in $Legs) {
        Restart-BridgeOnly $leg
        Assert-SamePositionAndTerminal $Before (Get-Snapshot $false $false)
    }

    $Candidate = Get-Snapshot $true $true
    Assert-SamePositionAndTerminal $Before $Candidate
    Restore-Watchdog
    $Final = Get-Snapshot $true $true
    Assert-SamePositionAndTerminal $Before $Final

    $report = [ordered]@{
        ok=$true;release=$Release;backup=$Backup
        candidate_main_sha256=$ExpectedCandidateMain
        candidate_runtime_sha256=$ExpectedCandidateRuntime
        watchdog_restored=$true;terminal_pids_preserved=$true
        preflight=$preflightPython;before=$Before;after=$Final
    } | ConvertTo-Json -Depth 16 -Compress
    $report | Set-Content -LiteralPath (Join-Path $Backup 'deployment-result.json') -Encoding UTF8
    $report
} catch {
    $failure = $_.Exception.Message
    $rollbackError = $null
    if ($Installed -and $BackupReady) {
        try {
            Copy-Item -LiteralPath (Join-Path $Backup 'runtime.py.before') -Destination (Join-Path $LiveApp 'runtime.py') -Force
            Copy-Item -LiteralPath (Join-Path $Backup 'main.py.before') -Destination (Join-Path $LiveApp 'main.py') -Force
            foreach ($leg in $Legs) { Restart-BridgeOnly $leg }
            $rolledBack = Get-Snapshot $false $false
            Assert-SamePositionAndTerminal $Before $rolledBack
            Assert-Hash (Join-Path $LiveApp 'main.py') $ExpectedProductionMain 'rolled-back main.py'
            Assert-Hash (Join-Path $LiveApp 'runtime.py') $ExpectedProductionRuntime 'rolled-back runtime.py'
        } catch {
            $rollbackError = $_.Exception.Message
        }
    }
    if ($WatchdogTouched) {
        try { Restore-Watchdog } catch {
            if ($rollbackError) { $rollbackError = "$rollbackError; watchdog restore: $($_.Exception.Message)" }
            else { $rollbackError = "watchdog restore: $($_.Exception.Message)" }
        }
    }
    if ($rollbackError) {
        throw "deployment failed: $failure; rollback/watchdog recovery failed: $rollbackError; maintenance must remain held"
    }
    throw "deployment failed and bridge rollback was verified: $failure"
}
