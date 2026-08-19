$ErrorActionPreference = 'Stop'

$apiKeyLine = Get-Content -LiteralPath 'D:\QHCELL\cell.env' |
    Where-Object { $_ -match '^API_KEY=' } | Select-Object -First 1
if (-not $apiKeyLine) { throw 'QHCELL API key is missing' }
$headers = @{'X-API-Key' = $apiKeyLine.Substring('API_KEY='.Length).Trim()}
$result = [ordered]@{}

foreach ($port in 8061, 8063) {
    $before = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $port) -TimeoutSec 10
    $beforeHistory = 0
    if ($before.mt5_api_queue.calls.history_deals_30d) {
        $beforeHistory = [int]$before.mt5_api_queue.calls.history_deals_30d.count
    }
    $samples = @()
    foreach ($index in 1..10) {
        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        $account = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/account/info" -f $port) `
            -Headers $headers -TimeoutSec 10
        $stopwatch.Stop()
        $samples += [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 3)
    }
    $positions = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/positions" -f $port) `
        -Headers $headers -TimeoutSec 10
    $tick = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/tick/XAUUSD" -f $port) `
        -Headers $headers -TimeoutSec 10
    $after = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $port) -TimeoutSec 10
    $afterHistory = 0
    if ($after.mt5_api_queue.calls.history_deals_30d) {
        $afterHistory = [int]$after.mt5_api_queue.calls.history_deals_30d.count
    }
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -First 1
    $result[[string]$port] = [ordered]@{
        listener_pid = [int]$listener.OwningProcess
        mt5 = [bool]$after.mt5
        trade_allowed = [bool]$after.trade_allowed
        execution_pending = [int]$after.execution_queue.pending_executions
        native_queued = [int]$after.mt5_api_queue.queued
        native_running = [bool]$after.mt5_api_queue.running
        single_thread = [bool]$after.mt5_api_queue.single_thread
        account_request_ms_min = ($samples | Measure-Object -Minimum).Minimum
        account_request_ms_max = ($samples | Measure-Object -Maximum).Maximum
        history_calls_before = $beforeHistory
        history_calls_after = $afterHistory
        account_source = [string]$account.account_snapshot_source
        account_age_ms = [double]$account.account_snapshot_age_ms
        account_complete = [bool]$account.account_snapshot_complete
        history_age_ms = [double]$account.account_history_age_ms
        position_count = @($positions.positions).Count
        position_source = [string]$positions.snapshot_source
        position_stale = [bool]$positions.snapshot_stale
        tick_bid = [double]$tick.bid
        tick_ask = [double]$tick.ask
        tick_time_msc = [long]$tick.time_msc
    }
}

$hashPaths = @(
    'D:\QHMT5\runtime\releases\v1\ic\app\main.py',
    'D:\QHMT5\runtime\releases\v1\ic\app\runtime.py'
)
$hashes = Get-FileHash -Algorithm SHA256 $hashPaths
$terminals = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'terminal64.exe' -and
    ($_.CommandLine -like '*pool\s1\terminal*' -or $_.CommandLine -like '*pool\s3\terminal*')
} | Select-Object ProcessId

[ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    files = @($hashes | ForEach-Object {
        [ordered]@{path=$_.Path; sha256=$_.Hash}
    })
    bridges = $result
    terminal_pids = @($terminals | ForEach-Object { [int]$_.ProcessId })
} | ConvertTo-Json -Depth 8 -Compress
