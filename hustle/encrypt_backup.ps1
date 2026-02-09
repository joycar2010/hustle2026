# GitHub备份文件加密脚本
# 版本：1.0
# 日期：2024-02-10

param(
    [string]$backupDir = "D:\backups\github",
    [string]$encryptedDir = "D:\backups\encrypted",
    [string]$keyFile = "D:\secrets\backup_key.txt"
)

# 初始化目录
New-Item -ItemType Directory -Path $encryptedDir -Force | Out-Null

# 日志函数
function Write-Log {
    param([string]$message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
}

Write-Log "=== 备份文件加密任务开始 ==="

# 检查密钥文件
if (-not (Test-Path $keyFile)) {
    Write-Log "ERROR: 密钥文件不存在: $keyFile"
    exit 1
}

$password = Get-Content $keyFile -Raw
if (-not $password) {
    Write-Log "ERROR: 密钥文件为空"
    exit 1
}

# 获取最新备份目录
$latestBackup = Get-ChildItem -Path $backupDir -Directory | Sort-Object CreationTime -Descending | Select-Object -First 1
if (-not $latestBackup) {
    Write-Log "ERROR: 未找到备份目录"
    exit 1
}

$backupPath = $latestBackup.FullName
$encryptedFile = "$encryptedDir\$($latestBackup.Name).7z"

Write-Log "开始加密备份: $backupPath"
Write-Log "加密后文件: $encryptedFile"

# 使用7-Zip加密备份文件
# 确保已安装7-Zip并添加到PATH
$7zipPath = "C:\Program Files\7-Zip\7z.exe"
if (-not (Test-Path $7zipPath)) {
    $7zipPath = "C:\Program Files (x86)\7-Zip\7z.exe"
    if (-not (Test-Path $7zipPath)) {
        Write-Log "ERROR: 未找到7-Zip安装路径"
        exit 1
    }
}

# 加密参数：AES-256，最高压缩比
& $7zipPath a -t7z -m0=lzma2 -mx=9 -mfb=64 -md=32m -ms=on -p"$password" "$encryptedFile" "$backupPath"

if ($LASTEXITCODE -eq 0) {
    Write-Log "备份文件加密成功"
    
    # 计算哈希值用于验证
    $hash = (Get-FileHash -Path $encryptedFile -Algorithm SHA256).Hash
    $hashFile = "$encryptedDir\$($latestBackup.Name).hash"
    Set-Content -Path $hashFile -Value $hash
    Write-Log "生成SHA256哈希值: $hash"
    
    # 验证加密文件
    Write-Log "开始验证加密文件..."
    & $7zipPath t -p"$password" "$encryptedFile"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Log "加密文件验证成功"
        exit 0
    } else {
        Write-Log "ERROR: 加密文件验证失败"
        exit 1
    }
} else {
    Write-Log "ERROR: 备份文件加密失败"
    exit 1
}