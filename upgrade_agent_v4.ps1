# MT5 Agent V4 升级脚本
# 在 MT5 服务器上运行此脚本以升级到 V4 版本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MT5 Agent V4 升级工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查是否在正确的目录
if (-not (Test-Path "C:\MT5Agent\main_v4.py")) {
    Write-Host "[错误] 找不到 main_v4.py 文件" -ForegroundColor Red
    Write-Host "请确保已运行迁移脚本" -ForegroundColor Yellow
    exit 1
}

Write-Host "[1/5] 停止当前 Agent 服务..." -ForegroundColor Yellow
try {
    # 尝试停止 Windows 服务
    $service = Get-Service -Name "MT5Agent" -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "  发现 Windows 服务，正在停止..." -ForegroundColor Gray
        Stop-Service -Name "MT5Agent" -Force -ErrorAction Stop
        Start-Sleep -Seconds 2
        Write-Host "  ✓ Windows 服务已停止" -ForegroundColor Green
    } else {
        Write-Host "  未发现 Windows 服务，尝试停止进程..." -ForegroundColor Gray
        # 停止所有相关的 Python 进程
        Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*main.py*" -or $_.CommandLine -like "*MT5Agent*"
        } | Stop-Process -Force
        Start-Sleep -Seconds 2
        Write-Host "  ✓ Agent 进程已停止" -ForegroundColor Green
    }
} catch {
    Write-Host "  警告: 停止服务时出错 - $($_.Exception.Message)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "[2/5] 备份当前版本..." -ForegroundColor Yellow
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
Copy-Item "C:\MT5Agent\main.py" -Destination "C:\MT5Agent\main.py.backup_$timestamp" -Force
Write-Host "  ✓ 已备份到 main.py.backup_$timestamp" -ForegroundColor Green
Write-Host ""

Write-Host "[3/5] 升级到 V4 版本..." -ForegroundColor Yellow
Copy-Item "C:\MT5Agent\main_v4.py" -Destination "C:\MT5Agent\main.py" -Force
Write-Host "  ✓ main_v4.py 已复制为 main.py" -ForegroundColor Green
Write-Host ""

Write-Host "[4/5] 启动 Agent 服务..." -ForegroundColor Yellow
try {
    $service = Get-Service -Name "MT5Agent" -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "  启动 Windows 服务..." -ForegroundColor Gray
        Start-Service -Name "MT5Agent" -ErrorAction Stop
        Start-Sleep -Seconds 3
        Write-Host "  ✓ Windows 服务已启动" -ForegroundColor Green
    } else {
        Write-Host "  以后台进程方式启动..." -ForegroundColor Gray
        cd C:\MT5Agent
        Start-Process python -ArgumentList "main.py" -WindowStyle Hidden
        Start-Sleep -Seconds 3
        Write-Host "  ✓ Agent 进程已启动" -ForegroundColor Green
    }
} catch {
    Write-Host "  错误: 启动服务失败 - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

Write-Host "[5/5] 验证服务状态..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

# 测试健康检查
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9000/" -UseBasicParsing -TimeoutSec 10
    $healthData = $response.Content | ConvertFrom-Json

    Write-Host "  ✓ Agent 运行正常" -ForegroundColor Green
    Write-Host "    状态: $($healthData.status)" -ForegroundColor Cyan
    Write-Host "    服务: $($healthData.service)" -ForegroundColor Cyan
    Write-Host "    版本: $($healthData.version)" -ForegroundColor Cyan
} catch {
    Write-Host "  ✗ 健康检查失败: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  请检查日志文件" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# 测试实例列表
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9000/instances" -UseBasicParsing -TimeoutSec 10
    $instancesData = $response.Content | ConvertFrom-Json

    Write-Host "  ✓ 实例列表查询成功" -ForegroundColor Green
    if ($instancesData.instances) {
        $instanceCount = ($instancesData.instances | Get-Member -MemberType NoteProperty).Count
        Write-Host "    当前实例数: $instanceCount" -ForegroundColor Cyan

        foreach ($port in $instancesData.instances.PSObject.Properties.Name) {
            $instance = $instancesData.instances.$port
            Write-Host "    - 端口 $port`: $($instance.status)" -ForegroundColor Gray
        }
    }
} catch {
    Write-Host "  警告: 实例列表查询失败 - $($_.Exception.Message)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "升级完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "V4 版本新特性:" -ForegroundColor Yellow
Write-Host "  - 完整的 MT5 客户端停止功能" -ForegroundColor White
Write-Host "  - 支持多进程环境下的精确停止" -ForegroundColor White
Write-Host "  - 更完善的错误处理和日志" -ForegroundColor White
Write-Host ""
Write-Host "备份文件: main.py.backup_$timestamp" -ForegroundColor Gray
Write-Host ""
