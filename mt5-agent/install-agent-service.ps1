# Hustle MT5 Agent - Windows 服务安装脚本
# 将 Agent 注册为 Windows 服务，实现开机自启

$ServiceName = "HustleMT5Agent"
$DisplayName = "Hustle MT5 Agent Service"
$Description = "MT5 微服务管理代理，用于部署和管理 MT5 实例"
$AgentPath = "D:\hustle-agent"
$PythonExe = (Get-Command python).Source
$AgentScript = "$AgentPath\agent.py"

Write-Host "=== Hustle MT5 Agent Service Installer ===" -ForegroundColor Cyan

# 检查是否以管理员权限运行
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: 请以管理员权限运行此脚本" -ForegroundColor Red
    exit 1
}

# 检查 Agent 文件是否存在
if (-not (Test-Path $AgentScript)) {
    Write-Host "ERROR: Agent 脚本不存在: $AgentScript" -ForegroundColor Red
    exit 1
}

# 停止并删除已存在的服务
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "停止现有服务..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    
    Write-Host "删除现有服务..." -ForegroundColor Yellow
    sc.exe delete $ServiceName
    Start-Sleep -Seconds 2
}

# 创建服务包装脚本（使用 NSSM 或 Python 服务包装器）
Write-Host "创建服务启动脚本..." -ForegroundColor Green
$startScript = @"
@echo off
cd /d $AgentPath
$PythonExe agent.py
"@
$startScript | Out-File -FilePath "$AgentPath\start-agent.bat" -Encoding ASCII

# 使用 sc.exe 创建服务
Write-Host "注册 Windows 服务..." -ForegroundColor Green
$binPath = "cmd.exe /c `"$AgentPath\start-agent.bat`""
sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $DisplayName

# 设置服务描述
sc.exe description $ServiceName $Description

# 配置服务失败后自动重启
sc.exe failure $ServiceName reset= 86400 actions= restart/60000/restart/60000/restart/60000

Write-Host "`n=== 服务安装完成 ===" -ForegroundColor Green
Write-Host "服务名称: $ServiceName" -ForegroundColor Cyan
Write-Host "显示名称: $DisplayName" -ForegroundColor Cyan
Write-Host "启动类型: 自动" -ForegroundColor Cyan
Write-Host "`n启动服务..." -ForegroundColor Yellow
Start-Service -Name $ServiceName

Start-Sleep -Seconds 3

# 验证服务状态
$service = Get-Service -Name $ServiceName
if ($service.Status -eq "Running") {
    Write-Host "`n✓ 服务已成功启动！" -ForegroundColor Green
    Write-Host "API 地址: http://127.0.0.1:9000" -ForegroundColor Cyan
    
    # 测试 API
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:9000/" -TimeoutSec 5
        Write-Host "`n✓ API 测试成功！" -ForegroundColor Green
        Write-Host ($response | ConvertTo-Json) -ForegroundColor Gray
    } catch {
        Write-Host "`n⚠ API 测试失败，请检查日志" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n✗ 服务启动失败，状态: $($service.Status)" -ForegroundColor Red
    Write-Host "请检查事件查看器中的错误日志" -ForegroundColor Yellow
}

Write-Host "`n常用命令:" -ForegroundColor Cyan
Write-Host "  启动服务: Start-Service $ServiceName" -ForegroundColor Gray
Write-Host "  停止服务: Stop-Service $ServiceName" -ForegroundColor Gray
Write-Host "  重启服务: Restart-Service $ServiceName" -ForegroundColor Gray
Write-Host "  查看状态: Get-Service $ServiceName" -ForegroundColor Gray
Write-Host "  卸载服务: sc.exe delete $ServiceName" -ForegroundColor Gray
