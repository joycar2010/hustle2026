# Windows 自动登录配置脚本
# 警告：此脚本会在注册表中存储密码，仅在安全环境中使用

param(
    [Parameter(Mandatory=$false)]
    [string]$Username = "Administrator",

    [Parameter(Mandatory=$false)]
    [string]$Password = "",

    [Parameter(Mandatory=$false)]
    [switch]$Disable
)

# 检查管理员权限
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[错误] 此脚本需要管理员权限运行" -ForegroundColor Red
    Write-Host "请右键点击 PowerShell 并选择'以管理员身份运行'" -ForegroundColor Yellow
    Read-Host "按 Enter 键退出"
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Windows 自动登录配置" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$RegPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

if ($Disable) {
    # 禁用自动登录
    Write-Host "禁用自动登录..." -ForegroundColor Yellow
    try {
        Set-ItemProperty -Path $RegPath -Name "AutoAdminLogon" -Value "0"
        Remove-ItemProperty -Path $RegPath -Name "DefaultPassword" -ErrorAction SilentlyContinue
        Write-Host "[成功] 自动登录已禁用" -ForegroundColor Green
    } catch {
        Write-Host "[错误] 禁用失败: $_" -ForegroundColor Red
    }
} else {
    # 启用自动登录
    Write-Host "配置自动登录..." -ForegroundColor Yellow
    Write-Host "用户名: $Username" -ForegroundColor Gray

    if ([string]::IsNullOrEmpty($Password)) {
        $SecurePassword = Read-Host "请输入密码" -AsSecureString
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
        $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    }

    try {
        Set-ItemProperty -Path $RegPath -Name "AutoAdminLogon" -Value "1"
        Set-ItemProperty -Path $RegPath -Name "DefaultUserName" -Value $Username
        Set-ItemProperty -Path $RegPath -Name "DefaultPassword" -Value $Password
        Set-ItemProperty -Path $RegPath -Name "DefaultDomainName" -Value $env:COMPUTERNAME

        Write-Host "[成功] 自动登录已配置" -ForegroundColor Green
        Write-Host ""
        Write-Host "安全提示:" -ForegroundColor Yellow
        Write-Host "- 密码以明文存储在注册表中" -ForegroundColor Gray
        Write-Host "- 仅在安全的内网环境中使用" -ForegroundColor Gray
        Write-Host "- 定期更换密码" -ForegroundColor Gray
        Write-Host "- 启用 Windows 防火墙" -ForegroundColor Gray
    } catch {
        Write-Host "[错误] 配置失败: $_" -ForegroundColor Red
    }
}

Write-Host ""

# 显示当前配置
Write-Host "当前配置:" -ForegroundColor Cyan
try {
    $AutoLogon = Get-ItemProperty -Path $RegPath -Name "AutoAdminLogon" -ErrorAction SilentlyContinue
    $DefaultUser = Get-ItemProperty -Path $RegPath -Name "DefaultUserName" -ErrorAction SilentlyContinue

    if ($AutoLogon.AutoAdminLogon -eq "1") {
        Write-Host "  自动登录: 已启用" -ForegroundColor Green
        Write-Host "  用户名: $($DefaultUser.DefaultUserName)" -ForegroundColor Gray
    } else {
        Write-Host "  自动登录: 已禁用" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  无法读取配置" -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Read-Host "按 Enter 键退出"
