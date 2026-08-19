$ErrorActionPreference = "Continue"
Write-Host "=== [1] 直接kill 8041/8042端口进程 ==="
$pids8041 = netstat -ano | findstr ":8041 " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
$pids8042 = netstat -ano | findstr ":8042 " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
Write-Host "8041 PIDs: $pids8041"
Write-Host "8042 PIDs: $pids8042"
foreach ($pid in ($pids8041 + $pids8042)) {
    if ($pid -match '^\d+$') {
        Write-Host "Kill PID $pid"
        taskkill /F /PID $pid 2>&1
    }
}
Start-Sleep -Seconds 3

Write-Host "`n=== [2] 验证端口已释放 ==="
netstat -ano | findstr ":8041 :8042 " | Select-String "LISTEN"

Write-Host "`n=== [3] 用run_agent.ps1启动(包含CMD_WAIT_SEC=30/20) ==="
# IC
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance ic -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 2
# Exness
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File D:\MT4LAB\agent\run_agent.ps1 -Instance exness -Portable" -WindowStyle Hidden
Start-Sleep -Seconds 15

Write-Host "`n=== [4] 验证新进程 ==="
netstat -ano | findstr ":8041 " | Select-String "LISTEN"
netstat -ano | findstr ":8042 " | Select-String "LISTEN"

$new8041 = netstat -ano | findstr ":8041 " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1
$new8042 = netstat -ano | findstr ":8042 " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1
Write-Host "8041 new PID: $new8041"
Write-Host "8042 new PID: $new8042"
if ($new8041 -match '^\d+$') {
    (Get-CimInstance Win32_Process -Filter "ProcessId=$new8041").CommandLine
    # 读CMD_WAIT_SEC环境变量
    $procEnv = (Get-CimInstance Win32_Process -Filter "ProcessId=$new8041").GetRelated("Win32_EnvironmentSetting")
    Write-Host "CMD_WAIT check:"
    Get-Item "Env:CMD_WAIT_SEC" -ErrorAction SilentlyContinue
}

Write-Host "`n=== [5] health check ==="
Start-Sleep -Seconds 3
try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8041/health" -TimeoutSec 5; $h | ConvertTo-Json -Compress } catch { "8041 FAIL" }
try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8042/health" -TimeoutSec 5; $h | ConvertTo-Json -Compress } catch { "8042 FAIL" }
