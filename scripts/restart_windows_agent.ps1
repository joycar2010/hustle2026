# MT5 状态优化功能 - Windows Agent 重启脚本
# 在 Windows 服务器上执行

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Windows Agent 重启脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. 停止现有进程
Write-Host "`n[1/3] 停止现有 Python 进程..." -ForegroundColor Yellow
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 2. 验证健康检查端点代码
Write-Host "`n[2/3] 验证健康检查端点..." -ForegroundColor Yellow
$mainPyPath = "C:\MT5Agent\main.py"
$content = Get-Content $mainPyPath -Raw

if ($content -match '/instances/\{port\}/health') {
    Write-Host "✓ 健康检查端点已存在" -ForegroundColor Green
} else {
    Write-Host "✗ 健康检查端点不存在，需要添加" -ForegroundColor Red
    Write-Host "请运行: python C:\MT5Agent\add_health_endpoints.py" -ForegroundColor Yellow
    exit 1
}

# 3. 启动 Agent
Write-Host "`n[3/3] 启动 Windows Agent..." -ForegroundColor Yellow
Start-Process -FilePath "python" -ArgumentList "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent" -WindowStyle Hidden

Start-Sleep -Seconds 3

# 4. 验证服务
Write-Host "`n验证服务..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9000/" -UseBasicParsing -TimeoutSec 5
    Write-Host "✓ Agent 服务正常运行" -ForegroundColor Green
    Write-Host "响应: $($response.StatusCode)" -ForegroundColor Gray
} catch {
    Write-Host "✗ Agent 服务未响应" -ForegroundColor Red
    Write-Host "错误: $_" -ForegroundColor Red
    exit 1
}

# 5. 测试健康检查端点
Write-Host "`n测试健康检查端点..." -ForegroundColor Yellow
try {
    # 假设有实例运行在 8001 端口
    $healthResponse = Invoke-WebRequest -Uri "http://localhost:9000/instances/8001/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "✓ 健康检查端点正常" -ForegroundColor Green
    Write-Host "响应: $($healthResponse.Content)" -ForegroundColor Gray
} catch {
    Write-Host "⚠ 健康检查端点测试失败（可能是端口 8001 没有实例）" -ForegroundColor Yellow
    Write-Host "错误: $_" -ForegroundColor Gray
}

Write-Host "`n=========================================" -ForegroundColor Cyan
Write-Host "Windows Agent 重启完成！" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
