# Bridge 服务迁移指南

## 概述

将旧版 Bridge 实例系统迁移到新版 Bridge 服务控制系统。

## 迁移步骤

### 步骤 1：数据同步

在 Linux 服务器上执行：

```bash
# 1. 连接到服务器
ssh -i ~/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz

# 2. 查询现有 Bridge 服务
cd /home/ubuntu/hustle2026
PGPASSWORD=Lk106504 psql -h 127.0.0.1 -U postgres -d postgres -c "
SELECT
    client_id,
    client_name,
    bridge_service_name,
    bridge_service_port,
    mt5_login,
    mt5_server
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');
"

# 3. 在 Windows 服务器上查询实际的 Bridge 服务
# 通过 RDP 或 SSH 连接到 Windows 服务器
# 执行：sc query | findstr /i "hustle-mt5"

# 4. 根据实际情况更新数据库
# 下载 sync_bridge_data.sql 文件并修改其中的服务名称和端口号
# 然后执行：
PGPASSWORD=Lk106504 psql -h 127.0.0.1 -U postgres -d postgres -f sync_bridge_data.sql
```

### 步骤 2：清理 Windows 服务器

在 Windows 服务器上执行：

```powershell
# 1. 连接到 Windows 服务器
# RDP: 35.77.212.24
# 或 SSH: ssh -i ~/.ssh/id_ed25519 Administrator@35.77.212.24

# 2. 下载并执行清理脚本
# 将 cleanup_windows_server.ps1 复制到服务器
# 然后以管理员身份运行：
.\cleanup_windows_server.ps1

# 3. 手动删除 C:\hustle-agent（如果存在）
if (Test-Path "C:\hustle-agent") {
    Remove-Item "C:\hustle-agent" -Recurse -Force
    Write-Host "C:\hustle-agent 已删除"
}
```

### 步骤 3：更新前端

```bash
# 1. 在本地构建前端
cd d:/git/hustle2026/frontend
npx vite build --config vite.config.admin.js

# 2. 部署到服务器
scp -i ~/.ssh/HustleNew.pem -r dist-admin/* ubuntu@go.hustle2026.xyz:/home/ubuntu/hustle2026/frontend-admin/dist/
```

### 步骤 4：验证迁移

1. **访问管理后台**：https://admin.hustle2026.xyz/users
2. **检查 MT5-01 和 MT5-Sys-Server**：
   - 应该看到"Bridge服务"区域（不是"Bridge实例"）
   - 显示服务状态、服务名称、端口号
   - 有启动/停止/重启/删除按钮
3. **测试控制功能**：
   - 点击启动/停止/重启按钮
   - 检查服务是否正常响应

## 数据库字段说明

### mt5_clients 表

新增字段：
- `bridge_service_name`: Bridge Windows 服务名称（如：hustle-mt5-mt5-01）
- `bridge_service_port`: Bridge HTTP 服务端口（如：8002）

### 迁移映射

| 旧系统 (mt5_instances) | 新系统 (mt5_clients) |
|------------------------|---------------------|
| instance_name          | bridge_service_name |
| service_port           | bridge_service_port |

## 服务命名规范

Bridge 服务名称格式：`hustle-mt5-{client_name}`

示例：
- MT5-01 → hustle-mt5-mt5-01
- MT5-Sys-Server → hustle-mt5-mt5-sys-server

## 目录结构

### Windows 服务器

**保留**：
- `C:\MT5Agent\` - Windows Agent 主目录
  - `main_v3.py` - Agent 主程序
  - `config.json` - 配置文件
  - `logs\` - 日志目录
  - `backup_*\` - 备份目录

**删除**：
- `C:\hustle-agent\` - 旧版本，与当前系统无关

**Bridge 部署目录**：
- `D:\hustle-mt5-*\` - Bridge 服务部署目录
- `D:\MetaTrader 5-*\` - MT5 客户端目录

## 故障排查

### 问题 1：Bridge 服务控制区域不显示

**原因**：数据库中 bridge_service_name 字段为空

**解决**：执行 sync_bridge_data.sql 同步数据

### 问题 2：点击控制按钮无响应

**原因**：Windows Agent 服务未运行或配置错误

**解决**：
```powershell
# 检查服务状态
sc query MT5Agent

# 重启服务
nssm restart MT5Agent
```

### 问题 3：503 错误

**原因**：后端无法连接到 Windows Agent

**解决**：
1. 检查 Windows Agent 服务是否运行
2. 检查防火墙设置
3. 检查 API Key 配置

## 回滚方案

如果迁移出现问题，可以回滚：

1. **恢复前端**：
```bash
# 从 git 恢复旧版本
git checkout HEAD~1 frontend/src-admin/views/UserManagement.vue
npm run build:admin
# 重新部署
```

2. **清空数据库字段**：
```sql
UPDATE mt5_clients
SET bridge_service_name = NULL, bridge_service_port = NULL
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');
```

3. **恢复 Windows Agent**：
```powershell
# 从备份恢复
Copy-Item "C:\MT5Agent\backup_*\main_v3.py" "C:\MT5Agent\main_v3.py" -Force
nssm restart MT5Agent
```

## 完成检查清单

- [ ] 数据库已同步（bridge_service_name 和 bridge_service_port 已填充）
- [ ] Windows 服务器已清理（C:\hustle-agent 已删除）
- [ ] 前端已更新（旧版 Bridge 实例区域已删除）
- [ ] Bridge 服务控制功能正常（启动/停止/重启可用）
- [ ] Windows Agent 远程控制功能正常
- [ ] 所有 Bridge 服务正常运行

## 注意事项

1. **备份优先**：执行任何操作前先备份数据库和配置文件
2. **逐步验证**：每完成一步都要验证功能正常
3. **保留日志**：保留迁移过程中的所有日志以便排查问题
4. **测试环境**：如果可能，先在测试环境验证迁移流程
