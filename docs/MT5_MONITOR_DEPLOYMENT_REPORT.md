# MT5 健康监控系统部署报告

## 部署时间
2026-04-01

## 部署内容

### 1. 数据库配置 ✅

**位置**: GO 服务器 (go.hustle2026.xyz)
**数据库**: postgres

已成功创建 3 个通知模板：

| 模板 Key | 模板名称 | 优先级 | 冷却时间 | 状态 |
|---------|---------|--------|---------|------|
| mt5_client_error | MT5 客户端错误 | 4 (红色) | 300秒 | 已启用 |
| mt5_client_warning | MT5 客户端警告 | 3 (橙色) | 600秒 | 已启用 |
| mt5_client_info | MT5 客户端信息 | 2 (蓝色) | 1800秒 | 已启用 |

**验证命令**:
```bash
ssh -i c:/Users/HUAWEI/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz
sudo -u postgres psql postgres -c "SELECT template_key, template_name, priority, enable_feishu, is_active FROM notification_templates WHERE template_key LIKE 'mt5_%';"
```

### 2. 监控脚本上传 ✅

**目标服务器**: Windows MT5 服务器 (54.249.66.53)
**脚本位置**: C:\MT5Agent\scripts\

已上传文件：
- ✅ monitor_mt5_health_en.ps1 (10,258 字节) - 英文版监控脚本
- ✅ install_monitor_service.ps1 (5,170 字节) - 服务安装脚本
- ✅ check_mt5_status.ps1 (4,176 字节) - 状态检查脚本

**验证命令**:
```powershell
ssh -i /c/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53
Get-ChildItem C:\MT5Agent\scripts\*.ps1
```

### 3. MT5 实例状态 ✅

当前两个 MT5 实例均正常运行：

| 端口 | 实例名称 | Bridge 状态 | MT5 连接 |
|------|---------|------------|---------|
| 8001 | MT5-System-Service | OK | True |
| 8002 | MT5-01 (cq987) | OK | True |

**验证命令**:
```powershell
Invoke-RestMethod -Uri 'http://localhost:8001/health'
Invoke-RestMethod -Uri 'http://localhost:8002/health'
```

## 待完成步骤

### 步骤 1: 配置管理员凭据

监控脚本需要管理员账户来调用后端 API。

**选项 A: 使用现有管理员账户**
```powershell
# 在 Windows 服务器上
cd C:\MT5Agent\scripts

# 测试监控脚本（运行一个周期）
.\monitor_mt5_health_en.ps1 `
    -CheckInterval 10 `
    -AdminUsername "admin" `
    -AdminPassword "your_password" `
    -EnableAlert $false
```

**选项 B: 创建专用监控账户（推荐）**

1. 在管理后台创建新用户：
   - 用户名: monitor_user
   - 角色: 管理员
   - 配置飞书 Open ID

2. 使用专用账户测试：
```powershell
.\monitor_mt5_health_en.ps1 `
    -CheckInterval 10 `
    -AdminUsername "monitor_user" `
    -AdminPassword "monitor_password" `
    -EnableAlert $true
```

### 步骤 2: 安装 Windows 服务

测试成功后，安装为 Windows 服务实现自动监控：

```powershell
# 以管理员身份运行 PowerShell
cd C:\MT5Agent\scripts

# 安装服务
.\install_monitor_service.ps1 `
    -ServiceName "MT5HealthMonitor" `
    -CheckInterval 30 `
    -ApiBaseUrl "https://admin.hustle2026.xyz" `
    -AdminUsername "monitor_user" `
    -AdminPassword "monitor_password"

# 验证服务状态
Get-Service -Name MT5HealthMonitor

# 查看日志
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 20 -Wait
```

### 步骤 3: 配置飞书通知

确保管理员用户已配置飞书信息：

1. 登录管理后台: https://admin.hustle2026.xyz
2. 进入用户管理
3. 编辑管理员用户
4. 填写飞书 Open ID 或飞书手机号

**获取飞书 Open ID**:
- 方法 1: 通过飞书管理后台查看
- 方法 2: 使用测试端点获取

### 步骤 4: 测试警报功能

**方法 1: 手动触发测试**
```powershell
# 停止一个 MT5 Bridge 服务
Stop-Process -Name python -Force

# 等待监控检测（最多 30 秒）
# 检查是否收到飞书通知

# 重启服务
cd C:\MT5Agent
python main_v2.py
```

**方法 2: 使用后端测试端点**
```bash
# 获取访问令牌
TOKEN=$(curl -s -X POST https://admin.hustle2026.xyz/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' \
  | jq -r '.access_token')

