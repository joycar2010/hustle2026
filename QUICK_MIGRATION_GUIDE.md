# Bridge 服务迁移 - 快速执行指南

## 当前状态

✅ **已完成**：
- 前端旧版 Bridge 实例区域已删除
- 前端已部署到服务器
- 迁移脚本已创建

⏳ **待执行**：
- 数据库数据同步
- Windows 服务器清理

## 立即执行步骤

### 步骤 1：同步数据库（5分钟）

```bash
# 1. SSH 连接到 Linux 服务器
ssh -i ~/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz

# 2. 查询当前 Bridge 服务配置
PGPASSWORD=Lk106504 psql -h 127.0.0.1 -U postgres -d postgres << 'EOF'
-- 查看当前配置
SELECT client_id, client_name, bridge_service_name, bridge_service_port
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');

-- 更新 MT5-01（假设服务名为 hustle-mt5-mt5-01，端口 8002）
UPDATE mt5_clients
SET bridge_service_name = 'hustle-mt5-mt5-01', bridge_service_port = 8002
WHERE client_name = 'MT5-01' AND bridge_service_name IS NULL;

-- 更新 MT5-Sys-Server（假设服务名为 hustle-mt5-mt5-sys-server，端口 8001）
UPDATE mt5_clients
SET bridge_service_name = 'hustle-mt5-mt5-sys-server', bridge_service_port = 8001
WHERE client_name = 'MT5-Sys-Server' AND bridge_service_name IS NULL;

-- 验证更新
SELECT client_id, client_name, bridge_service_name, bridge_service_port
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');
EOF
```

**注意**：请根据实际的服务名称和端口号修改上面的 UPDATE 语句。

### 步骤 2：验证 Windows 服务（2分钟）

```powershell
# 在 Windows 服务器上执行
# RDP 或 SSH: ssh -i ~/.ssh/id_ed25519 Administrator@35.77.212.24

# 查询实际的 Bridge 服务名称和端口
sc query | findstr /i "hustle-mt5"

# 查看服务详情
sc qc hustle-mt5-mt5-01
sc qc hustle-mt5-mt5-sys-server
```

### 步骤 3：清理 Windows 服务器（可选，5分钟）

```powershell
# 1. 删除 C:\hustle-agent（如果存在）
if (Test-Path "C:\hustle-agent") {
    Remove-Item "C:\hustle-agent" -Recurse -Force
    Write-Host "C:\hustle-agent 已删除"
}

# 2. 清理 C:\MT5Agent 临时文件
Remove-Item "C:\MT5Agent\*.pyc" -Force -ErrorAction SilentlyContinue
Remove-Item "C:\MT5Agent\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "C:\MT5Agent\*.log.old" -Force -ErrorAction SilentlyContinue

Write-Host "清理完成"
```

### 步骤 4：测试功能（3分钟）

1. **刷新浏览器**：Ctrl+F5
2. **访问**：https://admin.hustle2026.xyz/users
3. **检查 MT5-01**：
   - 应该看到"Bridge服务"区域（不是"Bridge实例"）
   - 显示服务名称和端口号
   - 有启动/停止/重启按钮
4. **测试控制**：
   - 点击停止按钮
   - 等待几秒，状态应该变为"已停止"
   - 点击启动按钮
   - 等待几秒，状态应该变为"运行中"

## 如果数据库更新后仍看不到 Bridge 服务控制

可能原因：服务名称或端口号不正确

**解决方法**：

1. 在 Windows 服务器上查询实际的服务：
```powershell
sc query | findstr /i "hustle"
```

2. 根据实际服务名称更新数据库：
```sql
UPDATE mt5_clients
SET bridge_service_name = '实际的服务名称', bridge_service_port = 实际的端口号
WHERE client_name = 'MT5-01';
```

3. 刷新浏览器

## 常见问题

### Q1: 如何确定正确的服务名称？

A: 在 Windows 服务器上执行：
```powershell
sc query | findstr /i "hustle-mt5"
```
输出中的 `SERVICE_NAME:` 后面就是服务名称。

### Q2: 如何确定正确的端口号？

A: 查看服务配置：
```powershell
# 方法1：查看 nssm 配置
nssm get hustle-mt5-mt5-01 AppParameters

# 方法2：查看 .env 文件
Get-Content D:\hustle-mt5-mt5-01\.env | Select-String "SERVICE_PORT"
```

### Q3: 更新数据库后前端还是不显示？

A: 
1. 强制刷新浏览器（Ctrl+F5）
2. 清除浏览器缓存
3. 检查浏览器控制台是否有错误

### Q4: 503 错误怎么办？

A: 检查 Windows Agent 服务：
```powershell
sc query MT5Agent
# 如果未运行，重启服务
nssm restart MT5Agent
```

## 完成后的状态

✅ 数据库已同步
✅ 前端显示新版 Bridge 服务控制
✅ 旧版 Bridge 实例区域已消失
✅ Windows 服务器已清理
✅ 所有功能正常工作

## 需要帮助？

如果遇到问题，请提供：
1. 数据库查询结果（SELECT 语句的输出）
2. Windows 服务列表（sc query 的输出）
3. 浏览器控制台错误信息
4. 前端截图
