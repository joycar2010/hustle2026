# MT5 Session 0 修复脚本
# 此脚本需要在 Windows 服务器的 RDP 会话中以管理员身份运行

Write-Host "=== MT5 Session 0 修复脚本 ===" -ForegroundColor Cyan

# 1. 检查 PsExec 是否存在
$psexecPath = "C:\Tools\PSTools\PsExec.exe"
if (-not (Test-Path $psexecPath)) {
    Write-Host "PsExec 未找到，正在下载..." -ForegroundColor Yellow

    # 创建目录
    New-Item -ItemType Directory -Force -Path "C:\Tools\PSTools" | Out-Null

    # 下载 PSTools
    $url = "https://download.sysinternals.com/files/PSTools.zip"
    $zipPath = "C:\Tools\PSTools.zip"

    try {
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
        Expand-Archive -Path $zipPath -DestinationPath "C:\Tools\PSTools" -Force
        Remove-Item $zipPath
        Write-Host "PsExec 下载完成" -ForegroundColor Green
    } catch {
        Write-Host "下载失败: $_" -ForegroundColor Red
        Write-Host "请手动下载 PSTools 并解压到 C:\Tools\PSTools\" -ForegroundColor Yellow
        exit 1
    }
}

# 2. 获取当前活动会话 ID
$activeSession = (query session | Select-String "Active" | Select-Object -First 1) -replace '\s+', ' '
if ($activeSession -match 'rdp-tcp#(\d+)') {
    $sessionId = $Matches[1]
    Write-Host "检测到活动 RDP 会话: Session $sessionId" -ForegroundColor Green
} else {
    Write-Host "未找到活动 RDP 会话" -ForegroundColor Red
    exit 1
}

# 3. 停止现有的 Windows Agent
Write-Host "停止现有的 Windows Agent..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    if ($wmi.CommandLine -like "*main_v2.py*" -or $wmi.CommandLine -like "*MT5Agent*") {
        Stop-Process -Id $_.Id -Force
        Write-Host "已停止进程 PID: $($_.Id)" -ForegroundColor Gray
    }
}

Start-Sleep -Seconds 2

# 4. 备份当前的 main_v2.py
$agentPath = "C:\MT5Agent\main_v2.py"
if (Test-Path $agentPath) {
    $backupPath = "C:\MT5Agent\main_v2.py.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $agentPath $backupPath
    Write-Host "已备份到: $backupPath" -ForegroundColor Gray
}

# 5. 下载新的 main_v2.py（从本地仓库）
Write-Host "更新 main_v2.py..." -ForegroundColor Yellow

# 注意：需要先将更新后的 main_v2.py 上传到 C:\Temp\
$sourcePath = "C:\Temp\main_v2.py"
if (Test-Path $sourcePath) {
    Copy-Item $sourcePath $agentPath -Force
    Write-Host "main_v2.py 已更新" -ForegroundColor Green
} else {
    Write-Host "错误: 未找到 $sourcePath" -ForegroundColor Red
    Write-Host "请先将更新后的 main_v2.py 上传到 C:\Temp\" -ForegroundColor Yellow
    exit 1
}

# 6. 在当前用户会话中启动 Windows Agent
Write-Host "在用户会话中启动 Windows Agent..." -ForegroundColor Yellow

$startCmd = "cd C:\MT5Agent && python main_v2.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $startCmd -WindowStyle Normal

Start-Sleep -Seconds 3

# 7. 验证服务启动
try {
    $response = Invoke-RestMethod -Uri "http://localhost:9000/" -Method Get -TimeoutSec 5
    if ($response.status -eq "healthy") {
        Write-Host "✓ Windows Agent 启动成功" -ForegroundColor Green
        Write-Host "  版本: $($response.version)" -ForegroundColor Gray
        Write-Host "  运行时间: $($response.uptime)秒" -ForegroundColor Gray
    }
} catch {
    Write-Host "✗ Windows Agent 可能未正常启动" -ForegroundColor Red
    Write-Host "  请检查 PowerShell 窗口中的错误信息" -ForegroundColor Yellow
}

Write-Host "`n=== 修复完成 ===" -ForegroundColor Cyan
Write-Host "现在可以在管理后台点击 MT5 实例的启动按钮测试" -ForegroundColor Green
Write-Host "MT5 窗口应该会在当前 RDP 会话中显示" -ForegroundColor Green
