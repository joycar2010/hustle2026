# Windows 服务器清理脚本
# 执行方式：在 Windows 服务器上以管理员身份运行 PowerShell

Write-Host "=== Windows 服务器清理脚本 ===" -ForegroundColor Green

# 1. 检查当前运行的 Bridge 服务
Write-Host "`n1. 检查当前运行的 Bridge 服务..." -ForegroundColor Yellow
sc query | findstr /i "hustle-mt5"

# 2. 列出 C:\hustle-agent 目录内容
Write-Host "`n2. 检查 C:\hustle-agent 目录..." -ForegroundColor Yellow
if (Test-Path "C:\hustle-agent") {
    Get-ChildItem "C:\hustle-agent" -Recurse | Select-Object FullName, Length, LastWriteTime

    $confirm = Read-Host "`n确认删除 C:\hustle-agent 目录？(yes/no)"
    if ($confirm -eq "yes") {
        Remove-Item "C:\hustle-agent" -Recurse -Force
        Write-Host "   ✓ C:\hustle-agent 已删除" -ForegroundColor Green
    } else {
        Write-Host "   跳过删除 C:\hustle-agent" -ForegroundColor Yellow
    }
} else {
    Write-Host "   C:\hustle-agent 目录不存在" -ForegroundColor Gray
}

# 3. 清理 C:\MT5Agent 中的临时文件
Write-Host "`n3. 清理 C:\MT5Agent 临时文件..." -ForegroundColor Yellow
if (Test-Path "C:\MT5Agent") {
    # 列出所有文件
    Write-Host "   当前文件列表："
    Get-ChildItem "C:\MT5Agent" | Select-Object Name, Length, LastWriteTime | Format-Table

    # 备份重要文件
    $backupDir = "C:\MT5Agent\backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

    # 备份配置文件
    Copy-Item "C:\MT5Agent\config.json" "$backupDir\config.json" -Force
    Copy-Item "C:\MT5Agent\main_v3.py" "$backupDir\main_v3.py" -Force
    if (Test-Path "C:\MT5Agent\instances.json") {
        Copy-Item "C:\MT5Agent\instances.json" "$backupDir\instances.json" -Force
    }

    Write-Host "   ✓ 重要文件已备份到: $backupDir" -ForegroundColor Green

    # 删除临时文件
    $tempFiles = @(
        "*.pyc",
        "__pycache__",
        "*.log.old",
        "*.tmp",
        "test_*.py"
    )

    foreach ($pattern in $tempFiles) {
        Get-ChildItem "C:\MT5Agent" -Filter $pattern -Recurse -Force | ForEach-Object {
            Write-Host "   删除: $($_.FullName)" -ForegroundColor Gray
            Remove-Item $_.FullName -Force -Recurse
        }
    }

    Write-Host "   ✓ 临时文件已清理" -ForegroundColor Green
} else {
    Write-Host "   C:\MT5Agent 目录不存在" -ForegroundColor Red
}

# 4. 检查 Bridge 服务配置
Write-Host "`n4. 检查 Bridge 服务配置..." -ForegroundColor Yellow
$services = sc query | Select-String "hustle-mt5" -Context 0,5
if ($services) {
    Write-Host "   找到以下 Bridge 服务："
    $services | ForEach-Object { Write-Host "   $_" }
} else {
    Write-Host "   未找到 Bridge 服务" -ForegroundColor Gray
}

# 5. 检查 MT5 客户端目录
Write-Host "`n5. 检查 MT5 客户端目录..." -ForegroundColor Yellow
Get-ChildItem "D:\" -Filter "MetaTrader 5-*" | Select-Object Name, LastWriteTime | Format-Table

# 6. 检查 Bridge 部署目录
Write-Host "`n6. 检查 Bridge 部署目录..." -ForegroundColor Yellow
Get-ChildItem "D:\" -Filter "hustle-mt5-*" | Select-Object Name, LastWriteTime | Format-Table

Write-Host "`n=== 清理完成 ===" -ForegroundColor Green
Write-Host "备份目录: $backupDir" -ForegroundColor Cyan
