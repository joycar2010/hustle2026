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
$prevSig = if (Test-Path $dispatchState) { (Get-Content $dispatchState -Raw -ErrorAction SilentlyContinue).Trim() } else { $null }
# Hard cooldown: even if sig changes, don't fire desktop popup more than once per 30 min.
# (Feishu/backend still gets every alert via the POST below for audit.)
$POPUP_COOLDOWN_S = 1800
$lastDispatchTs = if (Test-Path $dispatchState) { (Get-Item $dispatchState).LastWriteTime } else { [datetime]::MinValue }
$secsSinceLast = ((Get-Date) - $lastDispatchTs).TotalSeconds
if ($prevSig -eq $sig.Trim()) {
    Write-Log 'INFO' ("same failure set - suppressed: " + $sig)
    exit 0
}
$popupAllowed = ($secsSinceLast -ge $POPUP_COOLDOWN_S)

$targets = ($alert.failures | ForEach-Object { $_.target }) -join ', '
$title = 'MT5 Infra Alert'
$body = "Host " + $alert.host + " failures: " + $targets

# 1. Desktop toast (BurntToast if available, else msg.exe fallback)
# Skip popup if within cooldown window (Feishu still gets it below)
$toastSent = $false
if (-not $popupAllowed) {
    Write-Log 'INFO' ("popup suppressed by 30min cooldown ({0:N0}s since last)" -f $secsSinceLast)
} else {
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
