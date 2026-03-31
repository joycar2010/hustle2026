# MT5 健康监控系统使用指南 V2

## 概述

MT5 健康监控系统 V2 通过后端 API 实现实时监控 MT5 客户端和 Bridge 服务的健康状态，并在检测到异常时通过飞书和弹窗通知管理员。

## 版本变更

### V2 新特性
- ✅ 通过后端 API 统一管理通知
- ✅ 支持飞书卡片消息和音频警报
- ✅ 自动获取管理员用户列表
- ✅ 基于通知模板的灵活配置
- ✅ 完整的通知日志记录
- ✅ 更好的安全性（API 认证）

### 与 V1 的区别
| 特性 | V1 | V2 |
|------|----|----|
| 飞书通知 | 直接调用 Webhook | 通过后端 API |
| 弹窗警报 | Windows Forms | 通过后端 API |
| 用户管理 | 手动配置 | 自动获取管理员 |
| 通知模板 | 硬编码 | 数据库配置 |
| 日志记录 | 本地文件 | 本地 + 数据库 |

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│              MT5 健康监控服务 V2                         │
│                                                          │
│  ┌──────────────┐      ┌──────────────┐                │
│  │  MT5-系统服务 │      │   MT5-01     │                │
│  │  (端口 8001) │      │  (端口 8002) │                │
│  └──────┬───────┘      └──────┬───────┘                │
│         │                     │                         │
│         └─────────┬───────────┘                         │
│                   │                                     │
│         ┌─────────▼─────────┐                          │
│         │  健康检查引擎      │                          │
│         │  - Bridge 服务    │                          │
│         │  - MT5 连接状态   │                          │
│         │  - MT5 进程状态   │                          │
│         └─────────┬─────────┘                          │
│                   │                                     │
│         ┌─────────▼─────────┐                          │
│         │   后端 API 调用    │                          │
│         │  - 认证登录       │                          │
│         │  - 获取管理员     │                          │
│         │  - 发送通知       │                          │
│         └─────────┬─────────┘                          │
└───────────────────┼─────────────────────────────────────┘
                    │
         ┌──────────▼──────────┐
         │   后端服务器         │
         │  (FastAPI)          │
         │                     │
         │  ┌───────────────┐  │
         │  │ 通知服务      │  │
         │  │ - 飞书 API    │  │
         │  │ - 模板渲染    │  │
         │  │ - 日志记录    │  │
         │  └───────────────┘  │
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │   飞书企业应用       │
         │  - 卡片消息         │
         │  - 音频警报         │
         │  - 推送通知         │
         └─────────────────────┘
```

## 快速开始

### 前置条件

1. **PowerShell 5.1+** (Windows 10/11 自带)
2. **管理员权限** (安装服务时需要)
3. **后端 API 访问权限** (管理员账户)
4. **飞书企业应用** (已在后端配置)

### 步骤 1：配置后端通知服务

#### 1.1 配置飞书服务

登录管理后台：https://admin.hustle2026.xyz

导航到：系统设置 → 通知配置

配置飞书服务：
- App ID: 你的飞书应用 ID
- App Secret: 你的飞书应用密钥
- 启用服务：是

#### 1.2 配置通知模板

在通知模板管理中，确保以下模板已配置：

| 模板 Key | 模板名称 | 用途 | 优先级 |
|---------|---------|------|--------|
| `mt5_client_error` | MT5 客户端错误 | 严重故障警报 | 4 (红色) |
| `mt5_client_warning` | MT5 客户端警告 | 一般异常警报 | 3 (橙色) |
| `mt5_client_info` | MT5 客户端信息 | 恢复通知 | 2 (蓝色) |

如果模板不存在，需要在数据库中创建：

```sql
-- 连接到数据库
psql -U hustle -d hustle2026

-- 创建 MT5 监控通知模板
INSERT INTO notification_templates (
    template_key, template_name, category,
    title_template, content_template,
    enable_feishu, priority, cooldown_seconds
) VALUES
('mt5_client_error', 'MT5 客户端错误', 'system',
 '🚨 {title}', '{content}',
 true, 4, 300),
('mt5_client_warning', 'MT5 客户端警告', 'system',
 '⚠️ {title}', '{content}',
 true, 3, 300),
('mt5_client_info', 'MT5 客户端信息', 'system',
 'ℹ️ {title}', '{content}',
 true, 2, 300);
