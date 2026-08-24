$ErrorActionPreference = 'Continue'
$apiKey = '7af2221c27241dd524273d2752772aa43e6b18c0187dffbf'
$rows = foreach ($item in @(
    [pscustomobject]@{ Name = 'ic'; Port = 8041 },
    [pscustomobject]@{ Name = 'exness'; Port = 8042 }
)) {
    $root = "D:\MT4LAB\terminals\$($item.Name)"
    $stateRoot = Join-Path $root 'MQL4\Files\qhbridge\state'
    $metaPath = Join-Path $stateRoot 'meta.json'
    $positionsPath = Join-Path $stateRoot 'positions.json'
    $meta = $null
    $positions = $null
    try { $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json } catch {}
    try { $positions = Get-Content -LiteralPath $positionsPath -Raw | ConvertFrom-Json } catch {}
    $health = $null
    $status = $null
    $apiPositions = $null
    $errors = @()
    try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($item.Port)/health" -TimeoutSec 3 } catch { $errors += "health: $($_.Exception.Message)" }
    try { $status = Invoke-RestMethod -Uri "http://127.0.0.1:$($item.Port)/mt5/connection/status" -Headers @{'X-API-Key'=$apiKey} -TimeoutSec 3 } catch { $errors += "status: $($_.Exception.Message)" }
    try { $apiPositions = Invoke-RestMethod -Uri "http://127.0.0.1:$($item.Port)/mt5/positions" -Headers @{'X-API-Key'=$apiKey} -TimeoutSec 3 } catch { $errors += "positions: $($_.Exception.Message)" }
    $terminalProcess = @(Get-CimInstance Win32_Process -Filter "Name='terminal.exe'" | Where-Object {
        $_.ExecutablePath -eq (Join-Path $root 'terminal.exe')
    })
    [ordered]@{
        name = $item.Name
        port = $item.Port
        task_state = [string](Get-ScheduledTask -TaskName "MT4LAB-Agent-$($item.Name)").State
        listener_pid = (Get-NetTCPConnection -LocalPort $item.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
        terminal_pids = @($terminalProcess.ProcessId)
        meta_last_write_utc = if (Test-Path $metaPath) { (Get-Item $metaPath).LastWriteTimeUtc.ToString('o') } else { $null }
        positions_last_write_utc = if (Test-Path $positionsPath) { (Get-Item $positionsPath).LastWriteTimeUtc.ToString('o') } else { $null }
        meta = $meta
        file_snapshot = [ordered]@{ boot=$positions.snapshot_boot; seq=$positions.snapshot_seq; ts=$positions.snapshot_ts; count=@($positions.positions).Count }
        health = $health
        status = $status
        api_snapshot = $apiPositions
        errors = $errors
        agent_log_tail = @(Get-Content -LiteralPath "D:\MT4LAB\agent\logs\$($item.Name).log" -Tail 30 -ErrorAction SilentlyContinue)
    }
}
[ordered]@{ checked_at=(Get-Date).ToUniversalTime().ToString('o'); instances=@($rows) } | ConvertTo-Json -Depth 10 -Compress
