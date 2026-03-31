# MT5 健康监控系统使用指南

## 概述

MT5 健康监控系统提供实时监控 MT5 客户端和 Bridge 服务的健康状态，并在检测到异常时通过弹窗和飞书通知管理员。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                  MT5 健康监控服务                        │
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
│         │   警报分发器       │                          │
│         └─────────┬─────────┘                          │
│                   │                                     │
│         ┌─────────┴─────────┐                          │
│         │                   │                          │
│    ┌────▼────┐        ┌────▼────┐                     │
│    │ 弹窗警报 │        │飞书通知  │                     │
│    └─────────┘        └─────────┘                     │
└─────────────────────────────────────────────────────────┘
```

## 功能特性

### 1. 多维度健康检查
- **Bridge 服务健康**: 检查 `/health` 端点响应
- **MT5 连接状态**: 检查 `/mt5/connection/status` 端点
- **MT5 进程状态**: 检查 terminal64.exe 进程是否运行
- **会话信息**: 验证进程 SessionId 和窗口句柄

### 2. 智能警报机制
- **状态变化检测**: 只在状态从健康→异常或异常→恢复时发送通知
- **避免重复通知**: 使用状态缓存防止警报轰炸
- **恢复通知**: 实例恢复正常时自动发送恢复通知

### 3. 多渠道通知
- **Windows 弹窗**: 本地桌面弹窗警报（可选）
- **飞书机器人**: 企业即时通讯通知（可选）
- **日志记录**: 所有事件记录到日志文件

## 快速开始

### 前置条件

1. **PowerShell 5.1+** (Windows 10/11 自带)
2. **管理员权限** (安装服务时需要)
3. **飞书机器人 Webhook** (可选，用于飞书通知)

### 获取飞书 Webhook URL

1. 登录飞书管理后台
2. 进入「应用」→「机器人」
3. 创建自定义机器人
4. 复制 Webhook URL (格式: `https://open.feishu.cn/open-apis/bot/v2/hook/xxx`)

### 方式一：手动运行（测试用）

```powershell
# 基础运行（仅弹窗警报）
.\monitor_mt5_health.ps1

# 指定检查间隔
.\monitor_mt5_health.ps1 -CheckInterval 60

# 启用飞书通知
.\monitor_mt5_health.ps1 -FeishuWebhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

# 完整配置
.\monitor_mt5_health.ps1 `
    -Ports @(8001, 8002) `
    -CheckInterval 30 `
    -FeishuWebhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx" `
    -EnablePopup $true `
    -EnableFeishu $true
```

### 方式二：安装为 Windows 服务（推荐）

#### 步骤 1：安装 NSSM（推荐）

NSSM (Non-Sucking Service Manager) 是一个优秀的 Windows 服务管理工具。

```powershell
# 下载 NSSM
# 访问 https://nssm.cc/download 下载最新版本

# 解压到 C:\Tools\nssm.exe
# 或者使用 Chocolatey 安装
choco install nssm
```

#### 步骤 2：安装监控服务

```powershell
# 以管理员身份运行 PowerShell
cd d:\git\hustle2026\scripts

# 基础安装
.\install_monitor_service.ps1

# 带飞书通知
.\install_monitor_service.ps1 -FeishuWebhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

# 自定义配置
.\install_monitor_service.ps1 `
    -ServiceName "MT5Monitor" `
    -CheckInterval 60 `
    -FeishuWebhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
```

#### 步骤 3：验证服务状态

```powershell
# 查看服务状态
Get-Service -Name MT5HealthMonitor

# 查看实时日志
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 20 -Wait

# 检查服务日志（如果使用 NSSM）
Get-Content C:\MT5Agent\logs\monitor_service_stdout.log -Tail 20
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

# 查看服务状态
Get-Service -Name MT5HealthMonitor | Format-List *
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

### 修改服务配置

```powershell
# 使用 NSSM GUI 修改配置
nssm edit MT5HealthMonitor

# 或重新安装服务（会覆盖现有配置）
.\install_monitor_service.ps1 -FeishuWebhook "新的Webhook地址"
```

