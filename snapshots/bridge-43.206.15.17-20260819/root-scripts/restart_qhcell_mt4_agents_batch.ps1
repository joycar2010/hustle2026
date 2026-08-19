param(
    [int[]]$Ports = @(8065, 8066, 8067, 8068)
)

$ErrorActionPreference = "Stop"

$agentDir = "D:\MT4LAB\agent"
$pythonExe = "D:\MT4LAB\agent\venv\Scripts\python.exe"
$cellEnv = "D:\QHCELL\cell.env"
$slotByPort = @{
    8065 = "m1"
    8066 = "m2"
    8067 = "m3"
    8068 = "m4"
}

$apiKeyLine = Get-Content -LiteralPath $cellEnv |
    Where-Object { $_.StartsWith("API_KEY=") } |
    Select-Object -First 1
if (-not $apiKeyLine) {
    throw "API_KEY is missing from $cellEnv"
}
$apiKey = $apiKeyLine.Substring("API_KEY=".Length)

function Get-PositionSnapshot([int]$Port) {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/mt5/positions" `
        -Headers @{"X-API-Key" = $apiKey} -TimeoutSec 10
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
    [ordered]@{ count = @($response.positions).Count; signature = $signature }
}

$positionBefore = [ordered]@{}
foreach ($port in $Ports) {
    $slot = $slotByPort[$port]
    $commands = "D:\QHCELL\pool\$slot\terminal\MQL4\Files\qhbridge\commands"
    if (@(Get-ChildItem -LiteralPath $commands -Filter '*.json' -File -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "Refusing restart: port $port has pending terminal commands"
    }
    $positionBefore[[string]$port] = Get-PositionSnapshot $port
}

$targets = foreach ($port in $Ports) {
    if (-not $slotByPort.ContainsKey($port)) {
        throw "Unsupported MT4 Agent port: $port"
    }
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop |
        Select-Object -First 1
    $worker = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if (-not $worker -or $worker.CommandLine -notlike "*uvicorn main:app*--port $port*") {
        throw "Port $port is not owned by the expected MT4 Agent"
    }
    $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$($worker.ParentProcessId)"
    [pscustomobject]@{
        Port = $port
        Slot = $slotByPort[$port]
        WorkerPid = [int]$worker.ProcessId
        LauncherPid = if ($launcher -and $launcher.CommandLine -like "*uvicorn main:app*--port $port*") {
            [int]$launcher.ProcessId
        } else {
            $null
        }
    }
}

foreach ($target in $targets) {
    Stop-Process -Id $target.WorkerPid -Force -ErrorAction Stop
    if ($target.LauncherPid) {
        Stop-Process -Id $target.LauncherPid -Force -ErrorAction SilentlyContinue
    }
}

$deadline = (Get-Date).AddSeconds(10)
do {
    $remaining = @(
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in $Ports }
    )
    if (-not $remaining) { break }
    Start-Sleep -Milliseconds 100
} while ((Get-Date) -lt $deadline)
if ($remaining) {
    throw "Old MT4 Agent listeners did not stop: $($remaining.LocalPort -join ',')"
}

$started = foreach ($target in $targets) {
    $filesDir = "D:\QHCELL\pool\$($target.Slot)\terminal\MQL4\Files\qhbridge"
    if (-not (Test-Path -LiteralPath $filesDir)) {
        throw "Terminal bridge directory is missing: $filesDir"
    }
    $env:API_KEY = $apiKey
    $env:INSTANCE_NAME = "qhcell-$($target.Slot)"
    $env:TERMINAL_FILES_DIR = $filesDir
    $env:SERVICE_PORT = [string]$target.Port
    $logDir = "D:\QHCELL\pool\$($target.Slot)\logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $process = Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", [string]$target.Port) `
        -WorkingDirectory $agentDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "agent.hot.out.log") `
        -RedirectStandardError (Join-Path $logDir "agent.hot.err.log") `
        -PassThru
    [pscustomobject]@{
        Port = $target.Port
        Slot = $target.Slot
        LauncherPid = $process.Id
    }
}

$deadline = (Get-Date).AddSeconds(30)
do {
    $listeners = @(
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in $Ports }
    )
    if ($listeners.Count -eq $Ports.Count) { break }
    Start-Sleep -Milliseconds 250
} while ((Get-Date) -lt $deadline)
if ($listeners.Count -ne $Ports.Count) {
    throw "New MT4 Agent listeners did not become ready"
}

$result = foreach ($port in $Ports) {
    $openApi = Invoke-RestMethod -Uri "http://127.0.0.1:$port/openapi.json" -TimeoutSec 5
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 5
    if ([int]$health.execution_queue.max_pending_executions -ne 32) {
        throw "MT4 Agent port $port did not load execution capacity 32"
    }
    $positionAfter = Get-PositionSnapshot $port
    if ($positionAfter.count -ne $positionBefore[[string]$port].count -or
        $positionAfter.signature -ne $positionBefore[[string]$port].signature) {
        throw "Position signature changed while restarting MT4 Agent port $port"
    }
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port | Select-Object -First 1
    [pscustomobject]@{
        Port = $port
        Instance = $health.instance
        Login = [string]$health.login
        Connected = [bool]$health.mt5
        TradeAllowed = $health.trade_allowed
        QueueCapacity = $health.execution_queue.max_pending_executions
        Positions = $positionAfter
        AckOnly = $openApi.components.schemas.OrderRequest.properties.PSObject.Properties.Name -contains "ack_only"
        WorkerPid = [int]$listener.OwningProcess
    }
}

$result | Sort-Object Port | ConvertTo-Json -Depth 5
