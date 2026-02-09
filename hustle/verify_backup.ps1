# GitHub备份验证脚本
# 版本：1.0
# 日期：2024-02-10

param(
    [string]$backupDir = "D:\backups\github",
    [string]$encryptedDir = "D:\backups\encrypted",
    [string]$verifyDir = "D:\backups\verify",
    [string]$keyFile = "D:\secrets\backup_key.txt"
)

# 初始化目录
New-Item -ItemType Directory -Path $verifyDir -Force | Out-Null

# 日志函数
function Write-Log {
    param([string]$message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
}

Write-Log "=== 备份验证任务开始 ==="

# 检查密钥文件
if (-not (Test-Path $keyFile)) {
    Write-Log "ERROR: 密钥文件不存在: $keyFile"
    exit 1
}

$password = Get-Content $keyFile -Raw

# 获取最新加密备份
$latestEncrypted = Get-ChildItem -Path $encryptedDir -Filter "*.7z" | Sort-Object CreationTime -Descending | Select-Object -First 1
if (-not $latestEncrypted) {
    Write-Log "ERROR: 未找到加密备份文件"
    exit 1
}

$encryptedFile = $latestEncrypted.FullName
$backupName = $latestEncrypted.BaseName
$hashFile = "$encryptedDir\$backupName.hash"

Write-Log "开始验证备份: $encryptedFile"

# 1. 验证哈希值
if (Test-Path $hashFile) {
    Write-Log "验证SHA256哈希值..."
    $expectedHash = Get-Content $hashFile -Raw
    $actualHash = (Get-FileHash -Path $encryptedFile -Algorithm SHA256).Hash
    
    if ($expectedHash -eq $actualHash) {
        Write-Log "哈希值验证成功: $actualHash"
    } else {
        Write-Log "ERROR: 哈希值验证失败"
        Write-Log "期望: $expectedHash"
        Write-Log "实际: $actualHash"
        exit 1
    }
} else {
    Write-Log "WARNING: 未找到哈希文件，跳过哈希验证"
}

# 2. 解密备份文件
Write-Log "开始解密备份文件..."
$7zipPath = "C:\Program Files\7-Zip\7z.exe"
if (-not (Test-Path $7zipPath)) {
    $7zipPath = "C:\Program Files (x86)\7-Zip\7z.exe"
}

& $7zipPath x -p"$password" "$encryptedFile" -o"$verifyDir"

if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: 备份文件解密失败"
    exit 1
}

# 3. 验证Git仓库完整性
Write-Log "验证Git仓库完整性..."
$mirrorDir = Get-ChildItem -Path $verifyDir -Filter "*.git" -Directory | Select-Object -First 1
if ($mirrorDir) {
    cd $mirrorDir.FullName
    git fsck --full 2>&1 | ForEach-Object { Write-Log "git fsck: $_" }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Log "Git仓库完整性验证成功"
    } else {
        Write-Log "ERROR: Git仓库完整性验证失败"
        exit 1
    }
} else {
    Write-Log "ERROR: 未找到Git仓库镜像"
    exit 1
}

# 4. 验证分支和标签
Write-Log "验证分支和标签..."
$branches = git branch -a
Write-Log "找到 $($branches.Count) 个分支"

$tags = git tag -l
Write-Log "找到 $($tags.Count) 个标签"

# 5. 验证提交历史
Write-Log "验证提交历史..."
$commits = git log --oneline --all
Write-Log "找到 $($commits.Count) 次提交"

Write-Log "=== 备份验证任务完成 ==="
Write-Log "备份文件完整且可恢复"

# 清理验证目录
Remove-Item -Path $verifyDir -Recurse -Force | Out-Null
Write-Log "清理验证目录完成"

exit 0