## 日志管理

### 日志位置

| 日志类型 | 路径 | 说明 |
|---------|------|------|
| 监控日志 | `C:\MT5Agent\logs\health_monitor.log` | 健康检查结果和警报记录 |
| 服务标准输出 | `C:\MT5Agent\logs\monitor_service_stdout.log` | 服务运行输出（NSSM） |
| 服务错误输出 | `C:\MT5Agent\logs\monitor_service_stderr.log` | 服务错误信息（NSSM） |

### 查看日志

```powershell
# 查看最近 50 行
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 50

# 实时监控日志
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 20 -Wait

# 搜索错误日志
Select-String -Path C:\MT5Agent\logs\health_monitor.log -Pattern "ERROR"

# 查看今天的警报
Get-Content C:\MT5Agent\logs\health_monitor.log | Select-String "ALERT"
```

### 日志轮转

NSSM 自动配置日志轮转：
- 单个日志文件最大 10MB
- 超过大小自动创建新文件
- 旧文件自动重命名（添加时间戳）

## 警报示例

### 弹窗警报

当检测到异常时，会显示 Windows 消息框：

```
标题: MT5 实例异常: MT5-系统服务
内容:
端口: 8001
错误: MT5 未连接到服务器;

详细状态:
- Bridge 服务: 运行中
- MT5 连接: 未连接
- MT5 进程: 运行中
```

### 飞书通知

飞书机器人会发送富文本卡片消息：

```
🚨 MT5 监控警报

警报级别: Error
服务器: WIN-MT5-SERVER
时间: 2026-03-31 14:30:25

标题: MT5 实例异常: MT5-系统服务

详情: 端口: 8001
错误: MT5 未连接到服务器;

详细状态:
- Bridge 服务: 运行中
- MT5 连接: 未连接
- MT5 进程: 运行中
```

## 故障排查

### 问题 1: 服务无法启动

**症状**: `Start-Service` 失败或服务立即停止

**解决方案**:
```powershell
# 1. 检查脚本路径是否正确
Test-Path d:\git\hustle2026\scripts\monitor_mt5_health.ps1

# 2. 手动运行脚本测试
cd d:\git\hustle2026\scripts
.\monitor_mt5_health.ps1 -CheckInterval 10

# 3. 查看服务错误日志
Get-Content C:\MT5Agent\logs\monitor_service_stderr.log

# 4. 检查 PowerShell 执行策略
Get-ExecutionPolicy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
```

### 问题 2: 飞书通知未收到

**症状**: 弹窗正常但飞书无通知

**解决方案**:
```powershell
# 1. 检查 Webhook URL 是否正确
# 2. 手动测试飞书 API
$webhook = "你的Webhook地址"
$body = @{
    msg_type = "text"
    content = @{
        text = "测试消息"
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri $webhook -Method Post -Body $body -ContentType "application/json"

# 3. 检查网络连接
Test-NetConnection -ComputerName open.feishu.cn -Port 443

# 4. 查看监控日志中的错误
Select-String -Path C:\MT5Agent\logs\health_monitor.log -Pattern "飞书"
```

### 问题 3: 弹窗未显示

**症状**: 日志显示警报但无弹窗

**原因**: 服务运行在 Session 0，无法显示 GUI

**解决方案**:
```powershell
# 方案 A: 禁用弹窗，仅使用飞书通知
# 修改服务参数添加 -EnablePopup $false

# 方案 B: 使用任务计划程序在用户会话运行
# 创建任务计划程序任务，触发器设为"用户登录时"
```

### 问题 4: 误报警（实际正常但报异常）

**症状**: MT5 运行正常但收到警报

**解决方案**:
```powershell
# 1. 手动检查 MT5 状态
.\check_mt5_status.ps1 -Port 8001

# 2. 检查 Bridge 服务是否正常响应
Invoke-RestMethod -Uri "http://localhost:8001/health"
Invoke-RestMethod -Uri "http://localhost:8001/mt5/connection/status"

# 3. 增加检查间隔避免瞬时波动
# 修改 -CheckInterval 参数为更大值（如 60 秒）

# 4. 查看详细日志
Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 100
```

