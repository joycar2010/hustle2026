[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9A-Fa-f]{64}$")]
    [string]$ManifestSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9._-]{16,128}$")]
    [string]$QHMaintenanceToken
)

$ErrorActionPreference = "Stop"
$Release = "mt5-admission-snapshot-20260821.2"
$Stage = $PSScriptRoot
$AppRoot = "D:\QHMT5\runtime\releases\v1\ic\app"
$CellPath = "D:\QHCELL\cell.py"
$BackupRoot = "D:\QHMT5\backups"
$ManifestPath = Join-Path $Stage "release-manifest.json"
$Stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$Backup = Join-Path $BackupRoot ("{0}-{1}" -f $Release, $Stamp)
$ReportPath = Join-Path $Backup "deployment-report.json"
$Slots = @(
    @{ Name = "s1"; Port = 8061; ExpectedAccount = "52940784" },
    @{ Name = "s3"; Port = 8063; ExpectedAccount = "277809090" }
)
$Manifest = $null
$BackedUp = $false
$Mutated = $false

function Assert-Hash([string]$Path, [string]$Expected) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "missing file: $Path"
    }
    $Actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected.ToLowerInvariant()) {
        throw "hash mismatch: $Path"
    }
}

function Get-EnvValue([string]$Path, [string]$Name) {
    $prefix = $Name + "="
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        if ($line.StartsWith($prefix, [StringComparison]::Ordinal)) {
            return $line.Substring($prefix.Length).Trim().Trim("'", '"')
        }
    }
    return ""
}

