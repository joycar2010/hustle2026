<#
.SYNOPSIS
    安装 MT5 健康监控服务 V2

.DESCRIPTION
    将 MT5 健康监控脚本安装为 Windows 服务，通过后端 API 发送警报通知

.PARAMETER ServiceName
    服务名称（默认：MT5HealthMonitor）

.PARAMETER ApiBaseUrl
    后端 API 基础 URL

.PARAMETER AdminUsername
    管理员用户名（用于 API 认证）

.PARAMETER AdminPassword
    管理员密码（用于 API 认证）

.PARAMETER CheckInterval
    健康检查间隔（秒），默认 30 秒

.EXAMPLE
    .\install_monitor_service.ps1 -AdminUsername "admin" -AdminPassword "password"

.EXAMPLE
    .\install_monitor_service.ps1 -ServiceName "MT5Monitor" -CheckInterval 60
#>

param(
    [string]$ServiceName = "MT5HealthMonitor",
    [string]$ApiBaseUrl = "https://admin.hustle2026.xyz",
    [string]$AdminUsername = "",
    [string]$AdminPassword = "",
    [int]$CheckInterval = 30,
    [string]$ScriptPath = "d:\git\hustle2026\scripts\monitor_mt5_health_v2.ps1"
)

# 检查管理员权限
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "此脚本需要管理员权限运行"
    exit 1
}

# 检查监控脚本是否存在
if (-not (Test-Path $ScriptPath)) {
    Write-Error "监控脚本不存在: $ScriptPath"
    exit 1
}

Write-Host "=== 安装 MT5 健康监控服务 V2 ===" -ForegroundColor Cyan
Write-Host "服务名称: $ServiceName"
Write-Host "监控脚本: $ScriptPath"
Write-Host "检查间隔: $CheckInterval 秒"
Write-Host "API 地址: $ApiBaseUrl"
Write-Host "管理员账户: $(if($AdminUsername){'已配置'}else{'未配置'})"
Write-Host ""

# 检查服务是否已存在
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "服务已存在，正在停止并删除..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # 使用 sc.exe 删除服务
    sc.exe delete $ServiceName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "删除现有服务失败"
        exit 1
    }
    Start-Sleep -Seconds 2
}

# 构建 PowerShell 命令参数
$psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -CheckInterval $CheckInterval -ApiBaseUrl `"$ApiBaseUrl`""
if ($AdminUsername -and $AdminPassword) {
    $psArgs += " -AdminUsername `"$AdminUsername`" -AdminPassword `"$AdminPassword`""
}

# 使用 NSSM 安装服务（推荐方式）
$nssmPath = "C:\Tools\nssm.exe"
if (Test-Path $nssmPath) {
    Write-Host "使用 NSSM 安装服务..." -ForegroundColor Green

    & $nssmPath install $ServiceName "powershell.exe" $psArgs
    & $nssmPath set $ServiceName AppDirectory "d:\git\hustle2026\scripts"
    & $nssmPath set $ServiceName DisplayName "MT5 Health Monitor"
    & $nssmPath set $ServiceName Description "监控 MT5 客户端健康状态并发送警报"
    & $nssmPath set $ServiceName Start SERVICE_AUTO_START
    & $nssmPath set $ServiceName AppStdout "C:\MT5Agent\logs\monitor_service_stdout.log"
    & $nssmPath set $ServiceName AppStderr "C:\MT5Agent\logs\monitor_service_stderr.log"
    & $nssmPath set $ServiceName AppRotateFiles 1
    & $nssmPath set $ServiceName AppRotateBytes 10485760  # 10MB

    Write-Host "服务安装成功！" -ForegroundColor Green
} else {
    Write-Host "NSSM 未找到，使用 sc.exe 安装服务..." -ForegroundColor Yellow
    Write-Host "注意: 建议安装 NSSM 以获得更好的服务管理体验" -ForegroundColor Yellow
    Write-Host "下载地址: https://nssm.cc/download" -ForegroundColor Yellow
    Write-Host ""

    # 使用 sc.exe 创建服务
    $binPath = "powershell.exe $psArgs"
    sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= "MT5 Health Monitor" | Out-Null

    if ($LASTEXITCODE -ne 0) {
        Write-Error "服务安装失败"
        exit 1
    }

    # 设置服务描述
    sc.exe description $ServiceName "监控 MT5 客户端健康状态并通过 API 发送警报" | Out-Null

    Write-Host "服务安装成功！" -ForegroundColor Green
}

# 启动服务
Write-Host ""
Write-Host "正在启动服务..." -ForegroundColor Cyan
Start-Service -Name $ServiceName

# 检查服务状态
Start-Sleep -Seconds 3
$service = Get-Service -Name $ServiceName
if ($service.Status -eq "Running") {
    Write-Host "✓ 服务已成功启动并运行中" -ForegroundColor Green
} else {
    Write-Warning "服务状态: $($service.Status)"
    Write-Host "请检查日志: C:\MT5Agent\logs\monitor_service_*.log" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 安装完成 ===" -ForegroundColor Cyan
Write-Host "服务管理命令:"
Write-Host "  查看状态: Get-Service -Name $ServiceName"
Write-Host "  停止服务: Stop-Service -Name $ServiceName"
Write-Host "  启动服务: Start-Service -Name $ServiceName"
Write-Host "  删除服务: sc.exe delete $ServiceName"
Write-Host ""
Write-Host "日志位置:"
Write-Host "  监控日志: C:\MT5Agent\logs\health_monitor.log"
Write-Host "  服务日志: C:\MT5Agent\logs\monitor_service_*.log"