# 测试飞书通知
curl -X POST "https://admin.hustle2026.xyz/api/v1/notifications/test/feishu?recipient=your_feishu_open_id" \
  -H "Authorization: Bearer $TOKEN"
```

## 架构说明

### 监控流程

```
┌─────────────────────────────────────────────────────────┐
│              Windows MT5 服务器                          │
│                                                          │
│  ┌──────────────┐      ┌──────────────┐                │
│  │  MT5-系统服务 │      │   MT5-01     │                │
│  │  (端口 8001) │      │  (端口 8002) │                │
│  └──────┬───────┘      └──────┬───────┘                │
│         │                     │                         │
│         └─────────┬───────────┘                         │
│                   │                                     │
│         ┌─────────▼─────────┐                          │
│         │  监控脚本 (PS1)    │                          │
│         │  - 健康检查       │                          │
│         │  - 状态缓存       │                          │
│         └─────────┬─────────┘                          │
└───────────────────┼─────────────────────────────────────┘
                    │ HTTPS
         ┌──────────▼──────────┐
         │   后端 API 服务器    │
         │  (FastAPI)          │
         │                     │
         │  ┌───────────────┐  │
         │  │ 认证服务      │  │
         │  │ 通知服务      │  │
         │  │ 模板引擎      │  │
         │  └───────┬───────┘  │
         └──────────┼──────────┘
                    │
         ┌──────────▼──────────┐
         │   飞书企业应用       │
         │  - 管理员接收通知   │
         │  - 卡片消息         │
         │  - 音频警报         │
         └─────────────────────┘
```

### 关键特性

1. **智能状态检测**: 只在状态变化时发送通知（健康→异常，异常→恢复）
2. **多维度检查**: Bridge 服务、MT5 连接、进程状态
3. **统一通知管理**: 通过后端 API 统一管理所有通知
4. **灵活模板系统**: 可在管理后台动态修改通知内容
5. **完整日志记录**: 本地日志 + 数据库日志双重记录

## 文档位置

- **使用指南**: d:\git\hustle2026\docs\MT5_HEALTH_MONITOR_GUIDE_V2.md
- **监控脚本**: d:\git\hustle2026\scripts\monitor_mt5_health_en.ps1
- **安装脚本**: d:\git\hustle2026\scripts\install_monitor_service.ps1
- **SQL 脚本**: d:\git\hustle2026\scripts\create_mt5_notification_templates.sql

## 故障排查

### 问题 1: API 认证失败

**症状**: 日志显示 "Failed to get API token"

**解决方案**:
```powershell
# 测试 API 登录
$body = @{username="admin"; password="your_password"} | ConvertTo-Json
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/auth/login" `
    -Method Post -Body $body -ContentType "application/json"
```

### 问题 2: 未收到飞书通知

**检查清单**:
1. ✅ 飞书服务已在后端配置
2. ✅ 通知模板已启用
3. ✅ 管理员用户已配置飞书 Open ID
4. ✅ 监控脚本使用正确的管理员凭据

**验证命令**:
```bash
# 检查飞书服务状态
curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/notifications/feishu/status

# 检查通知模板
curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/notifications/templates | jq '.templates[] | select(.template_key | startswith("mt5_"))'
```

### 问题 3: 监控脚本无法运行

**症状**: PowerShell 执行策略错误

**解决方案**:
```powershell
# 检查执行策略
Get-ExecutionPolicy

# 设置执行策略
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
```

## 下一步建议

1. **创建专用监控账户**: 提高安全性，限制权限范围
2. **配置音频警报**: 为严重故障添加音频提醒
3. **设置通知冷却**: 防止警报轰炸
4. **定期审查日志**: 每周检查监控日志和通知记录
5. **优化检查间隔**: 根据实际需求调整检查频率

## 联系信息

- **GO 服务器**: ssh -i c:/Users/HUAWEI/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz
- **Windows 服务器**: ssh -i /c/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53
- **管理后台**: https://admin.hustle2026.xyz
- **数据库**: postgres@127.0.0.1:5432/postgres

## 部署状态总结

| 项目 | 状态 | 备注 |
|------|------|------|
| 数据库模板创建 | ✅ 完成 | 3 个模板已创建 |
| 监控脚本上传 | ✅ 完成 | 英文版已上传 |
| MT5 实例状态 | ✅ 正常 | 两个实例均运行正常 |
| 服务安装 | ⏳ 待完成 | 需要配置管理员凭据 |
| 飞书通知测试 | ⏳ 待完成 | 需要配置用户飞书信息 |
| 端到端测试 | ⏳ 待完成 | 需要触发实际警报 |

---

**部署人员**: Claude AI Assistant
**部署日期**: 2026-04-01
**版本**: V2.0.0
