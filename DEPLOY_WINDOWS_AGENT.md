# Windows Agent 部署说明

## 问题描述
Windows Agent 的进程匹配逻辑存在问题：
- 原逻辑依赖命令行参数中的账户号（`/login:{account}`）来匹配进程
- MT5 进程启动后，命令行参数可能不保留
- 导致 `is_instance_running()` 无法找到进程
- `stop_instance()` 因此认为进程没有运行，直接返回 True
- 实际上进程还在运行，但没有被停止

## 修复方案
改为仅使用 MT5 路径匹配进程，不再依赖账户号：
- 每个 MT5 实例有独立的安装路径（如 `D:\MetaTrader 5-01\terminal64.exe`）
- 路径匹配已足够精确，无需账户号
- 简化了逻辑，提高了可靠性

## 部署步骤

### 1. 连接到 Windows 服务器
```
服务器地址: 172.31.14.113
用户: Administrator
```

### 2. 备份当前版本
```powershell
cd C:\Users\Administrator\windows-agent
copy main_v3.py main_v3.py.backup
```

### 3. 更新代码
将本地的 `d:\git\hustle2026\windows-agent\main_v3.py` 复制到服务器的 `C:\Users\Administrator\windows-agent\main_v3.py`

可以使用以下方式之一：
- 远程桌面连接，直接复制粘贴
- 使用 WinSCP 或其他 SFTP 工具
- 通过 Git 拉取最新代码

### 4. 重启 Windows Agent 服务
```powershell
# 查看当前服务状态
Get-Process -Name python | Where-Object {$_.CommandLine -like "*main_v3.py*"}

# 停止服务（如果作为服务运行）
Stop-Service -Name "MT5WindowsAgent"

# 或者直接杀死进程
Get-Process -Name python | Where-Object {$_.CommandLine -like "*main_v3.py*"} | Stop-Process -Force

# 启动服务
Start-Service -Name "MT5WindowsAgent"

# 或者手动启动
cd C:\Users\Administrator\windows-agent
python main_v3.py
```

### 5. 验证部署
```bash
# 从本地测试
curl https://admin.hustle2026.xyz/api/v1/mt5-agent/health

# 应该返回
{"status":"ok","agent":"MT5 Windows Agent V3","version":"3.0.0","session":"..."}
```

### 6. 测试 MT5 控制功能
1. 登录管理后台: https://admin.hustle2026.xyz/
2. 进入"用户管理"页面
3. 找到 MT5-01 客户端
4. 点击"重启"按钮
5. 观察 MT5 客户端是否实际重启

### 7. 查看日志
```powershell
# 查看 Windows Agent 日志
cd C:\Users\Administrator\windows-agent
type logs\agent.log | Select-Object -Last 50
```

## 测试要点
- [ ] Windows Agent 服务正常启动
- [ ] 健康检查端点返回正常
- [ ] MT5-01 停止功能正常工作
- [ ] MT5-01 启动功能正常工作
- [ ] MT5-01 重启功能正常工作
- [ ] 日志中显示正确的进程匹配信息

## 回滚方案
如果新版本有问题，可以快速回滚：
```powershell
cd C:\Users\Administrator\windows-agent
copy main_v3.py.backup main_v3.py
Restart-Service -Name "MT5WindowsAgent"
```

## 相关提交
- 提交 9052e5d: 修复：Windows Agent 进程匹配改为仅使用路径
- 提交 56b1343: 添加：MT5进程调试端点
