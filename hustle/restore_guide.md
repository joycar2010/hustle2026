# GitHub仓库备份恢复操作指南

## 1. 恢复准备工作

### 1.1 所需工具
- Git客户端（版本2.20+）
- 7-Zip压缩工具（版本19.00+）
- 备份密钥文件
- 网络连接

### 1.2 恢复前检查
1. 确认需要恢复的版本和时间点
2. 检查备份文件是否完整
3. 验证备份文件哈希值
4. 准备恢复目标仓库

## 2. 恢复操作流程

### 2.1 从本地备份恢复

#### 步骤1：定位备份文件
```powershell
# 查看最新备份目录
Get-ChildItem -Path D:\backups\github -Directory | Sort-Object CreationTime -Descending

# 选择需要恢复的版本
$backupDir = "D:\backups\github\20240210-020000"
```

#### 步骤2：验证备份完整性
```powershell
# 检查Git仓库镜像是否存在
Test-Path "$backupDir\hustle-mirror.git\config"

# 验证Git仓库完整性
cd "$backupDir\hustle-mirror.git"
git fsck --full
```

#### 步骤3：恢复到新仓库
```powershell
# 创建新仓库目录
$restoreDir = "D:\restore\hustle-new"
New-Item -ItemType Directory -Path $restoreDir -Force

# 克隆备份到新仓库
git clone "$backupDir\hustle-mirror.git" $restoreDir

# 检查恢复结果
cd $restoreDir
git branch -a
git log --oneline
```

### 2.2 从加密备份恢复

#### 步骤1：解密备份文件
```powershell
# 定位加密备份文件
$encryptedFile = "D:\backups\encrypted\20240210-020000.7z"
$password = Get-Content "D:\secrets\backup_key.txt" -Raw

# 使用7-Zip解密
$7zipPath = "C:\Program Files\7-Zip\7z.exe"
& $7zipPath x -p"$password" "$encryptedFile" -o"D:\restore\temp"
```

#### 步骤2：验证解密结果
```powershell
# 检查解密后的备份文件
Test-Path "D:\restore\temp\hustle-mirror.git\config"
```

#### 步骤3：恢复到Git仓库
```powershell
# 克隆到新仓库
git clone "D:\restore\temp\hustle-mirror.git" "D:\restore\hustle-restored"
```

### 2.3 从云存储恢复

#### 步骤1：下载云备份文件
```powershell
# 从腾讯云COS下载
coscmd download /github-backups/20240210-020000/ D:\restore\cloud --recursive

# 从阿里云OSS下载
ossutil cp oss://github-backups-2024/github-backups/20240210-020000/ D:\restore\cloud -r

# 从AWS S3下载
aws s3 cp s3://github-backups-2024/github-backups/20240210-020000/ D:\restore\cloud --recursive
```

#### 步骤2：验证下载文件
```powershell
# 检查文件完整性
Get-FileHash -Path "D:\restore\cloud\hustle-mirror.git\config" -Algorithm SHA256
```

#### 步骤3：恢复到本地仓库
```powershell
git clone "D:\restore\cloud\hustle-mirror.git" "D:\restore\hustle-cloud"
```

## 3. 恢复后验证

### 3.1 基本验证
```powershell
# 检查分支
cd D:\restore\hustle-restored
git branch -a

# 检查标签
git tag -l

# 检查提交历史
git log --oneline --all | Select-Object -First 10

# 检查仓库配置
git remote -v
```

### 3.2 功能验证
1. 编译项目（如果需要）
2. 运行单元测试
3. 验证关键功能
4. 检查依赖项

### 3.3 数据完整性验证
```powershell
# 统计提交次数
$totalCommits = (git log --oneline --all | Measure-Object -Line).Lines
Write-Host "总提交次数: $totalCommits"

# 统计文件数量
$totalFiles = (Get-ChildItem -Path . -Recurse -File | Measure-Object).Count
Write-Host "总文件数量: $totalFiles"
```

## 4. 故障排除

### 4.1 常见问题

#### 问题1：备份文件损坏
**解决方案：**
- 验证哈希值
- 尝试从云存储恢复
- 使用备用备份版本

#### 问题2：解密失败
**解决方案：**
- 检查密钥文件是否正确
- 验证密码是否正确
- 尝试使用其他解压工具

#### 问题3：Git仓库损坏
**解决方案：**
```powershell
# 修复Git仓库
git fsck --full
git repair

# 如果无法修复，使用其他备份版本
```

#### 问题4：网络连接问题
**解决方案：**
- 检查网络连接
- 尝试使用代理
- 切换到其他云存储提供商

### 4.2 恢复失败回滚
```powershell
# 删除不完整的恢复目录
Remove-Item -Path D:\restore\hustle-restored -Recurse -Force

# 清理临时文件
Remove-Item -Path D:\restore\temp -Recurse -Force
```

## 5. 恢复后操作

### 5.1 配置更新
1. 更新仓库远程地址
2. 配置用户信息
3. 设置分支跟踪

```powershell
# 更新远程地址
git remote set-url origin https://github.com/joycar2010/hustle-restored.git

# 配置用户信息
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 5.2 数据同步
```powershell
# 拉取最新变更
git pull origin main

# 推送恢复后的代码
git push --mirror origin
```

### 5.3 监控恢复结果
1. 检查GitHub仓库状态
2. 验证CI/CD流程
3. 通知团队成员

## 6. 恢复演练

### 6.1 定期演练计划
- 每月：基础恢复演练
- 每季度：完整恢复演练
- 每年：灾难恢复演练

### 6.2 演练步骤
1. 选择一个历史版本
2. 执行完整恢复流程
3. 记录恢复时间
4. 验证恢复结果
5. 生成演练报告

## 7. 紧急恢复联系信息

| 角色 | 姓名 | 联系方式 |
|------|------|----------|
| 系统管理员 | 张三 | 13800138001 |
| DevOps工程师 | 李四 | 13800138002 |
| 技术支持 | 王五 | 13800138003 |

## 8. 附录

### 8.1 恢复时间参考
| 恢复类型 | 预计时间 |
|---------|---------|
| 本地恢复 | 10-30分钟 |
| 加密恢复 | 20-60分钟 |
| 云存储恢复 | 30-120分钟 |

### 8.2 恢复成功率目标
- 本地恢复：99.9%
- 加密恢复：99.5%
- 云存储恢复：99.0%

### 8.3 相关文档
- 《GitHub备份策略文档》
- 《备份监控指南》
- 《安全管理规范》