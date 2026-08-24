param(
    [string]$Stage = "D:\QHMT5\deploy\mt5-process-admission-20260817.1"
)

$ErrorActionPreference = "Stop"
$Release = "mt5-process-admission-20260817.1"
$AppRoot = "D:\QHMT5\runtime\releases\v1\ic\app"
$CellRoot = "D:\QHCELL"
$ExecutionRoot = Join-Path $CellRoot "execution"
$ExecutionLockRoot = Join-Path $ExecutionRoot "locks"
$Python = "D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe"
$Expected = @{
    "main.py" = "63d82f29c9cd87e43add022f1ed08a0951535c0736569bfde0f2757cf0e6ecdf"
    "runtime.py" = "77ee01c39d026a030bff6e0c6a2c9495577f4bdc1e105691b7826d013766f443"
    "cell.py" = "fd315eed24aa2024c879163eff4b12bc936f246dc88f68b20404361f74ccd902"
}
$Instances = @(
    @{ Name = "s1"; Port = 8061; Root = "D:\QHCELL\pool\s1\inst" },
    @{ Name = "s3"; Port = 8063; Root = "D:\QHCELL\pool\s3\inst" }
)
$Stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$Backup = "D:\QHMT5\backups\$Release-$Stamp"
$ReportPath = Join-Path $Backup "deployment-report.json"
$RestoreReady = $false

function Assert-FileHash([string]$Path, [string]$ExpectedHash) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "missing file: $Path"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedHash.ToLowerInvariant()) {
        throw "hash mismatch: $Path expected=$ExpectedHash actual=$actual"
    }
}

function Get-EnvValue([string]$Path, [string]$Name) {
    $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match "^$([Regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) { return "" }
    return $line.Substring($Name.Length + 1).Trim().Trim("'", '"')
}

function Set-EnvValue([string]$Path, [string]$Name, [string]$Value) {
    $lines = [Collections.Generic.List[string]]::new()
    $found = $false
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        if ($line -match "^$([Regex]::Escape($Name))=") {
            $lines.Add("$Name=$Value")
            $found = $true
        } else {
            $lines.Add($line)
        }
    }
    if (-not $found) { $lines.Add("$Name=$Value") }
    $temp = "$Path.$Release.tmp"
    [IO.File]::WriteAllLines($temp, $lines, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Get-ExecutionSettings([hashtable]$Instance) {
    $envPath = Join-Path $Instance.Root ".env"
    $login = Get-EnvValue $envPath "MT5_LOGIN"
    $server = (Get-EnvValue $envPath "MT5_SERVER").Trim().ToLowerInvariant()
    if (-not $login -or -not $server) {
        throw "missing MT5 account identity: $($Instance.Name)"
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes("$server|$login")
        $fenceKey = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
    $configured = Get-EnvValue $envPath "IDEMPOTENCY_DB"
    $sourceDb = if ($configured) { $configured } else { Join-Path $Instance.Root "idempotency.db" }
    return @{
        FenceKey = $fenceKey
        SourceDb = $sourceDb
        TargetDb = Join-Path $ExecutionRoot ($fenceKey + ".db")
    }
}

function Copy-DurableDatabase([string]$SourceDb, [string]$TargetDb, [string]$BackupPrefix) {
    New-Item -ItemType Directory -Force -Path $ExecutionRoot, $ExecutionLockRoot | Out-Null
    if (-not (Test-Path -LiteralPath $SourceDb -PathType Leaf)) {
        throw "source durable database is missing: $SourceDb"
    }
    $samePath = [String]::Equals(
        [IO.Path]::GetFullPath($SourceDb), [IO.Path]::GetFullPath($TargetDb),
        [StringComparison]::OrdinalIgnoreCase
    )
    $suffixes = @("", "-wal", "-shm")
    $sources = @()
    foreach ($suffix in $suffixes) {
        $source = $SourceDb + $suffix
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination ($BackupPrefix + $suffix) -Force
            $sources += @{ Suffix = $suffix; Path = $source }
        }
    }
    if ($samePath) { return }

    # A WAL database is one durable unit. Check every possible destination
    # before creating any of them, then stage all present source files under
    # unique names. A collision or copy/hash failure therefore cannot leave a
    # new main DB paired with an older WAL/SHM file.
    foreach ($suffix in $suffixes) {
        $target = $TargetDb + $suffix
        if (Test-Path -LiteralPath $target) {
            throw "target durable database already exists: $target"
        }
    }
    $staged = @()
    $installed = @()
    try {
        foreach ($item in $sources) {
            $target = $TargetDb + $item.Suffix
            $temporary = "$target.migrate-$Release-$Stamp"
            if (Test-Path -LiteralPath $temporary) {
                throw "durable migration staging collision: $temporary"
            }
            Copy-Item -LiteralPath $item.Path -Destination $temporary
            $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $item.Path).Hash
            $stagedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash
            if ($sourceHash -ne $stagedHash) {
                throw "durable migration hash mismatch: $($item.Path)"
            }
            $staged += @{ Temporary = $temporary; Target = $target }
        }
        foreach ($item in $staged) {
            Move-Item -LiteralPath $item.Temporary -Destination $item.Target
            $installed += $item.Target
        }
    } catch {
        foreach ($item in $staged) {
            if (Test-Path -LiteralPath $item.Temporary) {
                Remove-Item -LiteralPath $item.Temporary -Force
            }
        }
        # Every target was proven absent above. These paths can only have been
        # created by this invocation, and no bridge is started until the whole
        # migration function returns successfully.
        foreach ($target in $installed) {
            if (Test-Path -LiteralPath $target) {
                Remove-Item -LiteralPath $target -Force
            }
        }
        throw
    }
}

