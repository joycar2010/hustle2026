# 配置 Windows 防火墙允许 MT5 Agent 端口（9000）
# 需要以管理员身份运行

Write-Host "配置 Windows 防火墙..." -ForegroundColor Green

# 删除旧规则（如果存在）
Remove-NetFirewallRule -DisplayName "MT5 Windows Agent" -ErrorAction SilentlyContinue

# 添加入站规则 - 允许 TCP 9000 端口
New-NetFirewallRule -DisplayName "MT5 Windows Agent" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 9000 `
    -Action Allow `
    -Profile Any `
    -Description "允许内网访问 MT5 Windows Agent API (端口 9000)"

Write-Host "防火墙规则已添加" -ForegroundColor Green

# 验证规则
Get-NetFirewallRule -DisplayName "MT5 Windows Agent" | Format-Table -Property DisplayName, Enabled, Direction, Action

Write-Host "`n配置完成！现在可以通过内网 IP 访问 Agent API" -ForegroundColor Green
Write-Host "测试命令: curl http://172.31.14.113:9000/" -ForegroundColor Yellow
