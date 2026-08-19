$ErrorActionPreference = 'Stop'

$apiKey = '<REDACTED_API_KEY>'
$ports = 8061, 8063
$instances = foreach ($port in $ports) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -First 1
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listener.OwningProcess)
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 5
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/mt5/connection/status" `
        -Headers @{'X-API-Key'=$apiKey} -TimeoutSec 5
    $positions = Invoke-RestMethod -Uri "http://127.0.0.1:$port/mt5/positions" `
        -Headers @{'X-API-Key'=$apiKey} -TimeoutSec 15
    [ordered]@{
        port = $port
        pid = $listener.OwningProcess
        executable = $process.ExecutablePath
        command_line = $process.CommandLine
        creation_date = $process.CreationDate
        health = $health
        status = $status
        position_count = @($positions.positions).Count
        snapshot_boot = $positions.snapshot_boot
        snapshot_seq = $positions.snapshot_seq
        snapshot_ts = $positions.snapshot_ts
        snapshot_age_ms = $positions.snapshot_age_ms
        first_tickets = @($positions.positions | Select-Object -First 5 | ForEach-Object { $_.ticket })
    }
}

$tasks = Get-ScheduledTask | Where-Object {
    $_.TaskName -match 'QHCELL|MT5|hedge'
} | Select-Object TaskName, State, TaskPath, @{
    Name='Actions'; Expression={ @($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) }
}

$candidateFiles = @()
foreach ($root in 'D:\QHCELL', 'D:\QHMT5', 'C:\MT5Agent') {
    if (Test-Path -LiteralPath $root) {
        $candidateFiles += Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @('main.py','agent.py','mt5_agent.py','run_agent.ps1','cell_agent.py') } |
            Select-Object FullName, Length, LastWriteTimeUtc, @{
                Name='SHA256'; Expression={ (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
            }
    }
}

[ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    hostname = $env:COMPUTERNAME
    instances = @($instances)
    tasks = @($tasks)
    candidate_files = @($candidateFiles)
} | ConvertTo-Json -Depth 10 -Compress