function Set-EnvValues([string]$Path, [hashtable]$Values) {
    $lines = [Collections.Generic.List[string]]::new()
    $remaining = @{}
    foreach ($name in $Values.Keys) { $remaining[$name] = [string]$Values[$name] }
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        $separator = $line.IndexOf("=")
        $name = if ($separator -gt 0) { $line.Substring(0, $separator) } else { "" }
        if ($remaining.ContainsKey($name)) {
            $lines.Add($name + "=" + $remaining[$name])
            $remaining.Remove($name)
        } else {
            $lines.Add($line)
        }
    }
    foreach ($name in $remaining.Keys) { $lines.Add($name + "=" + $remaining[$name]) }
    $temp = $Path + "." + $Stamp + ".new"
    [IO.File]::WriteAllLines($temp, $lines, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Invoke-Bridge([hashtable]$Slot, [string]$Path, [int]$TimeoutSec = 15) {
    $envPath = "D:\QHCELL\pool\{0}\inst\.env" -f $Slot.Name
    $key = Get-EnvValue $envPath "API_KEY"
    if ([String]::IsNullOrWhiteSpace($key)) { throw "missing bridge API key for $($Slot.Name)" }
    return Invoke-RestMethod -Uri ("http://127.0.0.1:{0}{1}" -f $Slot.Port, $Path) `
        -Headers @{ "X-API-Key" = $key } -TimeoutSec $TimeoutSec
}

function Invoke-BridgeStatus([hashtable]$Slot, [string]$Path, [int]$TimeoutSec = 10) {
    $envPath = "D:\QHCELL\pool\{0}\inst\.env" -f $Slot.Name
    $key = Get-EnvValue $envPath "API_KEY"
    try {
        $response = Invoke-WebRequest -UseBasicParsing `
            -Uri ("http://127.0.0.1:{0}{1}" -f $Slot.Port, $Path) `
            -Headers @{ "X-API-Key" = $key } -TimeoutSec $TimeoutSec
        return @{ Status = [int]$response.StatusCode; Content = [string]$response.Content }
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw }
        $stream = $response.GetResponseStream()
        $reader = [IO.StreamReader]::new($stream)
        try { $content = $reader.ReadToEnd() } finally { $reader.Dispose() }
        return @{ Status = [int]$response.StatusCode; Content = $content }
    }
}

function Assert-Idle([hashtable]$Slot) {
    $health = Invoke-Bridge $Slot "/health" 10
    $queue = $health.execution_queue
    if ($health.status -ne "ok" -or $health.mt5 -ne $true -or
            $health.trade_allowed -eq $false -or $health.execution_healthy -ne $true -or
            $queue.execution_process_ready -ne $true -or $queue.coordinator_healthy -ne $true -or
            [int]$queue.pending_executions -ne 0 -or [int]$queue.queued -ne 0 -or
            [int]$queue.claimed -ne 0 -or [int]$queue.running -ne 0) {
        throw "bridge is not idle and execution-ready: $($Slot.Name)"
    }
    $positions = Invoke-Bridge $Slot "/mt5/positions?authoritative=true" 20
    if (@($positions.positions).Count -ne 0) {
        throw "bridge has open positions: $($Slot.Name)"
    }
}

function Stop-CellController {
    $pids = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq 8600 } |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($processId in $pids) {
        Stop-Process -Id $processId -Force -ErrorAction Stop
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq 8600 })
        if ($listeners.Count -eq 0) { return }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "cell controller did not stop"
}

function Start-CellController {
    try {
        Start-ScheduledTask -TaskName "QHCELL-Agent" -TaskPath "\" -ErrorAction Stop
    } catch {
        # The scheduled task can already be in a short launcher run. Health
        # polling below is the authoritative readiness check.
    }
}

function Wait-Bridge([hashtable]$Slot, [string]$BuildId, [int]$BudgetSec = 180) {
    $deadline = [DateTime]::UtcNow.AddSeconds($BudgetSec)
    $last = "unreachable"
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-Bridge $Slot "/health" 8
            $queue = $health.execution_queue
            $ok = ($health.status -eq "ok" -and $health.mt5 -eq $true -and
                $health.trade_allowed -ne $false -and $health.build_id -eq $BuildId -and
                $health.instance -eq ("qhcell-" + $Slot.Name) -and
                $health.execution_process_isolation -eq $true -and
                $health.execution_healthy -eq $true -and
                $queue.process_isolated -eq $true -and
                $queue.execution_process_ready -eq $true -and
                $queue.execution_process_alive -eq $true -and
                $queue.coordinator_healthy -eq $true -and
                $queue.native_owner_mode -eq "single_process_read_write_rpc" -and
                [int]$queue.native_owner_process_pid -eq [int]$queue.execution_process_pid -and
                [int]$queue.pending_executions -eq 0)
            if ($ok) { return $health }
            $last = "health contract not ready"
        } catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "bridge health timeout $($Slot.Name): $last"
}

function Assert-AdmissionContract([hashtable]$Slot) {
    $admission = Invoke-BridgeStatus $Slot "/mt5/positions?admission=true" 10
    if ($admission.Status -eq 200) {
        $snapshot = $admission.Content | ConvertFrom-Json
        if ($snapshot.snapshot_admission -ne $true -or
                $snapshot.snapshot_authoritative -ne $true -or
                $snapshot.snapshot_source -ne "broker") {
            throw "invalid admission snapshot contract: $($Slot.Name)"
        }
    } elseif ($admission.Status -ne 503) {
        throw "admission endpoint status $($admission.Status): $($Slot.Name)"
    }
    $conflict = Invoke-BridgeStatus $Slot "/mt5/positions?authoritative=true&admission=true" 10
    if ($conflict.Status -ne 400) {
        throw "admission conflict guard missing: $($Slot.Name)"
    }
}

function Restore-Backup {
    Copy-Item -LiteralPath (Join-Path $Backup "main.py.before") -Destination (Join-Path $AppRoot "main.py") -Force
    Copy-Item -LiteralPath (Join-Path $Backup "runtime.py.before") -Destination (Join-Path $AppRoot "runtime.py") -Force
    Copy-Item -LiteralPath (Join-Path $Backup "cell.py.before") -Destination $CellPath -Force
    foreach ($slot in $Slots) {
        $live = "D:\QHCELL\pool\{0}\inst\.env" -f $slot.Name
        Copy-Item -LiteralPath (Join-Path $Backup ($slot.Name + ".env.before")) -Destination $live -Force
    }
    Assert-Hash (Join-Path $AppRoot "main.py") $Manifest.production_before.main_py
    Assert-Hash (Join-Path $AppRoot "runtime.py") $Manifest.production_before.runtime_py
    Assert-Hash $CellPath $Manifest.production_before.cell_py
    Stop-CellController
    Start-CellController
    foreach ($slot in $Slots) { $null = Wait-Bridge $slot $Manifest.production_before.build_id 180 }
}

try {
    Assert-Hash $ManifestPath $ManifestSha256
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ($Manifest.release -ne $Release -or $Manifest.deployment_status -ne "sealed") {
        throw "release manifest identity mismatch"
    }
    if ($Manifest.requires_qh_maintenance -ne $true -or [String]::IsNullOrWhiteSpace($QHMaintenanceToken)) {
        throw "QH maintenance ownership is required"
    }
    Assert-Hash (Join-Path $Stage "app\main.py") $Manifest.candidate.main_py
    Assert-Hash (Join-Path $Stage "app\runtime.py") $Manifest.candidate.runtime_py
    Assert-Hash (Join-Path $Stage "cell.py") $Manifest.candidate.cell_py
    Assert-Hash $PSCommandPath $Manifest.candidate.deploy_ps1
    $candidateFiles = @(
        (Join-Path $Stage "app\main.py"),
        (Join-Path $Stage "app\runtime.py"),
        (Join-Path $Stage "cell.py")
    )
    & "D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe" -m py_compile @candidateFiles
    if ($LASTEXITCODE -ne 0) { throw "candidate Python compile failed" }
    Assert-Hash (Join-Path $AppRoot "main.py") $Manifest.production_before.main_py
    Assert-Hash (Join-Path $AppRoot "runtime.py") $Manifest.production_before.runtime_py
    Assert-Hash $CellPath $Manifest.production_before.cell_py
    foreach ($slot in $Slots) {
        $health = Invoke-Bridge $slot "/health" 10
        if ($health.build_id -ne $Manifest.production_before.build_id) {
            throw "production bridge build drift: $($slot.Name)"
        }
        Assert-Idle $slot
    }

    New-Item -ItemType Directory -Path $Backup -ErrorAction Stop | Out-Null
    Copy-Item -LiteralPath (Join-Path $AppRoot "main.py") -Destination (Join-Path $Backup "main.py.before")
    Copy-Item -LiteralPath (Join-Path $AppRoot "runtime.py") -Destination (Join-Path $Backup "runtime.py.before")
    Copy-Item -LiteralPath $CellPath -Destination (Join-Path $Backup "cell.py.before")
    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $Backup "release-manifest.json")
    foreach ($slot in $Slots) {
        $live = "D:\QHCELL\pool\{0}\inst\.env" -f $slot.Name
        Copy-Item -LiteralPath $live -Destination (Join-Path $Backup ($slot.Name + ".env.before"))
    }
    $BackedUp = $true

    $newMain = Join-Path $AppRoot ("main.py." + $Stamp + ".new")
    $newRuntime = Join-Path $AppRoot ("runtime.py." + $Stamp + ".new")
    $newCell = $CellPath + "." + $Stamp + ".new"
    Copy-Item -LiteralPath (Join-Path $Stage "app\main.py") -Destination $newMain -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $Stage "app\runtime.py") -Destination $newRuntime -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $Stage "cell.py") -Destination $newCell -ErrorAction Stop
    Assert-Hash $newMain $Manifest.candidate.main_py
    Assert-Hash $newRuntime $Manifest.candidate.runtime_py
    Assert-Hash $newCell $Manifest.candidate.cell_py
    Move-Item -LiteralPath $newMain -Destination (Join-Path $AppRoot "main.py") -Force
    Move-Item -LiteralPath $newRuntime -Destination (Join-Path $AppRoot "runtime.py") -Force
    Move-Item -LiteralPath $newCell -Destination $CellPath -Force
    foreach ($slot in $Slots) {
        $live = "D:\QHCELL\pool\{0}\inst\.env" -f $slot.Name
        Set-EnvValues $live @{
            "MT5_BRIDGE_BUILD_ID" = $Release
            "POSITIONS_ADMISSION_MAX_AGE_MS" = "200"
        }
    }
    Assert-Hash (Join-Path $AppRoot "main.py") $Manifest.candidate.main_py
    Assert-Hash (Join-Path $AppRoot "runtime.py") $Manifest.candidate.runtime_py
    Assert-Hash $CellPath $Manifest.candidate.cell_py
    $Mutated = $true

    Stop-CellController
    Start-CellController
    foreach ($slot in $Slots) {
        $null = Wait-Bridge $slot $Release 180
        Assert-Idle $slot
        Assert-AdmissionContract $slot
    }
    @{
        ok = $true
        release = $Release
        backup = $Backup
        deployed_at = [DateTime]::UtcNow.ToString("o")
        qh_maintenance_owned = $true
        real_orders_sent = $false
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    Get-Content -LiteralPath $ReportPath -Raw
} catch {
    $failure = $_.Exception.Message
    $rolledBack = $false
    if ($Mutated -and $BackedUp) {
        try {
            Restore-Backup
            $rolledBack = $true
        } catch {
            $failure += "; rollback=" + $_.Exception.Message
        }
    }
    if ($BackedUp) {
        @{
            ok = $false
            release = $Release
            backup = $Backup
            error = $failure
            rolled_back = $rolledBack
            real_orders_sent = $false
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    }
    throw $failure
}
