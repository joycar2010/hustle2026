# 完整测试 MT5 实例启动（带 GUI）

Write-Host "=== MT5 实例启动测试（GUI 模式） ===" -ForegroundColor Cyan
Write-Host ""

# 1. 停止所有 MT5 和桥接服务
Write-Host "1. 停止所有进程..." -ForegroundColor Yellow
Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*8002*"
} | Stop-Process -Force
Start-Sleep -Seconds 2
Write-Host "   所有进程已停止" -ForegroundColor Green
Write-Host ""

# 2. 通过 API 启动实例
Write-Host "2. 通过 Windows Agent API 启动实例 8002..." -ForegroundColor Yellow
$response = Invoke-RestMethod -Uri "http://localhost:9000/instances/8002/start" -Method Post
Write-Host "   响应: $($response | ConvertTo-Json)" -ForegroundColor Green
Write-Host ""

# 3. 等待启动
Write-Host "3. 等待服务启动..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
Write-Host ""

# 4. 检查进程
Write-Host "4. 检查进程状态..." -ForegroundColor Yellow

$mt5Procs = Get-Process -Name terminal64 -ErrorAction SilentlyContinue
if ($mt5Procs) {
    Write-Host "   ✓ MT5 进程已启动:" -ForegroundColor Green
    foreach ($proc in $mt5Procs) {
        $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)"
        Write-Host "     PID: $($proc.Id)" -ForegroundColor White
        Write-Host "     路径: $($wmi.ExecutablePath)" -ForegroundColor White
        Write-Host "     启动时间: $($proc.StartTime)" -ForegroundColor White

        # 检查是否有窗口
        $hasWindow = $proc.MainWindowHandle -ne 0
        if ($hasWindow) {
            Write-Host "     窗口: ✓ 有 GUI 窗口 (Handle: $($proc.MainWindowHandle))" -ForegroundColor Green
        } else {
            Write-Host "     窗口: ✗ 无 GUI 窗口（无头模式）" -ForegroundColor Red
        }
        Write-Host ""
    }
} else {
    Write-Host "   ✗ MT5 进程未启动" -ForegroundColor Red
}

$bridgeProcs = Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue
if ($bridgeProcs) {
    Write-Host "   ✓ 桥接服务已启动 (PID: $($bridgeProcs.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "   ✗ 桥接服务未启动" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 测试完成 ===" -ForegroundColor Cyan
