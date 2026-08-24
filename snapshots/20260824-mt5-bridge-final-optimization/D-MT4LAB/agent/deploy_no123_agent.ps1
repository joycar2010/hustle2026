[CmdletBinding()]
param(
    [string]$ReleaseTag = 'qhtest1-20260731'
)

$ErrorActionPreference = 'Stop'
$baseDir = 'D:\MT4LAB\agent'
$python = Join-Path $baseDir 'venv\Scripts\python.exe'
$stagedMain = Join-Path $baseDir 'main.py.qhtest1.new'
$stagedBridge = Join-Path $baseDir 'filebridge.py.qhtest1.new'
$backupDir = Join-Path $baseDir ("backups\{0}" -f $ReleaseTag)

foreach ($path in $stagedMain, $stagedBridge) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing staged file: $path" }
}
& $python -m py_compile $stagedMain $stagedBridge
if ($LASTEXITCODE -ne 0) { throw 'Agent staged Python compile failed' }

$run = Get-Content -LiteralPath (Join-Path $baseDir 'run_agent.ps1')
$keyLine = $run | Where-Object { $_ -match '^\$env:API_KEY\s*=' } | Select-Object -First 1
$apiKey = ($keyLine -split "'")[1]
$instances = @(
    [pscustomobject]@{ Name = 'ic'; Port = 8041; Task = 'MT4LAB-Agent-ic' },
    [pscustomobject]@{ Name = 'exness'; Port = 8042; Task = 'MT4LAB-Agent-exness' }
)

foreach ($instance in $instances) {
    $positions = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/positions" -f $instance.Port) `
        -Headers @{'X-API-Key' = $apiKey} -TimeoutSec 5
    if (@($positions.positions).Count -ne 0) {
        throw "Refusing restart: port $($instance.Port) has open positions"
    }
    $commands = "D:\MT4LAB\terminals\$($instance.Name)\MQL4\Files\qhbridge\commands"
    if (@(Get-ChildItem -LiteralPath $commands -Filter '*.json' -File -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "Refusing restart: port $($instance.Port) has pending commands"
    }
}

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $baseDir 'main.py') -Destination $backupDir -Force
Copy-Item -LiteralPath (Join-Path $baseDir 'filebridge.py') -Destination $backupDir -Force

function Stop-Agent([pscustomobject]$Instance) {
    Stop-ScheduledTask -TaskName $Instance.Task -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(10)
    do {
        $listener = Get-NetTCPConnection -LocalPort $Instance.Port -State Listen `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $listener) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ($listener -and $listener.OwningProcess) {
        Stop-Process -Id $listener.OwningProcess -Force
    }
}

function Start-And-Wait([pscustomobject]$Instance) {
    Start-ScheduledTask -TaskName $Instance.Task
    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 400
        try {
            $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Instance.Port) `
                -TimeoutSec 2
            if ($health.status -eq 'ok') { return }
        } catch {}
    } while ((Get-Date) -lt $deadline)
    throw "Agent port $($Instance.Port) did not recover"
}

try {
    Copy-Item -LiteralPath $stagedMain -Destination (Join-Path $baseDir 'main.py') -Force
    Copy-Item -LiteralPath $stagedBridge -Destination (Join-Path $baseDir 'filebridge.py') -Force
    foreach ($instance in $instances) { Stop-Agent $instance }
    foreach ($instance in $instances) { Start-And-Wait $instance }
} catch {
    Copy-Item -LiteralPath (Join-Path $backupDir 'main.py') -Destination (Join-Path $baseDir 'main.py') -Force
    Copy-Item -LiteralPath (Join-Path $backupDir 'filebridge.py') -Destination (Join-Path $baseDir 'filebridge.py') -Force
    foreach ($instance in $instances) {
        try { Stop-Agent $instance; Start-And-Wait $instance } catch {}
    }
    throw
}

$result = foreach ($instance in $instances) {
    $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $instance.Port) -TimeoutSec 3
    $status = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/connection/status" -f $instance.Port) `
        -Headers @{'X-API-Key' = $apiKey} -TimeoutSec 3
    [pscustomobject]@{
        Port = $instance.Port
        Service = $health.service
        Connected = [bool]$status.connected
        Account = $status.account
        ProcessId = (Get-NetTCPConnection -LocalPort $instance.Port -State Listen).OwningProcess
    }
}

[pscustomobject]@{
    ReleaseTag = $ReleaseTag
    BackupDir = $backupDir
    MainHash = (Get-FileHash -LiteralPath (Join-Path $baseDir 'main.py') -Algorithm SHA256).Hash
    FileBridgeHash = (Get-FileHash -LiteralPath (Join-Path $baseDir 'filebridge.py') -Algorithm SHA256).Hash
    Instances = @($result)
} | ConvertTo-Json -Depth 5 -Compress
