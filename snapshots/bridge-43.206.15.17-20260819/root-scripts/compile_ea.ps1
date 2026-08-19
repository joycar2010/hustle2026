$ErrorActionPreference = "Continue"
$MQ4_IC = "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.mq4"
$MQ4_EX = "D:\MT4LAB\terminals\exness\MQL4\Experts\QHBridge.mq4"
$EX4_IC = "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.ex4"
$EX4_EX = "D:\MT4LAB\terminals\exness\MQL4\Experts\QHBridge.ex4"
$LOG_IC = "D:\compile_ic.log"
$LOG_EX = "D:\compile_exness.log"

Write-Host "[1] backup old .ex4"
foreach ($f in @($EX4_IC, $EX4_EX)) {
    if (Test-Path $f) { Copy-Item $f "$f.bak" -Force; Write-Host "  backed up $f" }
}

Write-Host "[2] compile IC"
$me_ic = "D:\MT4LAB\terminals\ic\metaeditor.exe"
if (-not (Test-Path $me_ic)) { $me_ic = "D:\MT4LAB\terminals\ic\terminal.exe" }
Write-Host "  using: $me_ic"
$p = Start-Process -FilePath $me_ic -ArgumentList "/compile:$MQ4_IC","/log:$LOG_IC" -Wait -PassThru -WindowStyle Hidden
Write-Host "  exit=$($p.ExitCode)"

Write-Host "[3] compile Exness"
$me_ex = "D:\MT4LAB\terminals\exness\metaeditor.exe"
if (-not (Test-Path $me_ex)) { $me_ex = "D:\MT4LAB\terminals\exness\terminal.exe" }
Write-Host "  using: $me_ex"
$p2 = Start-Process -FilePath $me_ex -ArgumentList "/compile:$MQ4_EX","/log:$LOG_EX" -Wait -PassThru -WindowStyle Hidden
Write-Host "  exit=$($p2.ExitCode)"

Start-Sleep -Seconds 5

Write-Host "[4] check .ex4 files"
foreach ($f in @($EX4_IC, $EX4_EX)) {
    if (Test-Path $f) {
        $sz = (Get-Item $f).Length
        $mt = (Get-Item $f).LastWriteTime
        Write-Host "  OK $f  size=$sz  mod=$mt"
    } else {
        Write-Host "  MISSING $f"
    }
}

Write-Host "[5] compile logs"
if (Test-Path $LOG_IC) { Get-Content $LOG_IC -Tail 6 | ForEach-Object { "  IC: $_" } }
if (Test-Path $LOG_EX) { Get-Content $LOG_EX -Tail 6 | ForEach-Object { "  EX: $_" } }

Write-Host "[6] kill terminal processes"
$old = Get-Process -Name terminal -ErrorAction SilentlyContinue
if ($old) { $old | Stop-Process -Force; Write-Host "  killed $($old.Count)"; Start-Sleep 4 }

Write-Host "[7] restart via MT4LAB-Startup task (session2)"
Start-ScheduledTask -TaskName "MT4LAB-Startup" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 35

Write-Host "[8] verify terminals"
Get-Process -Name terminal -ErrorAction SilentlyContinue | Select-Object Id,StartTime,Path | Format-Table -AutoSize

Write-Host "[9] verify heartbeat.json"
foreach ($dir in @("ic", "exness")) {
    $hb = "D:\MT4LAB\terminals\$dir\MQL4\Files\qhbridge\state\heartbeat.json"
    if (Test-Path $hb) {
        $age = [int]((Get-Date) - (Get-Item $hb).LastWriteTime).TotalSeconds
        $content = Get-Content $hb -Raw -ErrorAction SilentlyContinue
        Write-Host "  $dir heartbeat age=${age}s  $content"
    } else {
        Write-Host "  $dir heartbeat.json NOT FOUND"
    }
}

Write-Host "[10] meta.json ages"
foreach ($dir in @("ic", "exness")) {
    $m = "D:\MT4LAB\terminals\$dir\MQL4\Files\qhbridge\state\meta.json"
    if (Test-Path $m) {
        $age = [int]((Get-Date) - (Get-Item $m).LastWriteTime).TotalSeconds
        Write-Host "  $dir meta.json age=${age}s"
    }
}