## 最佳实践

### 1. 生产环境配置

```powershell
# 推荐配置
.\install_monitor_service.ps1 `
    -ServiceName "MT5HealthMonitor" `
    -CheckInterval 30 `
    -FeishuWebhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

# 说明:
# - 30 秒检查间隔平衡及时性和性能
# - 使用飞书通知确保管理员及时收到警报
# - 弹窗在服务模式下可能无法显示，建议禁用
```

### 2. 测试环境配置

```powershell
# 测试配置（更频繁检查）
.\monitor_mt5_health.ps1 `
    -CheckInterval 10 `
    -EnablePopup $true `
    -EnableFeishu $false

# 说明:
# - 10 秒快速检查便于测试
# - 启用弹窗便于本地观察
# - 禁用飞书避免测试期间打扰
```

### 3. 定期维护

```powershell
# 每周检查服务状态
Get-Service -Name MT5HealthMonitor

# 每月清理旧日志（保留最近 30 天）
$logPath = "C:\MT5Agent\logs"
Get-ChildItem $logPath -Filter "*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

# 每季度审查警报记录
Select-String -Path C:\MT5Agent\logs\health_monitor.log -Pattern "ALERT" |
    Group-Object -Property Line |
    Sort-Object Count -Descending
```

### 4. 安全建议

- 限制日志文件访问权限
- 定期轮换飞书 Webhook URL
- 监控服务账户权限
- 审计警报通知记录

## 参数参考

### monitor_mt5_health.ps1

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-Ports` | int[] | @(8001, 8002) | 要监控的端口列表 |
| `-CheckInterval` | int | 30 | 健康检查间隔（秒） |
| `-FeishuWebhook` | string | "" | 飞书机器人 Webhook URL |
| `-EnablePopup` | bool | $true | 是否启用弹窗警报 |
| `-EnableFeishu` | bool | $true | 是否启用飞书通知 |
| `-LogPath` | string | C:\MT5Agent\logs\health_monitor.log | 日志文件路径 |

### install_monitor_service.ps1

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-ServiceName` | string | MT5HealthMonitor | Windows 服务名称 |
| `-FeishuWebhook` | string | "" | 飞书机器人 Webhook URL |
| `-CheckInterval` | int | 30 | 健康检查间隔（秒） |
| `-ScriptPath` | string | d:\git\hustle2026\scripts\monitor_mt5_health.ps1 | 监控脚本路径 |

## 常见问题

**Q: 监控服务会影响 MT5 性能吗？**
A: 不会。监控脚本仅调用 HTTP API 和检查进程状态，资源占用极低（<1% CPU，<50MB 内存）。

**Q: 可以监控更多端口吗？**
A: 可以。修改 `-Ports` 参数添加更多端口，如 `-Ports @(8001, 8002, 8003, 8004)`。

**Q: 如何自定义警报消息？**
A: 编辑 `monitor_mt5_health.ps1` 中的 `Send-FeishuAlert` 和 `Show-Alert` 函数。

**Q: 可以发送邮件通知吗？**
A: 可以。参考 `Send-FeishuAlert` 函数添加 `Send-MailMessage` 调用。

**Q: 服务重启后配置会丢失吗？**
A: 不会。服务配置存储在 Windows 服务注册表中，重启后自动恢复。

## 技术支持

如遇问题，请提供以下信息：

1. 服务状态: `Get-Service -Name MT5HealthMonitor | Format-List *`
2. 最近日志: `Get-Content C:\MT5Agent\logs\health_monitor.log -Tail 100`
3. 错误信息: `Get-Content C:\MT5Agent\logs\monitor_service_stderr.log`
4. 系统信息: `Get-ComputerInfo | Select-Object WindowsVersion, OsArchitecture`

## 更新日志

### v1.0.0 (2026-03-31)
- 初始版本发布
- 支持多实例监控
- 弹窗和飞书双通道警报
- Windows 服务模式
- 智能状态变化检测
- 自动日志轮转
