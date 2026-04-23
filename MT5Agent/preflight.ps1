# MT5WindowsAgent Preflight Check
# Called by nssm Pre-Start hook before launching python.exe main_v3.py
# Exit 0 => let nssm proceed to start main process
# Exit non-zero => nssm aborts start, SCM failure policy will retry

$ErrorActionPreference = 'Continue'
$logFile = 'C:\MT5Agent\preflight.log'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Log($msg) {
    $line = "$stamp [preflight] $msg"
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

Log '--- preflight start ---'

$failed = @()

# 1. Python interpreter
$python = 'C:\Program Files\Python311\python.exe'
if (-not (Test-Path $python)) { $failed += "python_missing:$python" }

# 2. Main script
$main = 'C:\MT5Agent\main_v3.py'
if (-not (Test-Path $main)) { $failed += "main_missing:$main" }

# 3. nssm (used by Agent to manage bridges)
if (-not (Test-Path 'C:\nssm\nssm.exe')) { $failed += 'nssm_missing:C:\nssm\nssm.exe' }

# 4. Agent listen port 8765 must be free (another process leftover would prevent bind)
try {
    $conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pidVal = $conn[0].OwningProcess
        $proc = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
        $procName = if ($proc) { $proc.ProcessName } else { 'unknown' }
        $failed += "port_8765_busy:pid=$pidVal name=$procName"
    }
} catch {
    Log "port check error: $_"
}

# 5. Working directory
if (-not (Test-Path 'C:\MT5Agent')) { $failed += 'workdir_missing:C:\MT5Agent' }

if ($failed.Count -gt 0) {
    foreach ($f in $failed) { Log "FAIL $f" }
    Log 'preflight result: FAIL'
    exit 1
}

Log 'preflight result: OK'
exit 0
