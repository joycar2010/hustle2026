Write-Host "=== P0-B: 重启 8041 agent 加载新 filebridge.py ==="
$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($p41) { taskkill /F /PID $p41 2>&1; Start-Sleep -Seconds 3 }
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 12

$new41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
Write-Host "new 8041 PID=$new41"
$key = "<REDACTED_API_KEY>"
try {
    $s = Invoke-RestMethod "http://127.0.0.1:8041/mt5/connection/status" -Headers @{"x-api-key"=$key} -TimeoutSec 10
    Write-Host "conn=$($s.connected) healthy=$($s.healthy) last_ok=$($s.last_ok_at)"
} catch { Write-Host "status fail: $_" }

Write-Host ""
Write-Host "=== P0-B: EA meta.json 停止写入根因调查 ==="
# 检查 filebridge.py 当前生效的 STALE_HEARTBEAT_SEC
$grep = Select-String -Path D:\MT4LAB\agent\filebridge.py -Pattern "STALE_HEARTBEAT_SEC|STATE_STALE_SEC"
$grep | Select-Object -First 8 | ForEach-Object { $_.Line }

Write-Host ""
Write-Host "=== QHBridge.mq4 关键代码:检查 OnTimer 写文件的条件 ==="
# 查找 EA 写 meta.json 的代码段
$ea_paths = @(
    "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.mq4",
    "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.ex4"
)
foreach ($p in $ea_paths) {
    if (Test-Path $p) {
        Write-Host "Found: $p ($((Get-Item $p).Length) bytes)"
    }
}
# 搜索 mq4 源码中 meta 写入条件
$mq4 = "D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.mq4"
if (Test-Path $mq4) {
    Get-Content $mq4 | Select-String -Pattern "meta|account|connected|login|AccountNumber|WriteFile" | Select-Object -First 20 | ForEach-Object { $_.Line }
}

Write-Host ""
Write-Host "=== 当前 meta.json 新鲜度 ==="
$f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
if (Test-Path $f) {
    $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
    Write-Host "meta.json age=${age}s"
    Get-Content $f -Raw
}
