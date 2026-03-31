# Windows Agent 启动和验证脚本
# 用途：启动 MT5 Windows Agent 并验证网络连接

Write-Host "=== MT5 Windows Agent 启动脚本 ===" -ForegroundColor Cyan

# 1. 停止现有的 Python 进程（如果有）
Write-Host "`n1. 停止现有的 Windows Agent 进程..." -ForegroundColor Yellow
$agentProcesses = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*Python311*" -or $_.Path -like "*MT5Agent*"
}
if ($agentProcesses) {
    Write-Host "找到 $($agentProcesses.Count) 个相关进程，正在停止..." -ForegroundColor Yellow
    $agentProcesses | Stop-Process -Force
    Start-Sleep -Seconds 2
    Write-Host "✓ 进程已停止" -ForegroundColor Green
} else {
    Write-Host "没有找到运行中的进程" -ForegroundColor Gray
}

# 2. 清理重复的防火墙规则
Write-Host "`n2. 清理重复的防火墙规则..." -ForegroundColor Yellow
$rules = Get-NetFirewallRule -DisplayName "MT5 Windows Agent" -ErrorAction SilentlyContinue
if ($rules.Count -gt 1) {
    Write-Host "找到 $($rules.Count) 个重复规则，保留第一个，删除其余..." -ForegroundColor Yellow
    $rules | Select-Object -Skip 1 | Remove-NetFirewallRule
    Write-Host "✓ 重复规则已清理" -ForegroundColor Green
} elseif ($rules.Count -eq 1) {
    Write-Host "✓ 防火墙规则正常（1个）" -ForegroundColor Green
} else {
    Write-Host "⚠ 未找到防火墙规则，正在创建..." -ForegroundColor Yellow
    New-NetFirewallRule -DisplayName "MT5 Windows Agent" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 9000 `
        -Action Allow `
        -Profile Any `
        -Enabled True
    Write-Host "✓ 防火墙规则已创建" -ForegroundColor Green
}

# 3. 启动 Windows Agent
Write-Host "`n3. 启动 Windows Agent..." -ForegroundColor Yellow
if (Test-Path "C:\MT5Agent\main.py") {
    # 使用 Start-Process 在后台启动
    $process = Start-Process -FilePath "python" `
        -ArgumentList "C:\MT5Agent\main.py" `
        -WorkingDirectory "C:\MT5Agent" `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "✓ Windows Agent 已启动 (PID: $($process.Id))" -ForegroundColor Green

    # 等待服务启动
    Write-Host "等待服务启动..." -ForegroundColor Gray
    Start-Sleep -Seconds 8
} else {
    Write-Host "✗ 错误：找不到 C:\MT5Agent\main.py" -ForegroundColor Red
    exit 1
}

# 4. 验证端口监听
Write-Host "`n4. 验证端口 9000 监听状态..." -ForegroundColor Yellow
$listening = Get-NetTCPConnection -State Listen -LocalPort 9000 -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "✓ 端口 9000 正在监听" -ForegroundColor Green
    $listening | Format-Table LocalAddress, LocalPort, State, OwningProcess -AutoSize

    # 显示进程信息
    $processId = $listening[0].OwningProcess
    $processInfo = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($processInfo) {
        Write-Host "进程信息：" -ForegroundColor Gray
        Write-Host "  PID: $processId" -ForegroundColor Gray
        Write-Host "  名称: $($processInfo.ProcessName)" -ForegroundColor Gray
        Write-Host "  路径: $($processInfo.Path)" -ForegroundColor Gray
    }
} else {
    Write-Host "✗ 端口 9000 未监听" -ForegroundColor Red
    Write-Host "检查进程是否启动失败..." -ForegroundColor Yellow

    # 检查是否有 Python 进程
    $pythonProcesses = Get-Process -Name python -ErrorAction SilentlyContinue
    if ($pythonProcesses) {
        Write-Host "找到 Python 进程：" -ForegroundColor Yellow
        $pythonProcesses | Format-Table Id, ProcessName, Path -AutoSize
    }

    Write-Host "`n尝试查看错误日志..." -ForegroundColor Yellow
    if (Test-Path "C:\MT5Agent\agent_error.log") {
        Get-Content "C:\MT5Agent\agent_error.log" -Tail 20
    }
    exit 1
}

# 5. 测试本地 HTTP 连接
Write-Host "`n5. 测试本地 HTTP 连接..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:9000/" -Method Get -TimeoutSec 5
    Write-Host "✓ 本地连接成功" -ForegroundColor Green
} catch {
    Write-Host "✗ 本地连接失败: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "状态码: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Gray
}

# 6. 测试健康检查端点
Write-Host "`n6. 测试健康检查端点..." -ForegroundColor Yellow
$testPorts = @(8001, 8002)
foreach ($port in $testPorts) {
    try {
        $healthUrl = "http://localhost:9000/instances/$port/health"
        $health = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 3
        Write-Host "✓ 端口 $port 健康检查成功" -ForegroundColor Green
        Write-Host "  运行状态: $($health.running)" -ForegroundColor Gray
        Write-Host "  MT5 连接: $($health.mt5_connected)" -ForegroundColor Gray
    } catch {
        Write-Host "⚠ 端口 $port 健康检查失败: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 7. 显示网络监听信息
Write-Host "`n7. 当前所有监听端口..." -ForegroundColor Yellow
netstat -ano | findstr ":9000"
netstat -ano | findstr ":8001"
netstat -ano | findstr ":8002"

Write-Host "`n=== 启动完成 ===" -ForegroundColor Cyan
Write-Host "`n下一步测试：" -ForegroundColor Yellow
Write-Host "1. 从 Ubuntu 服务器测试：" -ForegroundColor White
Write-Host "   ssh ubuntu@go.hustle2026.xyz" -ForegroundColor Gray
Write-Host "   curl http://172.31.14.113:9000/" -ForegroundColor Gray
Write-Host "`n2. 检查 API 返回数据：" -ForegroundColor White
Write-Host "   curl http://localhost:8000/api/v1/monitor/status | python3 -m json.tool" -ForegroundColor Gray
Write-Host "`n3. 访问前端验证：" -ForegroundColor White
Write-Host "   https://admin.hustle2026.xyz/" -ForegroundColor Gray
