# 部署修复后的 Windows Agent
Write-Host "=== 部署 Windows Agent 修复 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 备份当前版本
Write-Host "1. 备份当前版本..." -ForegroundColor Yellow
$backupFile = "C:\MT5Agent\main.py.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item "C:\MT5Agent\main.py" $backupFile -ErrorAction SilentlyContinue
Write-Host "   备份保存到: $backupFile" -ForegroundColor Green
Write-Host ""

# 2. 停止 Windows Agent
Write-Host "2. 停止 Windows Agent..." -ForegroundColor Yellow
$agentProcs = Get-WmiObject Win32_Process | Where-Object {
    $_.CommandLine -like "*MT5Agent*" -and $_.Name -eq "python.exe"
}

if ($agentProcs) {
    foreach ($proc in $agentProcs) {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Host "   已停止进程 $($proc.ProcessId)" -ForegroundColor Green
    }
} else {
    Write-Host "   没有找到运行中的 Windows Agent" -ForegroundColor Yellow
}

Start-Sleep -Seconds 2
Write-Host ""

# 3. 复制新文件
Write-Host "3. 更新文件..." -ForegroundColor Yellow
# 假设新文件已通过 SCP 上传到 C:\Temp\main.py
if (Test-Path "C:\Temp\main.py") {
    Copy-Item "C:\Temp\main.py" "C:\MT5Agent\main.py" -Force
    Write-Host "   文件已更新" -ForegroundColor Green
} else {
    Write-Host "   错误: 找不到新文件 C:\Temp\main.py" -ForegroundColor Red
    Write-Host "   请先上传文件到 C:\Temp\main.py" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 4. 启动 Windows Agent
Write-Host "4. 启动 Windows Agent..." -ForegroundColor Yellow
Start-Process -FilePath "python" `
    -ArgumentList "C:\MT5Agent\main.py" `
    -WorkingDirectory "C:\MT5Agent" `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

# 验证启动
$newProc = Get-WmiObject Win32_Process | Where-Object {
    $_.CommandLine -like "*MT5Agent*" -and $_.Name -eq "python.exe"
}

if ($newProc) {
    Write-Host "   Windows Agent 已启动 (PID: $($newProc.ProcessId))" -ForegroundColor Green
} else {
    Write-Host "   警告: 无法确认 Windows Agent 是否启动" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "=== 部署完成 ===" -ForegroundColor Green
Write-Host ""
Write-Host "测试修复："
Write-Host "  1. 检查服务: curl http://localhost:9000/"
Write-Host "  2. 停止实例: curl -X POST http://localhost:9000/instances/8002/stop"
Write-Host "  3. 启动实例: curl -X POST http://localhost:9000/instances/8002/start"
Write-Host "  4. 检查进程: Get-Process -Name terminal64"