```

### 步骤 2：安装监控服务

#### 2.1 准备脚本

确保脚本文件存在：
- `d:\git\hustle2026\scripts\monitor_mt5_health_v2.ps1`
- `d:\git\hustle2026\scripts\install_monitor_service.ps1`

#### 2.2 安装服务

以管理员身份运行 PowerShell：

```powershell
cd d:\git\hustle2026\scripts

# 基础安装（需要手动输入密码）
.\install_monitor_service.ps1 -AdminUsername "admin" -AdminPassword "your_password"

# 自定义配置
.\install_monitor_service.ps1 `
    -ServiceName "MT5Monitor" `
    -CheckInterval 60 `
    -ApiBaseUrl "https://admin.hustle2026.xyz" `
    -AdminUsername "admin" `
    -AdminPassword "your_password"
```

**安全建议**：
- 使用专门的监控账户而不是主管理员账户
- 定期更换密码
- 限制监控账户的权限（仅需通知发送权限）

#### 2.3 验证服务状态

```powershell
# 查看服务状态
Get-Service -Name MT5HealthMonitor

# 查看实时日志
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 20 -Wait

# 检查 API 连接
# 日志中应该看到 "API 令牌获取成功"
```

### 步骤 3：测试警报功能

#### 3.1 手动触发测试

停止一个 MT5 实例来触发警报：

```powershell
# 停止 MT5-01 的 Bridge 服务
Stop-Process -Name "python" -Force

# 等待监控检测（最多 CheckInterval 秒）
# 查看日志确认警报已发送
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 10
```

#### 3.2 验证飞书通知

检查飞书是否收到通知：
- 管理员应该收到飞书卡片消息
- 消息包含实例名称、错误详情、时间戳
- 消息颜色应为红色（错误级别）

#### 3.3 恢复服务

```powershell
# 重启 Bridge 服务
cd C:\MT5Agent
python main_v2.py

# 等待监控检测恢复
# 应该收到恢复通知（蓝色卡片）
```

## 服务管理

### 启动/停止服务

```powershell
# 启动服务
Start-Service -Name MT5HealthMonitor

# 停止服务
Stop-Service -Name MT5HealthMonitor

# 重启服务
Restart-Service -Name MT5HealthMonitor

# 查看服务详细状态
Get-Service -Name MT5HealthMonitor | Format-List *
```

### 修改配置

#### 方法 1：重新安装服务

```powershell
# 停止并删除现有服务
Stop-Service -Name MT5HealthMonitor -Force
sc.exe delete MT5HealthMonitor

# 使用新配置重新安装
.\install_monitor_service.ps1 -CheckInterval 60 -AdminUsername "new_user"
```

#### 方法 2：使用 NSSM 修改（如果使用 NSSM 安装）

```powershell
# 打开 NSSM GUI
nssm edit MT5HealthMonitor

# 在 "Arguments" 标签页修改参数
# 例如：-CheckInterval 60 改为 -CheckInterval 30
```

### 卸载服务

```powershell
# 停止服务
Stop-Service -Name MT5HealthMonitor -Force

# 删除服务
sc.exe delete MT5HealthMonitor

# 或使用 NSSM
nssm remove MT5HealthMonitor confirm
```

## 日志管理

### 日志位置

| 日志类型 | 路径 | 说明 |
|---------|------|------|
| 监控日志 | `C:\MT5Agent\logs\health_monitor.log` | 健康检查结果和警报记录 |
| 服务日志 | `C:\MT5Agent\logs\monitor_service_stdout.log` | 服务运行输出（NSSM） |
| 后端日志 | 数据库 `notification_logs` 表 | 通知发送记录 |

### 查看日志

```powershell
# 查看最近 50 行
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 50

# 实时监控日志
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 20 -Wait

# 搜索错误日志
Select-String -Path C:\MT5Agent\logs\health_monitor.log -Pattern "ERROR"

# 查看警报发送记录
Select-String -Path C:\MT5Agent\logs\health_monitor.log -Pattern "ALERT"

# 查看 API 认证日志
Select-String -Path C:\MT5Agent\logs\health_monitor.log -Pattern "API 令牌"
```

### 查看后端通知日志

通过管理后台查看：
https://admin.hustle2026.xyz/系统设置/通知日志

或通过 API：

```powershell
# 获取访问令牌
$token = "your_access_token"

# 查询通知日志
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/notifications/logs?limit=50" `
    -Headers @{"Authorization" = "Bearer $token"}
