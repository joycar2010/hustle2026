# MT5 Infra Alert Sender — consumes healthcheck.alert.json and dispatches:
#   1. Desktop toast (BurntToast if available, else msg.exe fallback)
#   2. Backend POST /api/v1/mt5-infra/alert (Feishu card + admin WS fanout)
# Idempotent: last-dispatched signature stored to avoid re-firing for the same failure set.

$ErrorActionPreference = 'Continue'

$alertFile = 'C:\MT5Agent\logs\healthcheck.alert.json'
$dispatchState = 'C:\MT5Agent\logs\healthcheck.alert.dispatched'
$logFile = 'C:\MT5Agent\logs\healthcheck.log'

$BACKEND_URL = 'https://admin.hustle2026.xyz/api/v1/mt5-infra/alert'
$API_KEY = 'HustleXAU_MT5_Agent_Key_2026'

function Write-Log([string]$level, [string]$msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value "$ts [ALERT-$level] $msg" -Encoding utf8
}

if (-not (Test-Path $alertFile)) {
    Write-Log 'INFO' 'no alert file - nothing to do'
    exit 0
}

try {
    $alertRaw = Get-Content $alertFile -Raw
    $alert = $alertRaw | ConvertFrom-Json
} catch {
    Write-Log 'ERROR' ("alert parse failed: " + $_.Exception.Message)
    exit 1
}

$sig = (($alert.failures | ForEach-Object { $_.target }) | Sort-Object) -join '|'
$prevSig = if (Test-Path $dispatchState) { Get-Content $dispatchState -Raw -ErrorAction SilentlyContinue } else { $null }
if ($prevSig -eq $sig) {
    Write-Log 'INFO' ("same failure set - suppressed: " + $sig)
    exit 0
}

$targets = ($alert.failures | ForEach-Object { $_.target }) -join ', '
$title = 'MT5 Infra Alert'
$body = "Host " + $alert.host + " failures: " + $targets

# 1. Desktop toast
$toastSent = $false
try {
    if (Get-Module -ListAvailable -Name BurntToast -ErrorAction SilentlyContinue) {
        Import-Module BurntToast -ErrorAction Stop
        New-BurntToastNotification -Text $title, $body
        $toastSent = $true
        Write-Log 'INFO' 'BurntToast sent'
    }
} catch {
    Write-Log 'WARN' ("BurntToast failed: " + $_.Exception.Message)
}
if (-not $toastSent) {
    try {
        $nl = [char]10
        $msgText = $title + $nl + $body
        Start-Process -WindowStyle Hidden -FilePath 'msg.exe' -ArgumentList '*','/TIME:10',$msgText -ErrorAction Stop
        Write-Log 'INFO' 'msg.exe dispatched'
    } catch {
        Write-Log 'WARN' ("msg.exe failed: " + $_.Exception.Message)
    }
}

# 2. Backend POST (Feishu + admin WS)
try {
    $headers = @{ 'X-API-Key' = $API_KEY; 'Content-Type' = 'application/json' }
    $resp = Invoke-RestMethod -Uri $BACKEND_URL -Method Post -Headers $headers -Body $alertRaw -TimeoutSec 8
    if ($resp -and $resp.ok) {
        Write-Log 'INFO' ("backend ok feishu=" + $resp.feishu.success)
    } else {
        Write-Log 'WARN' ("backend returned: " + ($resp | ConvertTo-Json -Compress -Depth 3))
    }
} catch {
    Write-Log 'ERROR' ("backend POST failed: " + $_.Exception.Message)
}

Set-Content -Path $dispatchState -Value $sig -Encoding utf8
