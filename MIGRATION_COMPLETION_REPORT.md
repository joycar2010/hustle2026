# Bridge 服务迁移完成报告

## 已完成的工作

### 1. 数据库配置 ✅
- MT5-01: `hustle-mt5-cq987`, 端口 8002
- MT5-Sys-Server: `hustle-mt5-system`, 端口 8001
- 数据库字段已正确填充

### 2. Windows 服务状态 ✅
- `hustle-mt5-cq987` (MT5-01) - **运行中**
- `hustle-mt5-system` (MT5-Sys-Server) - **已停止**

### 3. 目录清理 ✅
- `C:\hustle-agent` - **已删除**
- `C:\MT5Agent` - 清理脚本已创建并上传

### 4. 前端更新 ✅
- 旧版 Bridge 实例区域已删除
- 只保留新版 Bridge 服务控制功能
- 前端已部署到服务器

## 待完成的操作

### 1. 执行 C:\MT5Agent 清理（手动）

由于网络连接不稳定，请在 Windows 服务器上手动执行：

```powershell
# 方法1：通过 RDP 连接
# 打开 PowerShell，执行：
cd C:\MT5Agent
.\cleanup_mt5agent.ps1

# 方法2：通过 SSH（如果连接稳定）
ssh -i ~/.ssh/id_ed25519 Administrator@35.77.212.24
powershell -ExecutionPolicy Bypass -File C:\MT5Agent\cleanup_mt5agent.ps1
```

清理脚本会：
- 创建新备份（main_v3.py, config.json, instances.json）
- 删除所有临时和开发文件（main.py, main_v2.py, main_v4.py 等）
- 保留最新的 3 个备份目录
- 显示保留的文件列表

### 2. 测试前端功能

1. **刷新浏览器**：Ctrl+F5
2. **访问**：https://admin.hustle2026.xyz/users
3. **检查 MT5-01**：
   - 应该看到"Bridge服务"区域
   - 服务名：hustle-mt5-cq987
   - 端口：8002
   - 状态：运行中
   - 控制按钮可用

4. **检查 MT5-Sys-Server**：
   - 应该看到"Bridge服务"区域
   - 服务名：hustle-mt5-system
   - 端口：8001
   - 状态：已停止
   - 可以通过"启动"按钮启动

## 系统配置

### Windows Agent 配置
- 部署目录：`C:\MT5Agent`
- 主程序：`main_v3.py`
- 配置文件：`config.json`
- 实例配置：`instances.json`
- 日志目录：`C:\MT5Agent\logs`

### Bridge 服务配置
- 服务命名：`hustle-mt5-{client_name}`
- 部署目录：`D:\hustle-mt5-*`
- MT5 客户端：`D:\MetaTrader 5-*`
- 桌面快捷方式：`C:\Users\Administrator\Desktop\MT5 {login}+{port}.lnk`

## 保留的文件

清理后 C:\MT5Agent 应该只包含：

**必需文件**：
- `main_v3.py` - 当前运行的主程序
- `main_v3.py.backup` - 主程序备份
- `config.json` - 配置文件
- `instances.json` - 实例配置
- `requirements.txt` - Python 依赖

**安装脚本**（可选保留）：
- `install-agent-service.ps1`
- `install-service.ps1`
- `install-task.ps1`

**文档**（可选保留）：
- `README.md`
- `MT5_GUI_SOLUTION.md`
- `MT5_OPERATION_GUIDE.md`

**目录**：
- `logs/` - 日志目录
- `scripts/` - 脚本目录
- `backup_*/` - 备份目录（最多保留3个）

## 验证清单

- [ ] C:\hustle-agent 已删除
- [ ] C:\MT5Agent 临时文件已清理
- [ ] 前端显示新版 Bridge 服务控制
- [ ] MT5-01 Bridge 服务可控制
- [ ] MT5-Sys-Server Bridge 服务可控制
- [ ] 旧版 Bridge 实例区域已消失

## 故障排查

### 问题1：前端不显示 Bridge 服务控制

**检查**：
```sql
SELECT client_id, client_name, bridge_service_name, bridge_service_port
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');
```

**预期**：两个字段都应该有值

### 问题2：控制按钮无响应

**检查 Windows Agent**：
```powershell
sc query MT5Agent
```

**预期**：STATE = RUNNING

### 问题3：503 错误

**检查网络连接**：
```bash
curl -H "X-API-Key: HustleXAU_MT5_Agent_Key_2026" http://172.31.14.113:8765/health
```

**预期**：返回 200 OK

## 下一步建议

1. **立即测试**：刷新浏览器，验证前端功能
2. **手动清理**：在 Windows 服务器上执行清理脚本
3. **启动服务**：如果需要，启动 hustle-mt5-system 服务
4. **监控日志**：观察 C:\MT5Agent\logs\agent.log 确保无错误

## 相关文档

- `QUICK_MIGRATION_GUIDE.md` - 快速迁移指南
- `BRIDGE_MIGRATION_GUIDE.md` - 完整迁移指南
- `cleanup_mt5agent.ps1` - MT5Agent 清理脚本
- `sync_bridge_data.sql` - 数据库同步脚本
