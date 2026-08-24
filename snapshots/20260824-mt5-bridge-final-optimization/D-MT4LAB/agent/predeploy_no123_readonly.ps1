$ErrorActionPreference = 'Stop'

$run = Get-Content -LiteralPath 'D:\MT4LAB\agent\run_agent.ps1'
$keyLine = $run | Where-Object { $_ -match '^\$env:API_KEY\s*=' } | Select-Object -First 1
$apiKey = ($keyLine -split "'")[1]

$rows = foreach ($port in 8041, 8042) {
    $positions = Invoke-RestMethod -Uri "http://127.0.0.1:$port/mt5/positions" `
        -Headers @{'X-API-Key' = $apiKey} -TimeoutSec 5
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/mt5/connection/status" `
        -Headers @{'X-API-Key' = $apiKey} -TimeoutSec 5
    $items = @($positions.positions)
    $instance = if ($port -eq 8041) { 'ic' } else { 'exness' }
    $filesDir = "D:\MT4LAB\terminals\$instance\MQL4\Files\qhbridge"
    [pscustomobject]@{
        Port = $port
        Connected = [bool]$status.connected
        Account = $status.account
        PositionCount = $items.Count
        Tickets = @($items | ForEach-Object { $_.ticket })
        PendingCommands = @(
            Get-ChildItem -LiteralPath (Join-Path $filesDir 'commands') `
                -Filter '*.json' -File -ErrorAction SilentlyContinue
        ).Count
    }
}

$rows | ConvertTo-Json -Depth 4 -Compress