function Invoke-Bridge([hashtable]$Instance, [string]$Path, [int]$TimeoutSec = 8) {
    $key = Get-EnvValue (Join-Path $Instance.Root ".env") "API_KEY"
    $headers = @{ "X-API-Key" = $key }
    return Invoke-RestMethod -Uri ("http://127.0.0.1:{0}{1}" -f $Instance.Port, $Path) -Headers $headers -TimeoutSec $TimeoutSec
}

function Assert-BridgeIdle([hashtable]$Instance) {
    $health = Invoke-Bridge $Instance "/health"
    $queue = $health.execution_queue
    if ([int]($queue.pending_executions) -ne 0 -or
            [int]($queue.admitted_waiting) -ne 0 -or
            [int]($queue.queued) -ne 0 -or
            [int]($queue.claimed) -ne 0 -or [int]($queue.running) -ne 0) {
        throw "bridge is busy: $($Instance.Name)"
    }
    $positions = Invoke-Bridge $Instance "/mt5/positions?authoritative=true" 15
    $rows = @($positions.positions)
    if ($rows.Count -ne 0) {
        throw "bridge has open positions: $($Instance.Name) count=$($rows.Count)"
    }
}

function Get-ProcessSnapshot {
    return @(Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId,Name,CommandLine `
        -OperationTimeoutSec 5 | ForEach-Object {
        [PSCustomObject]@{
            ProcessId = [int]$_.ProcessId
            ParentProcessId = [int]$_.ParentProcessId
            Name = [string]$_.Name
            CommandLine = [string]$_.CommandLine
        }
    })
}

function Add-ProcessId([Collections.Generic.HashSet[int]]$Set, $Value) {
    try {
        $processId = [int]$Value
        if ($processId -gt 0) { $null = $Set.Add($processId) }
    } catch { }
}

function Get-ProcessTreeIds([int[]]$RootIds, [object[]]$Snapshot) {
    $selected = [Collections.Generic.HashSet[int]]::new()
    $pending = [Collections.Generic.Queue[int]]::new()
    foreach ($rootId in @($RootIds)) {
        if ($rootId -gt 0 -and $selected.Add([int]$rootId)) {
            $pending.Enqueue([int]$rootId)
        }
    }
    while ($pending.Count -gt 0) {
        $parentId = $pending.Dequeue()
        foreach ($child in @($Snapshot | Where-Object { $_.ParentProcessId -eq $parentId })) {
            if ($selected.Add([int]$child.ProcessId)) {
                $pending.Enqueue([int]$child.ProcessId)
            }
        }
    }
    return @($selected)
}

function Stop-ProcessTrees([int[]]$RootIds, [object[]]$Snapshot, [string]$Label) {
    $roots = @($RootIds | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
    if ($roots.Count -eq 0) { return @() }
    $treeIds = @(Get-ProcessTreeIds $roots $Snapshot)

    # Freeze launchers/listeners first so they cannot spawn another execution
    # worker, then terminate every descendant captured recursively. The caller
    # rescans known parent PIDs to catch a child created at the snapshot edge.
    foreach ($rootId in $roots) {
        Stop-Process -Id $rootId -Force -ErrorAction SilentlyContinue
    }
    foreach ($processId in @($treeIds | Where-Object { $_ -notin $roots })) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $alive = @(Get-Process -Id $treeIds -ErrorAction SilentlyContinue)
        if ($alive.Count -eq 0) { return $treeIds }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Label process tree did not stop: $($alive.Id -join ',')"
}

function Get-BridgeProcessRoots([int[]]$Ports, [object[]]$Snapshot,
                                [Collections.Generic.HashSet[int]]$KnownTreeIds) {
    $roots = [Collections.Generic.HashSet[int]]::new()
    $portPattern = "--port(?:=|\s+)(" + (($Ports | ForEach-Object {
        [Regex]::Escape([string]$_)
    }) -join "|") + ")($|\s)"
    $rootPattern = (($Instances | Where-Object { $_.Port -in $Ports } |
        ForEach-Object { [Regex]::Escape([string]$_.Root) }) -join "|")

    foreach ($listener in @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in $Ports })) {
        Add-ProcessId $roots $listener.OwningProcess
    }
    foreach ($process in $Snapshot) {
        $commandLine = [string]$process.CommandLine
        if (($commandLine -match $portPattern) -or
                ($rootPattern -and $commandLine -match $rootPattern) -or
                $KnownTreeIds.Contains([int]$process.ParentProcessId)) {
            Add-ProcessId $roots $process.ProcessId
        }
    }

    # Health provides both the HTTP listener and multiprocessing spawn worker
    # PIDs. Retain the other discovery paths because health can disappear
    # between the idle gate and shutdown.
    foreach ($instance in @($Instances | Where-Object { $_.Port -in $Ports })) {
        try {
            $health = Invoke-Bridge $instance "/health" 3
            Add-ProcessId $roots $health.execution_queue.http_process_pid
            Add-ProcessId $roots $health.execution_queue.execution_process_pid
        } catch { }
    }
    return @($roots)
}

function Stop-PythonByPort([int[]]$Ports) {
    $knownTreeIds = [Collections.Generic.HashSet[int]]::new()
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        $snapshot = @(Get-ProcessSnapshot)
        $roots = @(Get-BridgeProcessRoots $Ports $snapshot $knownTreeIds)
        if ($roots.Count -eq 0) { break }
        $stopped = @(Stop-ProcessTrees $roots $snapshot "bridge")
        foreach ($processId in $stopped) { Add-ProcessId $knownTreeIds $processId }
        Start-Sleep -Milliseconds 300
    }

    $snapshot = @(Get-ProcessSnapshot)
    $leftovers = @(Get-BridgeProcessRoots $Ports $snapshot $knownTreeIds)
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $Ports })
    if ($leftovers.Count -ne 0 -or $listeners.Count -ne 0) {
        throw "bridge process forest did not stop: pids=$($leftovers -join ',') ports=$($listeners.LocalPort -join ',')"
    }
}

function Stop-Cell {
    $snapshot = @(Get-ProcessSnapshot)
    $roots = [Collections.Generic.HashSet[int]]::new()
    foreach ($listener in @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq 8600 })) {
        Add-ProcessId $roots $listener.OwningProcess
    }
    foreach ($process in $snapshot) {
        if ($process.CommandLine -match "uvicorn\s+cell:app" -or
                $process.CommandLine -match "run_cell\.ps1") {
            Add-ProcessId $roots $process.ProcessId
        }
    }
    $rootIds = @($roots)
    if ($rootIds.Count -eq 0) { return }

    # Cell is a shared parent for other account bridges, so stop the launcher
    # roots themselves without /T. Target bridge trees are collected and
    # recursively stopped by Stop-PythonByPort immediately afterwards.
    foreach ($processId in $rootIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $alive = @(Get-Process -Id $rootIds -ErrorAction SilentlyContinue)
        if ($alive.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($alive.Count -ne 0) {
        throw "cell launcher did not stop: $($alive.Id -join ',')"
    }
}

function Start-Bridge([hashtable]$Instance, [string]$LogTag) {
    $logDir = Join-Path $Instance.Root "logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Process -FilePath $Python -ArgumentList @(
        "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", [string]$Instance.Port
    ) -WorkingDirectory $Instance.Root -RedirectStandardOutput (Join-Path $logDir "bridge.$LogTag.out.log") `
      -RedirectStandardError (Join-Path $logDir "bridge.$LogTag.err.log") -WindowStyle Hidden
}

function Wait-NewBridge([hashtable]$Instance, [int]$BudgetSec = 90) {
    $deadline = [DateTime]::UtcNow.AddSeconds($BudgetSec)
    $last = "not started"
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-Bridge $Instance "/health" 5
            $queue = $health.execution_queue
            if ($health.build_id -eq $Release -and $health.mt5 -eq $true -and
                $health.status -eq "ok" -and $health.execution_healthy -eq $true -and
                $health.execution_process_isolation -eq $true -and
                $queue.process_isolated -eq $true -and
                $queue.execution_process_ready -eq $true -and
                $queue.execution_process_alive -eq $true -and
                $queue.coordinator_healthy -eq $true -and
                $queue.promoter_alive -eq $true -and $queue.monitor_alive -eq $true -and
                [int]$queue.http_process_pid -gt 0 -and
                [int]$queue.execution_process_pid -gt 0 -and
                [int]$queue.http_process_pid -ne [int]$queue.execution_process_pid -and
                [int]$queue.pending_executions -eq 0) {
                return $health
            }
            $last = $health | ConvertTo-Json -Compress -Depth 8
        } catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "new bridge health timeout $($Instance.Name): $last"
}

