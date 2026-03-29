# Windows Agent 诊断脚本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MT5 Windows Agent 诊断" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查进程
Write-Host "[1] 检查 Python 进程..." -ForegroundColor Yellow
$pythonProcs = Get-Process -Name python -ErrorAction SilentlyContinue
if ($pythonProcs) {
    Write-Host "找到 $($pythonProcs.Count) 个 Python 进程" -ForegroundColor Green
    $pythonProcs | Select-Object Id, CPU, WorkingSet, StartTime | Format-Table
} else {
    Write-Host "未找到 Python 进程！Agent 可能未运行" -ForegroundColor Red
}

# 2. 检查端口监听
Write-Host "[2] 检查 9000 端口监听..." -ForegroundColor Yellow
$listening = netstat -an | Select-String "0.0.0.0:9000.*LISTENING"
if ($listening) {
    Write-Host "端口 9000 正在监听" -ForegroundColor Green
    Write-Host $listening
} else {
    Write-Host "端口 9000 未监听！" -ForegroundColor Red
}

# 3. 检查防火墙规则
Write-Host "[3] 检查防火墙规则..." -ForegroundColor Yellow
$fwRule = Get-NetFirewallRule -DisplayName "MT5 Windows Agent" -ErrorAction SilentlyContinue
if ($fwRule) {
    Write-Host "防火墙规则已配置" -ForegroundColor Green
    $fwRule | Select-Object DisplayName, Enabled, Direction, Action | Format-Table
} else {
    Write-Host "防火墙规则未找到" -ForegroundColor Red
}

# 4. 测试本地连接
Write-Host "[4] 测试本地 HTTP 连接..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9000/" -TimeoutSec 3 -UseBasicParsing
    Write-Host "本地连接成功！" -ForegroundColor Green
    Write-Host "状态码: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "响应: $($response.Content)" -ForegroundColor Green
} catch {
    Write-Host "本地连接失败: $($_.Exception.Message)" -ForegroundColor Red
}

# 5. 检查 Agent 配置文件
Write-Host "[5] 检查 Agent 配置..." -ForegroundColor Yellow
if (Test-Path "C:\MT5Agent\instances.json") {
    Write-Host "配置文件存在: C:\MT5Agent\instances.json" -ForegroundColor Green
    $config = Get-Content "C:\MT5Agent\instances.json" -Raw
    Write-Host "配置内容: $config"
} else {
    Write-Host "配置文件不存在" -ForegroundColor Yellow
}

# 6. 检查 Agent 主程序
Write-Host "[6] 检查 Agent 主程序..." -ForegroundColor Yellow
if (Test-Path "C:\MT5Agent\main.py") {
    Write-Host "主程序存在: C:\MT5Agent\main.py" -ForegroundColor Green
} else {
    Write-Host "主程序不存在！" -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "诊断完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
