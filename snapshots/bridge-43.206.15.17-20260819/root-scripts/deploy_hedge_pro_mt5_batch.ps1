param(
    [string]$Stage = 'D:\QHMT5\runtime\staged\hedge-pro-mt5-batch-20260731'
)

$ErrorActionPreference = 'Stop'
$python = 'D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe'
$liveApp = 'D:\QHMT5\runtime\releases\v1\ic\app'
$expectedMain = 'F0F4BA29211D89ED42CD4FDA0041583CEB342409C99BA9D5B869F544B42E5FAC'
$expectedRuntime = 'FDF42FF7CCB40B974C0FA81C9D6B095C9F6E2AC1956BF22F5B6CBBA940572C35'
$apiKeyLine = Get-Content -LiteralPath 'D:\QHCELL\cell.env' |
    Where-Object { $_ -match '^API_KEY=' } | Select-Object -First 1
if (-not $apiKeyLine) { throw 'QHCELL API key is missing' }
$apiKey = $apiKeyLine.Substring('API_KEY='.Length).Trim()
$headers = @{'X-API-Key' = $apiKey}

$legs = @(
    [pscustomobject]@{ slot='s3'; port=8063; role='hedge'; instance='D:\QHCELL\pool\s3\inst' },
    [pscustomobject]@{ slot='s1'; port=8061; role='main';  instance='D:\QHCELL\pool\s1\inst' }
)

function Get-TerminalPid([string]$slot) {
    $process = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'terminal64.exe' -and $_.CommandLine -like ("*pool\{0}\terminal*" -f $slot)
    } | Select-Object -First 1
    return $process.ProcessId
}

function Get-PositionSnapshot([int]$port) {
    $response = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/positions" -f $port) `
        -Headers $headers -TimeoutSec 30
    $lines = foreach ($position in @($response.positions | Sort-Object ticket)) {
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
    return [ordered]@{
        count = @($response.positions).Count
        signature = $signature
        snapshot_boot = $response.snapshot_boot
        snapshot_seq = $response.snapshot_seq
        snapshot_ts = $response.snapshot_ts
    }
}

function Wait-Bridge([int]$port, [int]$seconds=150) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        try {
            $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $port) -TimeoutSec 3
            if ($health.mt5 -and $health.trade_allowed -ne $false) { return $health }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "bridge $port did not become healthy within ${seconds}s"
}

