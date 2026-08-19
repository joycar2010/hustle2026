$ErrorActionPreference = "Continue"
$MEDIR_IC     = "D:\MT4LAB\terminals\ic\metaeditor.exe"
$MEDIR_EX     = "D:\MT4LAB\terminals\exness\metaeditor.exe"
$MQ4_IC       = "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.mq4"
$MQ4_EX       = "D:\MT4LAB\terminals\exness\MQL4\Experts\QHBridge.mq4"
$EX4_IC       = "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.ex4"
$EX4_EX       = "D:\MT4LAB\terminals\exness\MQL4\Experts\QHBridge.ex4"
$LOG_IC       = "D:\compile_ic.log"
$LOG_EX       = "D:\compile_exness.log"

Write-Host "=== [1] 备份旧 .ex4 ==="
if (Test-Path $EX4_IC)  { Copy-Item $EX4_IC  "$EX4_IC.bak_$(Get-Date -Format 'HHmmss')" -Force }
if (Test-Path $EX4_EX)  { Copy-Item $EX4_EX  "$EX4_EX.bak_$(Get-Date -Format 'HHmmss')" -Force }

Write-Host "=== [2] MetaEditor 命令行编译 IC ==="
if (Test-Path $MEDIR_IC) {
    $p = Start-Process -FilePath $MEDIR_IC -ArgumentList "/compile:$MQ4_IC","/log:$LOG_IC" -Wait -PassThru -WindowStyle Hidden
    Write-Host "IC compile exit code: $($p.ExitCode)"
} else {
    # 尝试共用 metaeditor
    $MEDIR_IC = "D:\MT4LAB\terminals\ic\metaeditor.exe"
    if (-not (Test-Path $MEDIR_IC)) {
        Write-Host "metaeditor.exe not found in IC dir, trying terminal.exe /compile"
        $TERM_IC = "D:\MT4LAB\terminals\ic\terminal.exe"
        Start-Process $TERM_IC -ArgumentList "/compile:$MQ4_IC" -Wait -WindowStyle Hidden
    }
}

Write-Host "=== [2b] MetaEditor 命令行编译 Exness ==="
if (Test-Path $MEDIR_EX) {
    $p2 = Start-Process -FilePath $MEDIR_EX -ArgumentList "/compile:$MQ4_EX","/log:$LOG_EX" -Wait -PassThru -WindowStyle Hidden
    Write-Host "Exness compile exit code: $($p2.ExitCode)"
} else {
    $TERM_EX = "D:\MT4LAB\terminals\exness\terminal.exe"
    Start-Process $TERM_EX -ArgumentList "/compile:$MQ4_EX" -Wait -WindowStyle Hidden
}

Write-Host "=== [3] 检查编译结果 ==="
Start-Sleep -Seconds 5
foreach ($ex4 in @($EX4_IC, $EX4_EX)) {
    if (Test-Path $ex4) {
        $sz  = (Get-Item $ex4).Length
        $mtime = (Get-Item $ex4).LastWriteTime
        Write-Host "OK ${ex4} size=${sz} modified=${mtime}"
    } else {
        Write-Host "MISSING ${ex4}"
    }
}

Write-Host "=== [4] 编译日志 ==="
if (Test-Path $LOG_IC)  { Get-Content $LOG_IC  -Tail 8 | ForEach-Object { "IC_LOG: $_" } }
if (Test-Path $LOG_EX)  { Get-Content $LOG_EX  -Tail 8 | ForEach-Object { "EX_LOG: $_" } }

Write-Host "=== [5] 重启 MT4 终端(计划任务,Interactive session2) ==="
# 先强制杀掉旧的 terminal.exe 进程
$old = Get-Process -Name terminal -ErrorAction SilentlyContinue
if ($old) {
    $old | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "Killed $($old.Count) terminal process(es)"
    Start-Sleep -Seconds 4
}

# 通过计划任务在 session 2 重启(解决 session 0 无法起 GUI 的问题)
Start-ScheduledTask -TaskName "MT4LAB-Startup" -ErrorAction SilentlyContinue
Write-Host "MT4LAB-Startup task triggered"

Start-Sleep -Seconds 30

Write-Host "=== [6] 验证终端已重启 ==="
Get-Process -Name terminal -ErrorAction SilentlyContinue | Select-Object Id,Path,StartTime | Format-Table -AutoSize

Write-Host "=== [7] 验证 heartbeat.json ==="
foreach ($dir in @("ic","exness")) {
    $hb = "D:\MT4LAB\terminals\$dir\MQL4\Files\qhbridge\state\heartbeat.json"
    if (Test-Path $hb) {
        $age = [int]((Get-Date) - (Get-Item $hb).LastWriteTime).TotalSeconds
        $content = Get-Content $hb -Raw -ErrorAction SilentlyContinue
        Write-Host "${dir} heartbeat.json age=${age}s : $content"
    } else {
        Write-Host "${dir} heartbeat.json NOT FOUND (EA not loaded yet?)"
    }
}

Write-Host "=== [8] meta.json 对比 ==="
foreach ($dir in @("ic","exness")) {
    $m = "D:\MT4LAB\terminals\$dir\MQL4\Files\qhbridge\state\meta.json"
    if (Test-Path $m) {
        $age = [int]((Get-Date) - (Get-Item $m).LastWriteTime).TotalSeconds
        Write-Host "${dir} meta.json age=${age}s"
    }
}
