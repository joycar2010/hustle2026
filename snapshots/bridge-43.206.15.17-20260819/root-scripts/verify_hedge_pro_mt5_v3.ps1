$ErrorActionPreference = 'Stop'

$apiKeyLine = Get-Content -LiteralPath 'D:\QHCELL\cell.env' |
    Where-Object { $_ -match '^API_KEY=' } | Select-Object -First 1
if (-not $apiKeyLine) { throw 'QHCELL API key is missing' }
$headers = @{'X-API-Key' = $apiKeyLine.Substring('API_KEY='.Length).Trim()}
$targets = @(
    [pscustomobject]@{ slot='s1'; port=8061; role='main'; instance='D:\QHCELL\pool\s1\inst' },
    [pscustomobject]@{ slot='s3'; port=8063; role='hedge'; instance='D:\QHCELL\pool\s3\inst' }
)

$results = foreach ($target in $targets) {
    $samples = foreach ($round in 1..6) {
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $positions = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/positions" -f $target.port) `
            -Headers $headers -TimeoutSec 30
        $watch.Stop()
        [ordered]@{
            round = $round
            elapsed_ms = [Math]::Round($watch.Elapsed.TotalMilliseconds, 3)
            count = @($positions.positions).Count
            snapshot_boot = $positions.snapshot_boot
            snapshot_seq = $positions.snapshot_seq
            snapshot_ts = $positions.snapshot_ts
            snapshot_age_ms = $positions.snapshot_age_ms
        }
        Start-Sleep -Milliseconds 180
    }
    $listener = Get-NetTCPConnection -LocalPort $target.port -State Listen | Select-Object -First 1
    $latestPositions = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/mt5/positions" -f $target.port) `
        -Headers $headers -TimeoutSec 30
    $signatureLines = foreach ($position in @($latestPositions.positions | Sort-Object ticket)) {
        $volume = ([double]$position.volume).ToString('R', [Globalization.CultureInfo]::InvariantCulture)
        '{0}|{1}|{2}|{3}' -f $position.ticket, $position.symbol, $position.type, $volume
    }
    $signatureBytes = [Text.Encoding]::UTF8.GetBytes(($signatureLines -join "`n"))
    $signatureSha = [Security.Cryptography.SHA256]::Create()
    try {
        $positionSignature = ([BitConverter]::ToString($signatureSha.ComputeHash($signatureBytes))).Replace('-', '')
    } finally {
        $signatureSha.Dispose()
    }
    $terminal = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'terminal64.exe' -and $_.CommandLine -like ("*pool\{0}\terminal*" -f $target.slot)
    } | Select-Object -First 1
    $errorLines = @(
        Get-Content -LiteralPath (Join-Path $target.instance 'logs\bridge.err.log') -Tail 80 -ErrorAction SilentlyContinue |
            Select-String -Pattern 'ERROR|Traceback|Exception' | ForEach-Object { [string]$_ }
    )
    [ordered]@{
        role = $target.role
        port = $target.port
        listener_pid = $listener.OwningProcess
        terminal_pid = $terminal.ProcessId
        app_version = (Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/openapi.json" -f $target.port)).info.version
        health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $target.port)
        position_signature = $positionSignature
        samples = @($samples)
        error_lines = $errorLines
    }
}

[ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    results = @($results)
} | ConvertTo-Json -Depth 10 -Compress