function Start-Cell {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\QHCELL\run_cell.ps1"
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8600/cell/health" -TimeoutSec 3
            if ($health.ok -eq $true) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "cell health timeout"
}

function Restore-Backup {
    Stop-Cell
    Stop-PythonByPort @(8061, 8063)
    Copy-Item -LiteralPath (Join-Path $Backup "main.py.before") -Destination (Join-Path $AppRoot "main.py") -Force
    Copy-Item -LiteralPath (Join-Path $Backup "runtime.py.before") -Destination (Join-Path $AppRoot "runtime.py") -Force
    Copy-Item -LiteralPath (Join-Path $Backup "cell.py.before") -Destination (Join-Path $CellRoot "cell.py") -Force
    foreach ($instance in $Instances) {
        Copy-Item -LiteralPath (Join-Path $Backup "$($instance.Name).env.before") -Destination (Join-Path $instance.Root ".env") -Force
        # Code rollback must not roll durable broker evidence back in time.
        # Keep the live idempotency DB/WAL/SHM exactly as the stopped bridge
        # left them; the pre-deploy copies remain forensic backups only.
        Start-Bridge $instance "rollback"
    }
    foreach ($instance in $Instances) {
        $deadline = [DateTime]::UtcNow.AddSeconds(60)
        $ok = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            try {
                $health = Invoke-Bridge $instance "/health" 5
                if ($health.mt5 -eq $true) { $ok = $true; break }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ok) { throw "rollback bridge health timeout: $($instance.Name)" }
    }
    Start-Cell
}

