# MT5 状态优化功能 - 完整测试脚本

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "MT5 状态优化功能测试脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 配置
$adminUrl = "https://admin.hustle2026.xyz"
$username = "admin"
$password = Read-Host "请输入管理员密码" -AsSecureString
$passwordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))

# 1. 登录获取 Token
Write-Host "`n[1/5] 登录获取 Token..." -ForegroundColor Yellow
$loginBody = @{
    username = $username
    password = $passwordPlain
} | ConvertTo-Json

try {
    $loginResponse = Invoke-RestMethod -Uri "$adminUrl/api/v1/auth/login" -Method Post -Body $loginBody -ContentType "application/json"
    $token = $loginResponse.access_token
    Write-Host "✓ 登录成功" -ForegroundColor Green
} catch {
    Write-Host "✗ 登录失败: $_" -ForegroundColor Red
    exit 1
}

$headers = @{
    "Authorization" = "Bearer $token"
}

# 2. 测试 /api/v1/monitor/status 端点
Write-Host "`n[2/5] 测试 monitor/status 端点..." -ForegroundColor Yellow
try {
    $monitorResponse = Invoke-RestMethod -Uri "$adminUrl/api/v1/monitor/status" -Headers $headers

    Write-Host "✓ API 响应正常" -ForegroundColor Green
    Write-Host "  - Redis: $($monitorResponse.redis.connected)" -ForegroundColor Gray
    Write-Host "  - MT5 客户端数量: $($monitorResponse.mt5_clients.Count)" -ForegroundColor Gray

    if ($monitorResponse.mt5_clients.Count -gt 0) {
        $client = $monitorResponse.mt5_clients[0]
        Write-Host "  - 第一个客户端:" -ForegroundColor Gray
        Write-Host "    * 名称: $($client.client_name)" -ForegroundColor Gray
        Write-Host "    * 在线: $($client.online)" -ForegroundColor Gray
        Write-Host "    * 进程运行: $($client.process_running)" -ForegroundColor Gray
        Write-Host "    * 最后连接: $($client.last_connected_at)" -ForegroundColor Gray
    }
} catch {
    Write-Host "✗ API 测试失败: $_" -ForegroundColor Red
}

# 3. 测试 Windows Agent 健康检查
Write-Host "`n[3/5] 测试 Windows Agent 健康检查..." -ForegroundColor Yellow
try {
    $agentResponse = Invoke-RestMethod -Uri "http://54.249.66.53:9000/"
    Write-Host "✓ Windows Agent 正常" -ForegroundColor Green
    Write-Host "  - 版本: $($agentResponse.version)" -ForegroundColor Gray
    Write-Host "  - 运行时间: $($agentResponse.uptime) 秒" -ForegroundColor Gray
} catch {
    Write-Host "✗ Windows Agent 不可达: $_" -ForegroundColor Red
}

# 测试健康检查端点
try {
    $healthResponse = Invoke-RestMethod -Uri "http://54.249.66.53:9000/instances/8001/health"
    Write-Host "✓ 健康检查端点正常" -ForegroundColor Green
    Write-Host "  - 端口: $($healthResponse.port)" -ForegroundColor Gray
    Write-Host "  - 运行中: $($healthResponse.running)" -ForegroundColor Gray
    Write-Host "  - MT5 连接: $($healthResponse.mt5_connected)" -ForegroundColor Gray
} catch {
    Write-Host "⚠ 健康检查端点测试失败（可能端口 8001 无实例）" -ForegroundColor Yellow
}

# 4. 测试前端页面
Write-Host "`n[4/5] 测试前端页面..." -ForegroundColor Yellow
try {
    $frontendResponse = Invoke-WebRequest -Uri "$adminUrl/" -UseBasicParsing
    if ($frontendResponse.StatusCode -eq 200) {
        Write-Host "✓ 前端页面正常" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ 前端页面访问失败: $_" -ForegroundColor Red
}

# 5. 检查后端日志
Write-Host "`n[5/5] 后端日志检查提示..." -ForegroundColor Yellow
Write-Host "请在服务器上执行以下命令检查日志:" -ForegroundColor Gray
Write-Host "  sudo journalctl -u hustle-backend -n 50 | grep -i 'mt5.*sync'" -ForegroundColor Cyan

Write-Host "`n=========================================" -ForegroundColor Cyan
Write-Host "测试完成！" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n手动验证清单:" -ForegroundColor Yellow
Write-Host "1. 访问 $adminUrl/" -ForegroundColor Gray
Write-Host "2. 展开 'MT5 客户端状态' 面板" -ForegroundColor Gray
Write-Host "3. 检查是否显示:" -ForegroundColor Gray
Write-Host "   - 进程状态（运行中/已停止）" -ForegroundColor Gray
Write-Host "   - 最后心跳时间" -ForegroundColor Gray
Write-Host "   - 重启和详情按钮" -ForegroundColor Gray
Write-Host "4. 打开浏览器开发者工具 Network 面板" -ForegroundColor Gray
Write-Host "5. 观察是否每 5 秒请求一次 /api/v1/monitor/status" -ForegroundColor Gray
Write-Host "6. 访问 $adminUrl/users，切换到 MT5客户端 tab" -ForegroundColor Gray
Write-Host "7. 点击实例的重启按钮，观察控制台是否显示:" -ForegroundColor Gray
Write-Host "   - 'Started fast polling (3s interval)'" -ForegroundColor Gray
Write-Host "   - 'Stopped fast polling'" -ForegroundColor Gray
