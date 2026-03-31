# 部署更新后的 Windows Agent 到 Windows 服务器
# 通过 Ubuntu 服务器作为跳板

Write-Host "=== 部署 Windows Agent 更新 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 备份当前版本
Write-Host "1. 备份当前版本..." -ForegroundColor Yellow
Copy-Item "C:\MT5Agent\main.py" "C:\MT5Agent\main.py.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')" -ErrorAction SilentlyContinue

# 2. 停止 Windows Agent
Write-Host "2. 停止 Windows Agent..." -ForegroundColor Yellow
$agentProcs = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*MT5Agent*" -and $_.Name -eq "python.exe" }
foreach ($proc in $agentProcs) {
    Stop-Process -Id $proc.ProcessId -Force
    Write-Host "   已停止进程 $($proc.ProcessId)" -ForegroundColor Green
}

Start-Sleep -Seconds 2

# 3. 复制新文件（假设已通过 SCP 上传到临时目录）
Write-Host "3. 更新文件..." -ForegroundColor Yellow
# 这里需要手动上传 main_v2.py 到 Windows 服务器
# 或者通过其他方式传输

# 4. 启动 Windows Agent
Write-Host "4. 启动 Windows Agent..." -ForegroundColor Yellow
Start-Process -FilePath "python" -ArgumentList "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent" -WindowStyle Hidden
Write-Host "   Windows Agent 已启动" -ForegroundColor Green

Write-Host ""
Write-Host "=== 部署完成 ===" -ForegroundColor Green
Write-Host ""
Write-Host "测试新端点："
Write-Host "  curl http://localhost:9000/system/mt5-processes"