New-Item -ItemType Directory -Force -Path $Backup | Out-Null
try {
    Assert-FileHash (Join-Path $Stage "app\main.py") $Expected["main.py"]
    Assert-FileHash (Join-Path $Stage "app\runtime.py") $Expected["runtime.py"]
    Assert-FileHash (Join-Path $Stage "cell.py") $Expected["cell.py"]
    foreach ($instance in $Instances) { Assert-BridgeIdle $instance }

    Copy-Item -LiteralPath (Join-Path $AppRoot "main.py") -Destination (Join-Path $Backup "main.py.before")
    Copy-Item -LiteralPath (Join-Path $AppRoot "runtime.py") -Destination (Join-Path $Backup "runtime.py.before")
    Copy-Item -LiteralPath (Join-Path $CellRoot "cell.py") -Destination (Join-Path $Backup "cell.py.before")
    foreach ($instance in $Instances) {
        Copy-Item -LiteralPath (Join-Path $instance.Root ".env") -Destination (Join-Path $Backup "$($instance.Name).env.before")
    }
    $RestoreReady = $true

    Stop-Cell
    Stop-PythonByPort @(8061, 8063)
    $executionSettings = @{}
    foreach ($instance in $Instances) {
        $settings = Get-ExecutionSettings $instance
        $executionSettings[$instance.Name] = $settings
        Copy-DurableDatabase $settings.SourceDb $settings.TargetDb `
            (Join-Path $Backup "$($instance.Name).idempotency.db")
    }

    Copy-Item -LiteralPath (Join-Path $Stage "app\main.py") -Destination (Join-Path $AppRoot "main.py") -Force
    Copy-Item -LiteralPath (Join-Path $Stage "app\runtime.py") -Destination (Join-Path $AppRoot "runtime.py") -Force
    Copy-Item -LiteralPath (Join-Path $Stage "cell.py") -Destination (Join-Path $CellRoot "cell.py") -Force
    Assert-FileHash (Join-Path $AppRoot "main.py") $Expected["main.py"]
    Assert-FileHash (Join-Path $AppRoot "runtime.py") $Expected["runtime.py"]
    Assert-FileHash (Join-Path $CellRoot "cell.py") $Expected["cell.py"]

    foreach ($instance in $Instances) {
        $envPath = Join-Path $instance.Root ".env"
        $settings = $executionSettings[$instance.Name]
        Set-EnvValue $envPath "MT5_EXECUTION_PROCESS_ISOLATION" "1"
        Set-EnvValue $envPath "MAX_PENDING_EXECUTIONS" "32"
        Set-EnvValue $envPath "MT5_PARENT_READ_GATE_WAIT_MS" "5000"
        Set-EnvValue $envPath "MT5_EXECUTION_READY_SEC" "55"
        Set-EnvValue $envPath "MT5_EXECUTION_CONNECT_SEC" "45"
        Set-EnvValue $envPath "MT5_EXECUTION_CONNECT_RETRY_MS" "750"
        Set-EnvValue $envPath "MT5_BRIDGE_BUILD_ID" $Release
        Set-EnvValue $envPath "MT5_EXECUTION_FENCE_KEY" $settings.FenceKey
        Set-EnvValue $envPath "MT5_EXECUTION_LOCK_DIR" $ExecutionLockRoot
        Set-EnvValue $envPath "IDEMPOTENCY_DB" $settings.TargetDb
        Start-Bridge $instance $Release
    }

    $healthRows = @()
    foreach ($instance in $Instances) {
        $health = Wait-NewBridge $instance
        Assert-BridgeIdle $instance
        $probeId = "qh-deploy-absent-$($instance.Name)-$Stamp"
        $absent = Invoke-Bridge $instance ("/mt5/order-status/" + $probeId)
        if ($absent.state -ne "ABSENT" -or $absent.admitted -ne $false -or
            $absent.result.dispatch_durable -ne $false) {
            throw "ABSENT tombstone probe failed: $($instance.Name)"
        }
        $healthRows += @{
            name = $instance.Name
            port = $instance.Port
            build_id = $health.build_id
            http_pid = [int]$health.execution_queue.http_process_pid
            worker_pid = [int]$health.execution_queue.execution_process_pid
            positions = 0
            pending = 0
            absent_probe = $probeId
        }
    }
    Start-Cell

    $report = @{
        ok = $true
        release = $Release
        deployed_at = [DateTime]::UtcNow.ToString("o")
        backup = $Backup
        bridges = $healthRows
        real_orders_sent = $false
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    $report | ConvertTo-Json -Compress -Depth 8
} catch {
    $failure = $_.Exception.Message
    if ($RestoreReady) {
        try { Restore-Backup } catch { $failure += "; rollback=" + $_.Exception.Message }
    }
    $report = @{
        ok = $false
        release = $Release
        failed_at = [DateTime]::UtcNow.ToString("o")
        backup = $Backup
        error = $failure
        real_orders_sent = $false
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    throw $failure
}