function Restart-BridgeOnly($leg) {
    $listener = Get-NetTCPConnection -LocalPort $leg.port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $listener) { throw "bridge $($leg.port) has no listener before restart" }
    $targetPid = [int]$listener.OwningProcess
    $target = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $targetPid)
    if (-not $target -or $target.Name -ne 'python.exe' -or $target.CommandLine -notlike ("*--port {0}*" -f $leg.port)) {
        throw "refusing to stop unexpected process on port $($leg.port)"
    }
    Stop-Process -Id $targetPid -Force
    $deadline = (Get-Date).AddSeconds(15)
    do {
        if (-not (Get-NetTCPConnection -LocalPort $leg.port -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if (Get-NetTCPConnection -LocalPort $leg.port -State Listen -ErrorAction SilentlyContinue) {
        throw "port $($leg.port) did not stop"
    }
    $logs = Join-Path $leg.instance 'logs'
    Start-Process -FilePath $python `
        -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port',([string]$leg.port) `
        -WorkingDirectory $leg.instance -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'bridge.out.log') `
        -RedirectStandardError (Join-Path $logs 'bridge.err.log')
    Wait-Bridge $leg.port | Out-Null
}

$stageMain = Join-Path $Stage 'app\main.py'
$stageRuntime = Join-Path $Stage 'app\runtime.py'
if ((Get-FileHash -LiteralPath $stageMain -Algorithm SHA256).Hash -ne $expectedMain) {
    throw 'staged main.py hash mismatch'
}
if ((Get-FileHash -LiteralPath $stageRuntime -Algorithm SHA256).Hash -ne $expectedRuntime) {
    throw 'staged runtime.py hash mismatch'
}
& $python 'D:\preflight_hedge_pro_mt5_v3.py'
if ($LASTEXITCODE -ne 0) { throw 'recent in-flight MT5 execution detected' }

$before = [ordered]@{}
foreach ($leg in $legs) {
    $before[$leg.role] = [ordered]@{
        port = $leg.port
        listener_pid = (Get-NetTCPConnection -LocalPort $leg.port -State Listen | Select-Object -First 1).OwningProcess
        terminal_pid = Get-TerminalPid $leg.slot
        positions = Get-PositionSnapshot $leg.port
    }
}

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backup = "D:\QHMT5\backups\hedge-pro-mt5-v3-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item -LiteralPath (Join-Path $liveApp 'main.py') -Destination (Join-Path $backup 'main.py.before')
$runtimeExisted = Test-Path -LiteralPath (Join-Path $liveApp 'runtime.py')
if ($runtimeExisted) {
    Copy-Item -LiteralPath (Join-Path $liveApp 'runtime.py') -Destination (Join-Path $backup 'runtime.py.before')
}

$restarted = @()
try {
    Copy-Item -LiteralPath $stageRuntime -Destination (Join-Path $liveApp 'runtime.py') -Force
    Copy-Item -LiteralPath $stageMain -Destination (Join-Path $liveApp 'main.py') -Force

    foreach ($leg in $legs) {
        Restart-BridgeOnly $leg
        $restarted += $leg
        $afterPositions = Get-PositionSnapshot $leg.port
        $afterTerminalPid = Get-TerminalPid $leg.slot
        $openapi = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/openapi.json" -f $leg.port) -TimeoutSec 10
        if ($openapi.info.version -ne '3.0.0') { throw "port $($leg.port) did not load v3" }
        if ($afterPositions.count -ne $before[$leg.role].positions.count -or
            $afterPositions.signature -ne $before[$leg.role].positions.signature) {
            throw "position signature changed on port $($leg.port)"
        }
        if ($before[$leg.role].terminal_pid -and $afterTerminalPid -ne $before[$leg.role].terminal_pid) {
            throw "terminal PID changed for $($leg.slot)"
        }
        if ($null -eq $afterPositions.snapshot_boot -or $null -eq $afterPositions.snapshot_seq) {
            throw "position snapshot version missing on port $($leg.port)"
        }
    }
} catch {
    Copy-Item -LiteralPath (Join-Path $backup 'main.py.before') -Destination (Join-Path $liveApp 'main.py') -Force
    if ($runtimeExisted) {
        Copy-Item -LiteralPath (Join-Path $backup 'runtime.py.before') -Destination (Join-Path $liveApp 'runtime.py') -Force
    } else {
        Remove-Item -LiteralPath (Join-Path $liveApp 'runtime.py') -Force -ErrorAction SilentlyContinue
    }
    foreach ($leg in $restarted) {
        Restart-BridgeOnly $leg
    }
    throw
}

$after = [ordered]@{}
foreach ($leg in $legs) {
    $after[$leg.role] = [ordered]@{
        port = $leg.port
        listener_pid = (Get-NetTCPConnection -LocalPort $leg.port -State Listen | Select-Object -First 1).OwningProcess
        terminal_pid = Get-TerminalPid $leg.slot
        positions = Get-PositionSnapshot $leg.port
        app_version = (Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/openapi.json" -f $leg.port) -TimeoutSec 10).info.version
    }
}

[ordered]@{
    deployed_at = (Get-Date).ToUniversalTime().ToString('o')
    backup = $backup
    live_main_sha256 = (Get-FileHash -LiteralPath (Join-Path $liveApp 'main.py') -Algorithm SHA256).Hash
    live_runtime_sha256 = (Get-FileHash -LiteralPath (Join-Path $liveApp 'runtime.py') -Algorithm SHA256).Hash
    before = $before
    after = $after
} | ConvertTo-Json -Depth 10 -Compress