```

## 通知模板管理

### 查看模板

```powershell
# 通过 API 查看所有模板
$token = "your_access_token"
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/notifications/templates" `
    -Headers @{"Authorization" = "Bearer $token"}
```

### 修改模板

通过管理后台：系统设置 → 通知模板

可以修改：
- 标题模板
- 内容模板
- 优先级（影响卡片颜色）
- 冷却时间（防止警报轰炸）
- 启用/禁用状态

### 添加音频警报

1. 上传音频文件到后端
2. 在模板中设置 `alert_sound_file` 字段
3. 设置 `alert_sound_repeat` 循环次数

## 故障排查

### 问题 1: 服务无法启动

**症状**: `Start-Service` 失败或服务立即停止

**解决方案**:
```powershell
# 1. 检查脚本路径
Test-Path d:\git\hustle2026\scripts\monitor_mt5_health_v2.ps1

# 2. 手动运行脚本测试
cd d:\git\hustle2026\scripts
.\monitor_mt5_health_v2.ps1 -CheckInterval 10 -AdminUsername "admin" -AdminPassword "password"

# 3. 查看服务错误日志
Get-Content C:\MT5Agent\logs\monitor_service_stderr.log

# 4. 检查 PowerShell 执行策略
Get-ExecutionPolicy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
```

### 问题 2: API 认证失败

**症状**: 日志显示 "获取 API 令牌失败"

**解决方案**:
```powershell
# 1. 验证管理员凭据
$body = @{username="admin"; password="your_password"} | ConvertTo-Json
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/auth/login" `
    -Method Post -Body $body -ContentType "application/json"

# 2. 检查网络连接
Test-NetConnection -ComputerName admin.hustle2026.xyz -Port 443

# 3. 检查 SSL 证书
Invoke-WebRequest -Uri "https://admin.hustle2026.xyz" -UseBasicParsing

# 4. 查看详细错误
Get-Content C:\MT5Agent\logs\health_monitor.log | Select-String "API 令牌"
```

### 问题 3: 未收到飞书通知

**症状**: 日志显示警报已发送但未收到飞书消息

**解决方案**:
```powershell
# 1. 检查飞书服务状态
$token = "your_access_token"
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/notifications/feishu/status" `
    -Headers @{"Authorization" = "Bearer $token"}

# 2. 检查通知模板是否启用飞书
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/notifications/templates" `
    -Headers @{"Authorization" = "Bearer $token"} |
    Select-Object -ExpandProperty templates |
    Where-Object { $_.template_key -like "mt5_*" }

# 3. 检查用户飞书配置
# 确保管理员用户配置了 feishu_open_id 或 feishu_mobile

# 4. 查看通知日志
Invoke-RestMethod -Uri "https://admin.hustle2026.xyz/api/v1/notifications/logs?limit=10" `
    -Headers @{"Authorization" = "Bearer $token"}
```

### 问题 4: 通知模板不存在

**症状**: 日志显示 "模板不存在"

**解决方案**:
```sql
-- 连接到数据库
ssh -i ~/.ssh/id_ed25519 ubuntu@go.hustle2026.xyz
sudo -u postgres psql hustle2026

-- 检查模板是否存在
SELECT template_key, template_name, is_active
FROM notification_templates
WHERE template_key LIKE 'mt5_%';

-- 如果不存在，创建模板（见"步骤 1.2"）
```

### 问题 5: 警报重复发送

**症状**: 同一个问题收到多次通知

**解决方案**:
```powershell
# 1. 检查状态缓存是否正常工作
# 查看日志中的状态变化记录

# 2. 增加模板冷却时间
# 在管理后台修改模板的 cooldown_seconds 字段

# 3. 检查是否有多个监控服务实例
Get-Service | Where-Object { $_.Name -like "*MT5*Monitor*" }

# 4. 确保只有一个服务在运行
Stop-Service -Name MT5HealthMonitor -Force
Start-Service -Name MT5HealthMonitor
```

## 最佳实践

### 1. 生产环境配置

```powershell
# 推荐配置
.\install_monitor_service.ps1 `
    -ServiceName "MT5HealthMonitor" `
    -CheckInterval 30 `
    -ApiBaseUrl "https://admin.hustle2026.xyz" `
    -AdminUsername "monitor_user" `
    -AdminPassword "strong_password_here"

