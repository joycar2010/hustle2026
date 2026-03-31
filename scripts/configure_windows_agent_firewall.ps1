# Windows Agent 防火墙配置脚本
# 用途：允许端口 9000 的入站连接，使 Ubuntu 服务器可以访问 Windows Agent

Write-Host "=== Windows Agent 防火墙配置 ===" -ForegroundColor Cyan

# 1. 检查当前防火墙规则
Write-Host "`n1. 检查现有防火墙规则..." -ForegroundColor Yellow
$existingRule = Get-NetFirewallRule -DisplayName "MT5 Windows Agent" -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "找到现有规则，将删除并重新创建" -ForegroundColor Yellow
    Remove-NetFirewallRule -DisplayName "MT5 Windows Agent"
}

# 2. 创建新的防火墙规则
Write-Host "`n2. 创建防火墙规则允许端口 9000..." -ForegroundColor Yellow
New-NetFirewallRule -DisplayName "MT5 Windows Agent" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 9000 `
    -Action Allow `
    -Profile Any `
    -Enabled True `
    -Description "允许 Ubuntu 服务器访问 Windows Agent API (端口 9000)"

Write-Host "✓ 防火墙规则创建成功" -ForegroundColor Green

# 3. 验证规则
Write-Host "`n3. 验证防火墙规则..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName "MT5 Windows Agent" | Select-Object DisplayName, Enabled, Direction, Action

# 4. 检查端口监听状态
Write-Host "`n4. 检查端口 9000 监听状态..." -ForegroundColor Yellow
$listening = Get-NetTCPConnection -State Listen -LocalPort 9000 -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "✓ 端口 9000 正在监听" -ForegroundColor Green
    $listening | Select-Object LocalAddress, LocalPort, State
} else {
    Write-Host "✗ 端口 9000 未监听，需要启动 Windows Agent" -ForegroundColor Red
}

# 5. 测试本地连接
Write-Host "`n5. 测试本地连接..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:9000/" -Method Get -TimeoutSec 3 -ErrorAction Stop
    Write-Host "✓ 本地连接成功" -ForegroundColor Green
} catch {
    Write-Host "✗ 本地连接失败: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "提示：可能需要重启 Windows Agent" -ForegroundColor Yellow
}

Write-Host "`n=== 配置完成 ===" -ForegroundColor Cyan
Write-Host "下一步：从 Ubuntu 服务器测试连接" -ForegroundColor Yellow
Write-Host "命令：curl http://172.31.14.113:9000/" -ForegroundColor Gray
