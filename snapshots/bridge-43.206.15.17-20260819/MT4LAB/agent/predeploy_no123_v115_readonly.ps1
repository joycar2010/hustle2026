$ErrorActionPreference = 'Stop'

$agentRoot = 'D:\MT4LAB\agent'
$run = Get-Content -LiteralPath (Join-Path $agentRoot 'run_agent.ps1')
$keyLine = $run | Where-Object { $_ -match '^\$env:API_KEY\s*=' } | Select-Object -First 1
$apiKey = ($keyLine -split "'")[1]
$instances = @(
    [pscustomobject]@{ Name = 'ic'; Port = 8041; Task = 'MT4LAB-Agent-ic' },
    [pscustomobject]@{ Name = 'exness'; Port = 8042; Task = 'MT4LAB-Agent-exness' }
)

$rows = foreach ($instance in $instances) {
    $terminalRoot = "D:\MT4LAB\terminals\$($instance.Name)"
    $bridgeRoot = Join-Path $terminalRoot 'MQL4\Files\qhbridge'
    $positions = Invoke-RestMethod -Uri "http://127.0.0.1:$($instance.Port)/mt5/positions" `
        -Headers @{'X-API-Key' = $apiKey} -TimeoutSec 5
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$($instance.Port)/mt5/connection/status" `
        -Headers @{'X-API-Key' = $apiKey} -TimeoutSec 5
    $meta = Get-Content -LiteralPath (Join-Path $bridgeRoot 'state\meta.json') -Raw | ConvertFrom-Json
    $positionFile = Get-Content -LiteralPath (Join-Path $bridgeRoot 'state\positions.json') -Raw | ConvertFrom-Json
    $task = Get-ScheduledTask -TaskName $instance.Task
    $listener = Get-NetTCPConnection -LocalPort $instance.Port -State Listen | Select-Object -First 1
    $source = Join-Path $terminalRoot 'MQL4\Experts\QHBridge.mq4'
    $binary = Join-Path $terminalRoot 'MQL4\Experts\QHBridge.ex4'
    $editors = @(Get-ChildItem -LiteralPath $terminalRoot -Filter 'metaeditor*.exe' -File -ErrorAction SilentlyContinue)
    [ordered]@{
        name = $instance.Name
        port = $instance.Port
        connected = [bool]$status.connected
        account = [string]$status.account
        positions = @($positions.positions).Count
        tickets = @($positions.positions | ForEach-Object { $_.ticket })
        pending_commands = @(Get-ChildItem -LiteralPath (Join-Path $bridgeRoot 'commands') -Filter '*.json' -File -ErrorAction SilentlyContinue).Count
        ea = $meta.ea
        snapshot_boot = $positionFile.snapshot_boot
        snapshot_seq = $positionFile.snapshot_seq
        source_hash = if (Test-Path -LiteralPath $source) { (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash } else { $null }
        binary_hash = if (Test-Path -LiteralPath $binary) { (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash } else { $null }
        metaeditors = @($editors.FullName)
        task_state = [string]$task.State
        listener_pid = $listener.OwningProcess
    }
}

$python = Join-Path $agentRoot 'venv\Scripts\python.exe'
$walRaw = & $python (Join-Path $agentRoot 'inspect_no123_agent_wal.py')
if ($LASTEXITCODE -ne 0) { throw 'Agent WAL inspection failed' }
$wal = $walRaw | ConvertFrom-Json

[ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    instances = @($rows)
    wal = $wal
} | ConvertTo-Json -Depth 8 -Compress
