# 在用户会话中启动 Windows Agent
# 此脚本需要在 RDP 会话中运行

Write-Host "=== 在用户会话中启动 Windows Agent ===" -ForegroundColor Cyan

# 1. 停止所有现有的 Windows Agent 进程
Write-Host "停止现有的 Windows Agent 进程..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    if ($wmi.CommandLine -like "*main_v2.py*" -or $wmi.CommandLine -like "*MT5Agent*") {
        Write-Host "  停止 PID: $($_.Id)" -ForegroundColor Gray
        Stop-Process -Id $_.Id -Force
    }
}

Start-Sleep -Seconds 2

# 2. 在当前用户会话中启动 Windows Agent
Write-Host "在用户会话中启动 Windows Agent..." -ForegroundColor Yellow

# 创建启动脚本
$startScript = @"
Set-Location C:\MT5Agent
python main_v2.py
"@

# 保存到临时文件
$tempScript = "C:\Temp\start_agent.ps1"
$startScript | Out-File -FilePath $tempScript -Encoding UTF8

# 在新的 PowerShell 窗口中启动（保持窗口打开以查看日志）
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $tempScript

Start-Sleep -Seconds 5

# 3. 验证服务启动
Write-Host "验证服务状态..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:9000/" -Method Get -TimeoutSec 5
    if ($response.status -eq "healthy") {
        Write-Host "✓ Windows Agent 启动成功" -ForegroundColor Green
        Write-Host "  版本: $($response.version)" -ForegroundColor Gray
        Write-Host "  运行时间: $($response.uptime)秒" -ForegroundColor Gray

        # 检查进程会话
        $agentProc = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
            (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*main_v2.py*"
        } | Select-Object -First 1

        if ($agentProc) {
            Write-Host "  进程 PID: $($agentProc.Id)" -ForegroundColor Gray
            Write-Host "  会话 ID: $($agentProc.SessionId)" -ForegroundColor Gray

            # 获取当前 RDP 会话 ID
            $currentSession = (query session | Select-String "Active" | Select-Object -First 1) -replace '\s+', ' '
            if ($currentSession -match '\s(\d+)\s+Active') {
                $rdpSessionId = $Matches[1]
                if ($agentProc.SessionId -eq $rdpSessionId) {
                    Write-Host "  ✓ Windows Agent 正在用户会话中运行" -ForegroundColor Green
                } else {
                    Write-Host "  ✗ Windows Agent 不在用户会话中（Session $($agentProc.SessionId) vs $rdpSessionId）" -ForegroundColor Yellow
                }
            }
        }
    }
} catch {
    Write-Host "✗ Windows Agent 可能未正常启动" -ForegroundColor Red
    Write-Host "  错误: $_" -ForegroundColor Red
}

Write-Host "`n=== 启动完成 ===" -ForegroundColor Cyan
Write-Host "Windows Agent 现在在用户会话中运行" -ForegroundColor Green
Write-Host "现在可以在管理后台点击 MT5 实例的启动按钮" -ForegroundColor Green
Write-Host "MT5 窗口应该会在当前 RDP 会话中显示" -ForegroundColor Green
Write-Host "`n注意：关闭 PowerShell 窗口会停止 Windows Agent" -ForegroundColor Yellow
