[CmdletBinding()]
param(
    [string]$ReleaseTag = ''
)

$ErrorActionPreference = 'Stop'
if (-not $ReleaseTag) {
    $ReleaseTag = 'no123-v116-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
}
$agentRoot = 'D:\MT4LAB\agent'
$stageRoot = 'D:\MT4LAB\stage-no123-v116'
$backupRoot = Join-Path 'D:\MT4LAB\backups' $ReleaseTag
$python = Join-Path $agentRoot 'venv\Scripts\python.exe'
$expected = @{
    main = '1382F6B1F415C0FACC39DC9FEDD0989FDEC76497B0C54E56E0EE9FEC5AD6D29B'
    source = 'D60EE4467E7ABED53BAF1E7F174E7B66571E70E72E31447C0E2537B0940C57FA'
    ic_binary = '4A6B80F64C27970F7AF8541B97B7D289A04205D82B09D5BDDB1C29DA18E45743'
    exness_binary = '954FE61BE29BE2A4686B7850ECF5CA8BC4BA95FB85A97E08F967051FCD77A58F'
}
$instances = @(
    [pscustomobject]@{Name='ic';Port=8041;Task='MT4LAB-Agent-ic';Account='31387608';Binary=$expected.ic_binary},
    [pscustomobject]@{Name='exness';Port=8042;Task='MT4LAB-Agent-exness';Account='95297401';Binary=$expected.exness_binary}
)

$run = Get-Content -LiteralPath (Join-Path $agentRoot 'run_agent.ps1')
$keyLine = $run | Where-Object { $_ -match '^\$env:API_KEY\s*=' } | Select-Object -First 1
$apiKey = ($keyLine -split "'")[1]
$headers = @{'X-API-Key'=$apiKey}

function Assert-Hash([string]$Path,[string]$ExpectedHash) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing staged file: $Path" }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $ExpectedHash) { throw "Hash mismatch for $Path`: $actual" }
}
function Get-Root([string]$Name) { "D:\MT4LAB\terminals\$Name" }

function Assert-TradeSafe {
    foreach ($instance in $instances) {
        $status = Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/mt5/connection/status" -Headers $headers -TimeoutSec 5
        $positions = Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/mt5/positions" -Headers $headers -TimeoutSec 5
        if (-not [bool]$status.connected -or [string]$status.account -ne $instance.Account) {
            throw "Port $($instance.Port) account/connection preflight failed"
        }
        if (@($positions.positions).Count -ne 0) { throw "Refusing deployment: $($instance.Name) has positions" }
        $commands = Join-Path (Get-Root $instance.Name) 'MQL4\Files\qhbridge\commands'
        if (@(Get-ChildItem -LiteralPath $commands -Filter '*.json' -File -ErrorAction SilentlyContinue).Count -ne 0) {
            throw "Refusing deployment: $($instance.Name) has pending commands"
        }
    }
    $wal = (& $python (Join-Path $agentRoot 'inspect_no123_agent_wal.py')) | ConvertFrom-Json
    foreach ($ledger in $wal.sending.PSObject.Properties) {
        if (@($ledger.Value).Count -ne 0) { throw "Refusing deployment: WAL SENDING in $($ledger.Name)" }
    }
}

function Stop-Agent($instance) {
    Stop-ScheduledTask -TaskName $instance.Task -ErrorAction SilentlyContinue
    $deadline=(Get-Date).AddSeconds(10)
    do {
        $listener=Get-NetTCPConnection -LocalPort $instance.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $listener) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ($listener.OwningProcess) { Stop-Process -Id $listener.OwningProcess -Force }
}

function Stop-Terminal([string]$Name) {
    $root=Get-Root $Name
    $rows=@(Get-CimInstance Win32_Process -Filter "Name='terminal.exe'" | Where-Object { $_.ExecutablePath -eq (Join-Path $root 'terminal.exe') })
    foreach ($row in $rows) {
        $process=Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
        if ($process) { [void]$process.CloseMainWindow() }
    }
    $deadline=(Get-Date).AddSeconds(15)
    do {
        $rows=@(Get-CimInstance Win32_Process -Filter "Name='terminal.exe'" | Where-Object { $_.ExecutablePath -eq (Join-Path $root 'terminal.exe') })
        if ($rows.Count -eq 0) { return }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    foreach ($row in $rows) { Stop-Process -Id $row.ProcessId -Force }
}

function Start-Terminal([string]$Name,[datetime]$StartedAfter,[string]$ExpectedEa) {
    $root=Get-Root $Name
    Start-Process -FilePath (Join-Path $root 'terminal.exe') -ArgumentList '/portable' -WorkingDirectory $root -WindowStyle Hidden
    $metaPath=Join-Path $root 'MQL4\Files\qhbridge\state\meta.json'
    $positionsPath=Join-Path $root 'MQL4\Files\qhbridge\state\positions.json'
    $deadline=(Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $metaItem=Get-Item -LiteralPath $metaPath
            $meta=Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
            $positions=Get-Content -LiteralPath $positionsPath -Raw | ConvertFrom-Json
            if ($metaItem.LastWriteTimeUtc -gt $StartedAfter.ToUniversalTime().AddSeconds(-2) -and
                $meta.ea -eq $ExpectedEa -and $null -ne $positions.snapshot_boot -and
                [long]$positions.snapshot_seq -ge 1) { return }
        } catch {}
    } while ((Get-Date) -lt $deadline)
    throw "$Name terminal did not publish fresh $ExpectedEa state"
}

function Start-Agent($instance) {
    Start-ScheduledTask -TaskName $instance.Task
    $deadline=(Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 400
        try {
            $health=Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/health" -TimeoutSec 2
            $status=Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/mt5/connection/status" -Headers $headers -TimeoutSec 2
            if ($health.status -eq 'ok' -and [bool]$status.connected -and [string]$status.account -eq $instance.Account) { return }
        } catch {}
    } while ((Get-Date) -lt $deadline)
    throw "Agent port $($instance.Port) did not recover"
}

$stagedMain=Join-Path $stageRoot 'main.py'
$stagedSource=Join-Path $stageRoot 'QHBridge.mq4'
Assert-Hash $stagedMain $expected.main
Assert-Hash $stagedSource $expected.source
foreach ($instance in $instances) {
    Assert-Hash (Join-Path (Get-Root $instance.Name) 'MQL4\Experts\stage_v116\QHBridge.ex4') $instance.Binary
}
& $python -m py_compile $stagedMain
if ($LASTEXITCODE -ne 0) { throw 'Staged Agent compile failed' }
Assert-TradeSafe

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $agentRoot 'main.py') -Destination (Join-Path $backupRoot 'main.py') -Force
foreach ($instance in $instances) {
    $dest=Join-Path $backupRoot $instance.Name
    $root=Get-Root $instance.Name
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'MQL4\Experts\QHBridge.mq4') -Destination $dest -Force
    Copy-Item -LiteralPath (Join-Path $root 'MQL4\Experts\QHBridge.ex4') -Destination $dest -Force
}

$deploymentStarted=(Get-Date).ToUniversalTime()
$filesDeployed=$false
try {
    foreach ($instance in $instances) { Stop-Agent $instance }
    foreach ($instance in $instances) { Stop-Terminal $instance.Name }
    Copy-Item -LiteralPath $stagedMain -Destination (Join-Path $agentRoot 'main.py') -Force
    foreach ($instance in $instances) {
        $root=Get-Root $instance.Name
        Copy-Item -LiteralPath $stagedSource -Destination (Join-Path $root 'MQL4\Experts\QHBridge.mq4') -Force
        Copy-Item -LiteralPath (Join-Path $root 'MQL4\Experts\stage_v116\QHBridge.ex4') `
            -Destination (Join-Path $root 'MQL4\Experts\QHBridge.ex4') -Force
    }
    $filesDeployed=$true
    foreach ($instance in $instances) { Start-Terminal $instance.Name $deploymentStarted 'QHBridge/1.16' }
    foreach ($instance in $instances) { Start-Agent $instance }
} catch {
    $failure=$_
    if ($filesDeployed) {
        foreach ($instance in $instances) { try { Stop-Agent $instance; Stop-Terminal $instance.Name } catch {} }
        Copy-Item -LiteralPath (Join-Path $backupRoot 'main.py') -Destination (Join-Path $agentRoot 'main.py') -Force
        foreach ($instance in $instances) {
            $root=Get-Root $instance.Name; $src=Join-Path $backupRoot $instance.Name
            Copy-Item -LiteralPath (Join-Path $src 'QHBridge.mq4') -Destination (Join-Path $root 'MQL4\Experts\QHBridge.mq4') -Force
            Copy-Item -LiteralPath (Join-Path $src 'QHBridge.ex4') -Destination (Join-Path $root 'MQL4\Experts\QHBridge.ex4') -Force
        }
        foreach ($instance in $instances) { try { Start-Terminal $instance.Name (Get-Date).ToUniversalTime() 'QHBridge/1.15' } catch {} }
        foreach ($instance in $instances) { try { Start-Agent $instance } catch {} }
    }
    throw $failure
}