# 说明:
# - 30 秒检查间隔平衡及时性和性能
# - 使用专门的监控账户（非主管理员）
# - 通过后端 API 统一管理通知
```

### 2. 安全建议

- **使用专用监控账户**: 创建权限最小化的监控专用账户
- **定期更换密码**: 每季度更换一次监控账户密码
- **限制日志访问**: 设置日志文件访问权限
- **审计通知记录**: 定期检查通知日志，发现异常模式

### 3. 通知模板优化

- **合理设置优先级**:
  - 4 (红色): 严重故障，需要立即处理
  - 3 (橙色): 一般异常，需要关注
  - 2 (蓝色): 信息通知，无需紧急处理

- **配置冷却时间**: 防止警报轰炸
  - 错误级别: 300 秒（5 分钟）
  - 警告级别: 600 秒（10 分钟）
  - 信息级别: 1800 秒（30 分钟）

- **使用音频警报**: 对于严重故障，配置音频提醒

### 4. 定期维护

```powershell
# 每周检查服务状态
Get-Service -Name MT5HealthMonitor
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 100

# 每月清理旧日志（保留最近 30 天）
$logPath = "C:\MT5Agent\logs"
Get-ChildItem $logPath -Filter "*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

# 每季度审查警报记录
# 通过管理后台查看通知统计
```

## 参数参考

### monitor_mt5_health_v2.ps1

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-Ports` | int[] | @(8001, 8002) | 要监控的端口列表 |
| `-CheckInterval` | int | 30 | 健康检查间隔（秒） |
| `-ApiBaseUrl` | string | https://admin.hustle2026.xyz | 后端 API 基础 URL |
| `-AdminUsername` | string | "" | 管理员用户名 |
| `-AdminPassword` | string | "" | 管理员密码 |
| `-EnableAlert` | bool | $true | 是否启用警报通知 |
| `-LogPath` | string | C:\MT5Agent\logs\health_monitor.log | 日志文件路径 |

### install_monitor_service.ps1

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-ServiceName` | string | MT5HealthMonitor | Windows 服务名称 |
| `-ApiBaseUrl` | string | https://admin.hustle2026.xyz | 后端 API 基础 URL |
| `-AdminUsername` | string | "" | 管理员用户名 |
| `-AdminPassword` | string | "" | 管理员密码 |
| `-CheckInterval` | int | 30 | 健康检查间隔（秒） |
| `-ScriptPath` | string | d:\git\hustle2026\scripts\monitor_mt5_health_v2.ps1 | 监控脚本路径 |

## 常见问题

**Q: V2 相比 V1 有什么优势？**
A: V2 通过后端 API 统一管理通知，支持更丰富的通知功能（音频警报、卡片消息），并提供完整的日志记录和审计功能。

**Q: 监控服务会影响 MT5 性能吗？**
A: 不会。监控脚本仅调用 HTTP API 和检查进程状态，资源占用极低（<1% CPU，<50MB 内存）。

**Q: 如何添加更多管理员接收通知？**
A: 在用户管理中将用户角色设置为"管理员"或"系统管理员"，并配置其飞书 Open ID。

**Q: 可以自定义通知内容吗？**
A: 可以。在管理后台的通知模板中修改标题和内容模板，支持变量替换。

**Q: 如何临时禁用通知？**
A: 方法 1：停止监控服务 `Stop-Service -Name MT5HealthMonitor`
   方法 2：在管理后台禁用通知模板

**Q: 服务重启后配置会丢失吗？**
A: 不会。服务配置存储在 Windows 服务注册表中，通知配置存储在数据库中，重启后自动恢复。

## 技术支持

如遇问题，请提供以下信息：

1. **服务状态**: `Get-Service -Name MT5HealthMonitor | Format-List *`
2. **监控日志**: `Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 100`
3. **服务日志**: `Get-Content C:\MT5Agent\logs\monitor_service_stderr.log`
4. **API 测试**: 手动测试 API 登录和通知发送
5. **系统信息**: `Get-ComputerInfo | Select-Object WindowsVersion, OsArchitecture`

## 更新日志

### v2.0.0 (2026-04-01)
- 重构为基于后端 API 的架构
- 支持飞书卡片消息和音频警报
- 自动获取管理员用户列表
- 基于数据库的通知模板管理
- 完整的通知日志记录
- 改进的安全性（API 认证）

### v1.0.0 (2026-03-31)
- 初始版本
- 直接调用飞书 Webhook
- Windows Forms 弹窗
- 本地日志记录
