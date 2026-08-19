param(
    [string]$Stage = "D:\QHMT5\deploy\mt5-single-owner-admission-20260817.2",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9A-Fa-f]{64}$")]
    [string]$ManifestSha256,
    [switch]$QHMaintenanceOwned
)

$ErrorActionPreference = "Stop"
$Release = "mt5-single-owner-admission-20260817.2"
$AppRoot = "D:\QHMT5\runtime\releases\v1\ic\app"
$CellRoot = "D:\QHCELL"
$ExecutionRoot = Join-Path $CellRoot "execution"
$ExecutionLockRoot = Join-Path $ExecutionRoot "locks"
$Python = "D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe"
$ManifestPath = Join-Path $Stage "release-manifest.json"
$Expected = @{}
$ProductionBefore = @{}
$Manifest = $null
$Instances = @(
    @{ Name = "s1"; Port = 8061; Root = "D:\QHCELL\pool\s1\inst" },
    @{ Name = "s3"; Port = 8063; Root = "D:\QHCELL\pool\s3\inst" }
)
$Stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$Backup = "D:\QHMT5\backups\$Release-$Stamp"
$ReportPath = Join-Path $Backup "deployment-report.json"
$RestoreReady = $false
$CellTaskName = "QHCELL-Agent"
$CellWatchdogTouched = $false
$CellWatchdogWasEnabled = $false
$CellWatchdogSuspended = $false
$CellSupervisorQuiesced = $false
$ProductionMutated = $false
$CandidateStartRequested = $false
$RollbackVerified = $false
$CellWatchdogRestored = $false

function Assert-FileHash([string]$Path, [string]$ExpectedHash) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "missing file: $Path"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedHash.ToLowerInvariant()) {
        throw "hash mismatch: $Path expected=$ExpectedHash actual=$actual"
    }
}

function Get-ManifestHash($Section, [string]$Name) {
    $property = $Section.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "manifest hash is missing: $Name"
    }
    $value = [string]$property.Value
    if ($value -notmatch "^[0-9A-Fa-f]{64}$") {
        throw "manifest hash is invalid: $Name"
    }
    return $value.ToLowerInvariant()
}

function Assert-ReleaseManifest {
    Assert-FileHash $ManifestPath $ManifestSha256
    try {
        $script:Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    } catch {
        throw "invalid release manifest: $($_.Exception.Message)"
    }
    if ([int]$Manifest.schema -ne 1 -or [string]$Manifest.release -ne $Release -or
            [string]$Manifest.deployment_status -ne "candidate_sealed_not_deployed") {
        throw "release manifest identity mismatch"
    }
    if ($Manifest.required_runtime_gates.maintenance_owned -ne $true) {
        throw "release manifest does not require owned maintenance"
    }

    $candidateNames = @($Manifest.candidate.PSObject.Properties.Name | Sort-Object)
    $requiredCandidateNames = @("cell.py", "deploy.ps1", "main.py", "runtime.py")
    if (@(Compare-Object $candidateNames $requiredCandidateNames).Count -ne 0) {
        throw "release manifest candidate file set mismatch"
    }
    foreach ($name in $requiredCandidateNames) {
        $script:Expected[$name] = Get-ManifestHash $Manifest.candidate $name
    }
    foreach ($name in @("cell.py", "main.py", "runtime.py")) {
        $script:ProductionBefore[$name] = Get-ManifestHash $Manifest.production_before $name
    }

    Assert-FileHash (Join-Path $Stage "app\main.py") $Expected["main.py"]
    Assert-FileHash (Join-Path $Stage "app\runtime.py") $Expected["runtime.py"]
    Assert-FileHash (Join-Path $Stage "cell.py") $Expected["cell.py"]
    Assert-FileHash (Join-Path $Stage "deploy.ps1") $Expected["deploy.ps1"]
    Assert-FileHash $PSCommandPath $Expected["deploy.ps1"]
}