$verification=foreach ($instance in $instances) {
    $root=Get-Root $instance.Name
    $deadline=(Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        $historyDeals=Join-Path $root 'MQL4\Files\qhbridge\state\history_deals.json'
        $historyOrders=Join-Path $root 'MQL4\Files\qhbridge\state\history_orders.json'
    } while ((-not (Test-Path $historyDeals) -or -not (Test-Path $historyOrders)) -and (Get-Date) -lt $deadline)
    if (-not (Test-Path $historyDeals) -or -not (Test-Path $historyOrders)) { throw "$($instance.Name) history files were not exported" }
    $positions=Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/mt5/positions" -Headers $headers -TimeoutSec 5
    $deals=Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/mt5/history/deals?days=30" -Headers $headers -TimeoutSec 15
    $orders=Invoke-RestMethod "http://127.0.0.1:$($instance.Port)/mt5/history/orders?days=30" -Headers $headers -TimeoutSec 15
    if (@($positions.positions).Count -ne 0) { throw 'Positions changed during deployment' }
    [ordered]@{
        name=$instance.Name;port=$instance.Port;account=$instance.Account;positions=0
        ea=(Get-Content (Join-Path $root 'MQL4\Files\qhbridge\state\meta.json') -Raw|ConvertFrom-Json).ea
        history_deals=@($deals.deals).Count;history_orders=@($orders.orders).Count
        source_hash=(Get-FileHash (Join-Path $root 'MQL4\Experts\QHBridge.mq4') -Algorithm SHA256).Hash
        binary_hash=(Get-FileHash (Join-Path $root 'MQL4\Experts\QHBridge.ex4') -Algorithm SHA256).Hash
    }
}
[ordered]@{ok=$true;release=$ReleaseTag;backup=$backupRoot;instances=@($verification)} | ConvertTo-Json -Depth 7 -Compress
