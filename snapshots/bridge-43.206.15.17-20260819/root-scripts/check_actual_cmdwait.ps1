$key = "<REDACTED_API_KEY>"

Write-Host "=== 8041/8042 listener PIDs ==="
$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$p42 = (Get-NetTCPConnection -LocalPort 8042 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "8041 PID=$p41  8042 PID=$p42"

Write-Host "`n=== CMD_WAIT_SEC from process env (WMI) ==="
foreach ($pid_val in @($p41, $p42)) {
    if ($pid_val) {
        $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$pid_val").CommandLine
        Write-Host "PID=${pid_val}: $cmdline"
        # read env from process handle
        try {
            $proc = [System.Diagnostics.Process]::GetProcessById([int]$pid_val)
            # can't read other process env easily in PS5.1 without extra tools
            # try reading from /proc style via Get-Process MainModule
            Write-Host "  Path: $($proc.MainModule.FileName)"
        } catch { Write-Host "  path read FAIL" }
    }
}

Write-Host "`n=== agents logs (last 5 lines each) ==="
Get-Content "D:\MT4LAB\agent\logs\ic.log" -Tail 5 -ErrorAction SilentlyContinue | ForEach-Object { "ic: $_" }
Get-Content "D:\MT4LAB\agent\logs\exness.log" -Tail 5 -ErrorAction SilentlyContinue | ForEach-Object { "ex: $_" }

Write-Host "`n=== scheduled task actions ==="
$t_ic = Get-ScheduledTask -TaskName "MT4LAB-Agent-ic" -ErrorAction SilentlyContinue
$t_ex = Get-ScheduledTask -TaskName "MT4LAB-Agent-exness" -ErrorAction SilentlyContinue
if ($t_ic) { $t_ic.Actions | Select-Object Execute,Arguments | Format-List }
if ($t_ex) { $t_ex.Actions | Select-Object Execute,Arguments | Format-List }

Write-Host "`n=== CMD_WAIT_SEC in bridge (via env endpoint if exists) ==="
try {
    $r = Invoke-RestMethod "http://127.0.0.1:8041/env" -Headers @{"x-api-key"=$key} -TimeoutSec 5
    $r.CMD_WAIT_SEC
} catch {
    # try /mt5/config
    try { Invoke-RestMethod "http://127.0.0.1:8041/config" -Headers @{"x-api-key"=$key} -TimeoutSec 5 | ConvertTo-Json -Compress } catch { "no env/config endpoint" }
}
