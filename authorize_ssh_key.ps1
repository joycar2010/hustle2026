# 授权 SSH 公钥到 MT5 服务器 Administrator 账户
# 在 MT5 服务器 (54.249.66.53) 上以管理员身份运行此脚本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SSH 公钥授权工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 公钥内容
$publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMZnRHno9RCGHSI0hijpQP2HZp23c9PM958vFwy5wUrN HUAWEI@JoyBook"

# Administrator 用户的 .ssh 目录
$sshDir = "C:\Users\Administrator\.ssh"
$authorizedKeysFile = "$sshDir\authorized_keys"

Write-Host "[1/4] 检查 .ssh 目录..." -ForegroundColor Yellow
if (-not (Test-Path $sshDir)) {
    Write-Host "  创建目录: $sshDir" -ForegroundColor Gray
    New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
    Write-Host "  ✓ 目录已创建" -ForegroundColor Green
} else {
    Write-Host "  ✓ 目录已存在" -ForegroundColor Green
}
Write-Host ""

Write-Host "[2/4] 检查 authorized_keys 文件..." -ForegroundColor Yellow
if (-not (Test-Path $authorizedKeysFile)) {
    Write-Host "  创建文件: $authorizedKeysFile" -ForegroundColor Gray
    New-Item -ItemType File -Path $authorizedKeysFile -Force | Out-Null
    Write-Host "  ✓ 文件已创建" -ForegroundColor Green
} else {
    Write-Host "  ✓ 文件已存在" -ForegroundColor Green

    # 检查公钥是否已存在
    $existingKeys = Get-Content $authorizedKeysFile -ErrorAction SilentlyContinue
    if ($existingKeys -contains $publicKey) {
        Write-Host "  ! 公钥已存在，无需添加" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "公钥已授权" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Cyan
        exit 0
    }
}
Write-Host ""

Write-Host "[3/4] 添加公钥到 authorized_keys..." -ForegroundColor Yellow
Add-Content -Path $authorizedKeysFile -Value $publicKey
Write-Host "  ✓ 公钥已添加" -ForegroundColor Green
Write-Host ""

Write-Host "[4/4] 设置文件权限..." -ForegroundColor Yellow
# 设置正确的权限（仅 Administrator 可读写）
try {
    # 禁用继承
    $acl = Get-Acl $authorizedKeysFile
    $acl.SetAccessRuleProtection($true, $false)

    # 移除所有现有权限
    $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }

    # 添加 Administrator 的完全控制权限
    $adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        "Administrator",
        "FullControl",
        "Allow"
    )
    $acl.AddAccessRule($adminRule)

    # 添加 SYSTEM 的完全控制权限
    $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        "SYSTEM",
        "FullControl",
        "Allow"
    )
    $acl.AddAccessRule($systemRule)

    Set-Acl -Path $authorizedKeysFile -AclObject $acl
    Write-Host "  ✓ 权限已设置" -ForegroundColor Green
} catch {
    Write-Host "  ! 权限设置失败: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  请手动设置文件权限" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "授权完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "公钥信息:" -ForegroundColor Yellow
Write-Host "  类型: ED25519" -ForegroundColor White
Write-Host "  指纹: SHA256:Q///4JQx0xWbf1NVTaIHqUzYnrjReXWg7wRQYLqPPC8" -ForegroundColor White
Write-Host "  来源: HUAWEI@JoyBook" -ForegroundColor White
Write-Host ""
Write-Host "authorized_keys 文件位置:" -ForegroundColor Yellow
Write-Host "  $authorizedKeysFile" -ForegroundColor White
Write-Host ""
Write-Host "验证连接:" -ForegroundColor Yellow
Write-Host "  在本地机器上运行:" -ForegroundColor White
Write-Host "  ssh -i c:/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53" -ForegroundColor Cyan
Write-Host ""