function Assert-QHMaintenanceOwned {
    if (-not $QHMaintenanceOwned) {
        throw "refusing to deploy unless QH blocking maintenance is already owned"
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
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $BackupPrefix) | Out-Null

    # A WAL database is one durable unit. Prove every final name absent before
    # creating anything, stage under one-use names, hash all copies, and only
    # then publish the complete set. Existing durable files are never forced.
    foreach ($suffix in $suffixes) {
        $backupTarget = $BackupPrefix + $suffix
        if (Test-Path -LiteralPath $backupTarget) {
            throw "durable database backup already exists: $backupTarget"
        }
        if (-not $samePath) {
            $target = $TargetDb + $suffix
            if (Test-Path -LiteralPath $target) {
                throw "target durable database already exists: $target"
            }
        }
    }

    $token = [Guid]::NewGuid().ToString("N")
    $entries = @()
    foreach ($suffix in $suffixes) {
        $source = $SourceDb + $suffix
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            $entries += [PSCustomObject]@{
                Source = $source
                Backup = $BackupPrefix + $suffix
                BackupTemp = $BackupPrefix + ".migrate-$token$suffix.tmp"
                Target = $TargetDb + $suffix
                TargetTemp = $TargetDb + ".migrate-$token$suffix.tmp"
            }
        }
    }
    $created = [Collections.Generic.List[string]]::new()
    try {
        foreach ($entry in $entries) {
            Copy-Item -LiteralPath $entry.Source -Destination $entry.BackupTemp -ErrorAction Stop
            if ((Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Source).Hash -ne
                    (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.BackupTemp).Hash) {
                throw "durable database backup hash mismatch: $($entry.Source)"
            }
            if (-not $samePath) {
                Copy-Item -LiteralPath $entry.Source -Destination $entry.TargetTemp -ErrorAction Stop
                if ((Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Source).Hash -ne
                        (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.TargetTemp).Hash) {
                    throw "durable database migration hash mismatch: $($entry.Source)"
                }
            }
        }

        # Close the staging race. Move-Item remains non-forcing so a creator
        # appearing after this check is rejected and its file stays untouched.
        foreach ($suffix in $suffixes) {
            if (Test-Path -LiteralPath ($BackupPrefix + $suffix)) {
                throw "durable database backup appeared during migration: $($BackupPrefix + $suffix)"
            }
            if (-not $samePath -and (Test-Path -LiteralPath ($TargetDb + $suffix))) {
                throw "target durable database appeared during migration: $($TargetDb + $suffix)"
            }
        }
        foreach ($entry in $entries) {
            Move-Item -LiteralPath $entry.BackupTemp -Destination $entry.Backup -ErrorAction Stop
            $created.Add($entry.Backup)
        }
        if (-not $samePath) {
            foreach ($entry in $entries) {
                Move-Item -LiteralPath $entry.TargetTemp -Destination $entry.Target -ErrorAction Stop
                $created.Add($entry.Target)
            }
        }
    } catch {
        foreach ($entry in $entries) {
            foreach ($temporary in @($entry.BackupTemp, $entry.TargetTemp)) {
                if (Test-Path -LiteralPath $temporary) {
                    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
                }
            }
        }
        for ($index = $created.Count - 1; $index -ge 0; $index--) {
            $path = $created[$index]
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
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

function Assert-ProductionBeforeFiles {
    Assert-FileHash (Join-Path $AppRoot "main.py") $ProductionBefore["main.py"]
    Assert-FileHash (Join-Path $AppRoot "runtime.py") $ProductionBefore["runtime.py"]
    Assert-FileHash (Join-Path $CellRoot "cell.py") $ProductionBefore["cell.py"]
}

function Assert-ProductionBeforeRuntime {
    $expectedBuild = $Manifest.production_before.build_id
    $expectedIsolation = $Manifest.production_before.execution_process_isolation -eq $true
    foreach ($instance in $Instances) {
        $health = Invoke-Bridge $instance "/health"
        $actualBuild = $health.build_id
        if ($null -eq $expectedBuild) {
            if (-not [String]::IsNullOrWhiteSpace([string]$actualBuild)) {
                throw "production build drift: $($instance.Name) expected=<null> actual=$actualBuild"
            }
        } elseif ([string]$actualBuild -ne [string]$expectedBuild) {
            throw "production build drift: $($instance.Name) expected=$expectedBuild actual=$actualBuild"
        }
        $actualIsolation = $health.execution_process_isolation -eq $true
        if ($actualIsolation -ne $expectedIsolation) {
            throw "production isolation drift: $($instance.Name) expected=$expectedIsolation actual=$actualIsolation"
        }
    }
}

function Assert-BridgeIdle([hashtable]$Instance) {
    $health = Invoke-Bridge $Instance "/health"
    if ($health.mt5 -ne $true -or $health.status -ne "ok" -or
            $health.trade_allowed -ne $true) {
        throw "bridge is not trade-ready: $($Instance.Name)"
    }
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

function Assert-CellHealthy([bool]$RequireAllocatedDetails = $false) {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8600/cell/health" -TimeoutSec 5
    if ($health.ok -ne $true) {
        throw "cell allocated health gate failed"
    }
    $hasAllocatedHealthy = $null -ne $health.PSObject.Properties["allocated_healthy"]
    $hasUnhealthySlots = $null -ne $health.PSObject.Properties["unhealthy_slots"]
    if ($RequireAllocatedDetails -and
            (-not $hasAllocatedHealthy -or -not $hasUnhealthySlots)) {
        throw "cell allocated health details are unavailable"
    }
    if ($hasAllocatedHealthy -and $hasUnhealthySlots -and
            ([int]$health.allocated -ne [int]$health.allocated_healthy -or
             @($health.unhealthy_slots).Count -ne 0)) {
        throw "cell allocated health gate failed"
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

function Get-CellWatchdogTask {
    $tasks = @(Get-ScheduledTask -TaskName $CellTaskName -TaskPath "\" -ErrorAction Stop)
    if ($tasks.Count -ne 1) {
        throw "cell watchdog task identity is ambiguous"
    }
    return $tasks[0]
}

function Assert-CellWatchdogBaseline {
    $task = Get-CellWatchdogTask
    $actions = @($task.Actions)
    if ($task.Settings.Enabled -eq $false -or $actions.Count -ne 1 -or
            (Split-Path -Leaf ([string]$actions[0].Execute)) -ine "powershell.exe" -or
            [string]$actions[0].Arguments -notmatch "(?i)(^|\s)-File(\s|$)" -or
            [string]$actions[0].Arguments -notmatch "(?i)D:\\QHCELL\\run_cell\.ps1") {
        throw "cell watchdog baseline identity or enabled state mismatch"
    }
}

function Suspend-CellWatchdog {
    if ($CellWatchdogSuspended) { return }
    Assert-CellWatchdogBaseline
    $script:CellWatchdogWasEnabled = $true
    $script:CellWatchdogTouched = $true
    $script:CellWatchdogRestored = $false
    Disable-ScheduledTask -TaskName $CellTaskName -TaskPath "\" -ErrorAction Stop | Out-Null
    Stop-ScheduledTask -TaskName $CellTaskName -TaskPath "\" -ErrorAction SilentlyContinue

    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    $quietSamples = 0
    do {
        $task = Get-CellWatchdogTask
        $launchers = @(Get-ProcessSnapshot | Where-Object {
            $_.CommandLine -match "run_cell\.ps1"
        })
        if ($task.Settings.Enabled -eq $false -and
                $task.State -notin @("Running", "Queued") -and
                $launchers.Count -eq 0) {
            $quietSamples++
            if ($quietSamples -ge 5) {
                $script:CellWatchdogSuspended = $true
                return
            }
        } else {
            $quietSamples = 0
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "cell watchdog did not reach a stable suspended state"
}

function Stop-Cell {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    $quietSamples = 0
    do {
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
        foreach ($processId in @($roots)) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }

        Start-Sleep -Milliseconds 200

        $remaining = @(Get-ProcessSnapshot | Where-Object {
            $_.CommandLine -match "uvicorn\s+cell:app" -or
            $_.CommandLine -match "run_cell\.ps1"
        })
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq 8600 })
        if ($remaining.Count -eq 0 -and $listeners.Count -eq 0) {
            $quietSamples++
            if ($quietSamples -ge 5) { return }
        } else {
            $quietSamples = 0
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "cell launcher did not reach a stable stopped state"
}

function Ensure-CellSupervisorQuiesced {
    $script:CellSupervisorQuiesced = $false
    Suspend-CellWatchdog
    Stop-Cell
    Stop-PythonByPort @(8061, 8063)
    $script:CellSupervisorQuiesced = $true
}

function Start-CellWatchdog([bool]$RequireAllocatedDetails,
                            [bool]$RequireQuiesced = $true) {
    if (-not $CellWatchdogTouched) {
        throw "cell watchdog start requested without owned task state"
    }
    if ($RequireQuiesced -and -not $CellSupervisorQuiesced) {
        throw "cell watchdog start refused before process quiescence"
    }
    Enable-ScheduledTask -TaskName $CellTaskName -TaskPath "\" -ErrorAction Stop | Out-Null
    $script:CellWatchdogSuspended = $false
    $script:CellSupervisorQuiesced = $false
    Start-ScheduledTask -TaskName $CellTaskName -TaskPath "\" -ErrorAction Stop

    $deadline = [DateTime]::UtcNow.AddSeconds(150)
    $last = "not started"
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $task = Get-CellWatchdogTask
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8600/cell/health" -TimeoutSec 5
            $listener = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.LocalPort -eq 8600 })
            $allocatedOk = $true
            if ($RequireAllocatedDetails) {
                $allocatedProperty = $health.PSObject.Properties["allocated_healthy"]
                $unhealthyProperty = $health.PSObject.Properties["unhealthy_slots"]
                $allocatedOk = $null -ne $allocatedProperty -and $null -ne $unhealthyProperty -and
                    [int]$health.allocated -eq [int]$health.allocated_healthy -and
                    @($health.unhealthy_slots).Count -eq 0
            }
            if ($task.Settings.Enabled -ne $false -and $health.ok -eq $true -and
                    $listener.Count -gt 0 -and $allocatedOk) {
                return $health
            }
            $last = $health | ConvertTo-Json -Compress -Depth 8
        } catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "cell watchdog interactive start timeout: $last"
}

function Complete-CellWatchdogResume {
    $task = Get-CellWatchdogTask
    if ($task.Settings.Enabled -eq $false) {
        throw "cell watchdog is disabled after runtime validation"
    }
    $script:CellWatchdogTouched = $false
    $script:CellWatchdogSuspended = $false
    $script:CellSupervisorQuiesced = $false
    $script:CellWatchdogRestored = $true
}

function Wait-NewBridge([hashtable]$Instance, [int]$BudgetSec = 90) {
    $deadline = [DateTime]::UtcNow.AddSeconds($BudgetSec)
    $last = "not started"
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-Bridge $Instance "/health" 5
            $queue = $health.execution_queue
            if ($health.build_id -eq $Release -and $health.mt5 -eq $true -and
                $health.trade_allowed -eq $true -and
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
                $queue.native_owner_mode -eq "single_process_read_write_rpc" -and
                [int]$queue.native_owner_process_pid -eq [int]$queue.execution_process_pid -and
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

function Restore-BackupFiles {
    if (-not $CellSupervisorQuiesced) {
        throw "rollback refused without process quiescence"
    }
    Copy-Item -LiteralPath (Join-Path $Backup "main.py.before") -Destination (Join-Path $AppRoot "main.py") -Force
    Copy-Item -LiteralPath (Join-Path $Backup "runtime.py.before") -Destination (Join-Path $AppRoot "runtime.py") -Force
    Copy-Item -LiteralPath (Join-Path $Backup "cell.py.before") -Destination (Join-Path $CellRoot "cell.py") -Force
    Assert-FileHash (Join-Path $AppRoot "main.py") $ProductionBefore["main.py"]
    Assert-FileHash (Join-Path $AppRoot "runtime.py") $ProductionBefore["runtime.py"]
    Assert-FileHash (Join-Path $CellRoot "cell.py") $ProductionBefore["cell.py"]
    foreach ($instance in $Instances) {
        $backupEnv = Join-Path $Backup "$($instance.Name).env.before"
        $liveEnv = Join-Path $instance.Root ".env"
        Copy-Item -LiteralPath $backupEnv -Destination $liveEnv -Force
        $expectedEnv = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupEnv).Hash.ToLowerInvariant()
        Assert-FileHash $liveEnv $expectedEnv
        # Code rollback must not roll durable broker evidence back in time.
        # Keep the live idempotency DB/WAL/SHM exactly as the stopped bridge
        # left them; the pre-deploy copies remain forensic backups only.
    }
}

function Wait-RollbackBridges {
    foreach ($instance in $Instances) {
        $deadline = [DateTime]::UtcNow.AddSeconds(150)
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
    Assert-ProductionBeforeFiles
    Assert-ProductionBeforeRuntime
    foreach ($instance in $Instances) { Assert-BridgeIdle $instance }
    Assert-CellHealthy $false
}

Assert-ReleaseManifest
Assert-QHMaintenanceOwned
Assert-ProductionBeforeFiles
Assert-ProductionBeforeRuntime
foreach ($instance in $Instances) { Assert-BridgeIdle $instance }
Assert-CellHealthy $false
Assert-CellWatchdogBaseline
if (Test-Path -LiteralPath $Backup) {
    throw "backup already exists: $Backup"
}
New-Item -ItemType Directory -Path $Backup | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $AppRoot "main.py") -Destination (Join-Path $Backup "main.py.before")
    Copy-Item -LiteralPath (Join-Path $AppRoot "runtime.py") -Destination (Join-Path $Backup "runtime.py.before")
    Copy-Item -LiteralPath (Join-Path $CellRoot "cell.py") -Destination (Join-Path $Backup "cell.py.before")
    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $Backup "release-manifest.json")
    Assert-FileHash (Join-Path $Backup "main.py.before") $ProductionBefore["main.py"]
    Assert-FileHash (Join-Path $Backup "runtime.py.before") $ProductionBefore["runtime.py"]
    Assert-FileHash (Join-Path $Backup "cell.py.before") $ProductionBefore["cell.py"]
    Assert-FileHash (Join-Path $Backup "release-manifest.json") $ManifestSha256
    foreach ($instance in $Instances) {
        Copy-Item -LiteralPath (Join-Path $instance.Root ".env") -Destination (Join-Path $Backup "$($instance.Name).env.before")
    }
    $RestoreReady = $true

    Ensure-CellSupervisorQuiesced
    Assert-QHMaintenanceOwned
    Assert-ReleaseManifest
    Assert-ProductionBeforeFiles
    $executionSettings = @{}
    foreach ($instance in $Instances) {
        $settings = Get-ExecutionSettings $instance
        $executionSettings[$instance.Name] = $settings
        Copy-DurableDatabase $settings.SourceDb $settings.TargetDb `
            (Join-Path $Backup "$($instance.Name).idempotency.db")
    }

    $ProductionMutated = $true
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
        Set-EnvValue $envPath "MT5_NATIVE_RPC_TIMEOUT_SEC" "30"
        Set-EnvValue $envPath "MT5_BRIDGE_BUILD_ID" $Release
        Set-EnvValue $envPath "MT5_EXECUTION_FENCE_KEY" $settings.FenceKey
        Set-EnvValue $envPath "MT5_EXECUTION_LOCK_DIR" $ExecutionLockRoot
        Set-EnvValue $envPath "IDEMPOTENCY_DB" $settings.TargetDb
    }

    $CandidateStartRequested = $true
    $null = Start-CellWatchdog $true
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
            native_owner_mode = $health.execution_queue.native_owner_mode
            positions = 0
            pending = 0
            absent_probe = $probeId
        }
    }
    Assert-CellHealthy $true
    Complete-CellWatchdogResume

    $report = @{
        ok = $true
        release = $Release
        deployed_at = [DateTime]::UtcNow.ToString("o")
        backup = $Backup
        manifest_sha256 = $ManifestSha256.ToLowerInvariant()
        qh_maintenance_owned = $true
        candidate_start_requested = $CandidateStartRequested
        cell_watchdog_restored = $CellWatchdogRestored
        rollback_verified = $RollbackVerified
        bridges = $healthRows
        real_orders_sent = $false
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    $report | ConvertTo-Json -Compress -Depth 8
} catch {
    $failure = $_.Exception.Message
    if ($ProductionMutated -and $RestoreReady) {
        try {
            Ensure-CellSupervisorQuiesced
            Restore-BackupFiles
            $null = Start-CellWatchdog $false
            Wait-RollbackBridges
            Complete-CellWatchdogResume
            $RollbackVerified = $true
        } catch {
            $failure += "; rollback=" + $_.Exception.Message
            try { Ensure-CellSupervisorQuiesced } catch {
                $failure += "; rollback_quiescence=" + $_.Exception.Message
            }
        }
    } elseif ($CellWatchdogTouched) {
        try {
            $null = Start-CellWatchdog $false $false
            Wait-RollbackBridges
            Complete-CellWatchdogResume
        } catch {
            $failure += "; watchdog_recovery=" + $_.Exception.Message
        }
    }
    $report = @{
        ok = $false
        release = $Release
        failed_at = [DateTime]::UtcNow.ToString("o")
        backup = $Backup
        error = $failure
        production_mutated = $ProductionMutated
        candidate_start_requested = $CandidateStartRequested
        rollback_verified = $RollbackVerified
        cell_watchdog_restored = $CellWatchdogRestored
        cell_supervisor_quiesced = $CellSupervisorQuiesced
        real_orders_sent = $false
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    throw $failure
}
