# Windows Agent V2 部署指南

## 更新内容

### 新功能
1. **真正的启动/停止/重启功能** - 不再是空实现
2. **MT5 Portable 模式支持** - 自动设置环境变量 `MT5_PORTABLE=1`
3. **进程管理** - 正确启动和停止 MT5 桥接服务进程
4. **错误处理** - 完善的异常处理和状态检查

### 关键改进
- 启动时自动使用部署目录下的 venv Python 环境
- 支持优雅停止（terminate）和强制停止（kill）
- 重启时等待端口完全释放
- 启动后验证服务是否正常监听端口

## 部署步骤

### 1. 备份当前 Agent

在 Windows MT5 服务器上：

```powershell
cd C:\MT5Agent
copy main.py main.py.backup
```

### 2. 停止当前 Agent

```powershell
# 停止所有 Agent 进程
Get-Process -Name python | Where-Object {$_.Path -like "*MT5Agent*"} | Stop-Process -Force
```

### 3. 上传新版本

将 `main_v2.py` 上传到 Windows 服务器的 `C:\MT5Agent\` 目录，并重命名为 `main.py`：

```powershell
# 假设新文件已上传为 main_v2.py
cd C:\MT5Agent
move main.py main.py.old
move main_v2.py main.py
```

### 4. 启动新 Agent

```powershell
cd C:\MT5Agent
Start-Process python -ArgumentList "main.py" -WindowStyle Hidden
```

### 5. 验证

```powershell
# 测试健康检查
Invoke-WebRequest -Uri "http://localhost:9000/" -UseBasicParsing

# 应该返回：
# {"status":"healthy","service":"MT5 Windows Agent","version":"2.0.0"}
```

## MT5 桥接服务部署目录结构

每个 MT5 实例的部署目录应该包含：

```
D:\hustle-mt5-cq987\
├── main.py              # MT5 桥接服务主程序
├── venv\                # Python 虚拟环境
│   └── Scripts\
│       └── python.exe
├── requirements.txt
└── ... (其他文件)
```

## 环境变量

Agent 启动 MT5 桥接服务时会自动设置：

- `MT5_PATH` - MT5 可执行文件路径
- `MT5_PORTABLE` - 设置为 `1`，表示使用 portable 模式

MT5 桥接服务的 `main.py` 应该读取这些环境变量：

```python
import os

MT5_PATH = os.getenv('MT5_PATH')
MT5_PORTABLE = os.getenv('MT5_PORTABLE') == '1'

# 启动 MT5 时使用
if MT5_PORTABLE:
    cmd = [MT5_PATH, '/portable']
else:
    cmd = [MT5_PATH]
```

## 测试

### 1. 部署实例

```powershell
$body = @{
    port = 8004
    mt5_path = "D:\MetaTrader 5-01\terminal64.exe"
    deploy_path = "D:\hustle-mt5-cq987"
    auto_start = $true
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:9000/instances/deploy" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body `
    -UseBasicParsing
```

### 2. 启动实例

```powershell
Invoke-WebRequest -Uri "http://localhost:9000/instances/8004/start" `
    -Method Post `
    -UseBasicParsing
```

### 3. 检查状态

```powershell
# 检查端口
netstat -ano | findstr :8004

# 检查实例状态
Invoke-WebRequest -Uri "http://localhost:9000/instances/8004/status" `
    -UseBasicParsing
```

### 4. 停止实例

```powershell
Invoke-WebRequest -Uri "http://localhost:9000/instances/8004/stop" `
    -Method Post `
    -UseBasicParsing
```

### 5. 重启实例

```powershell
Invoke-WebRequest -Uri "http://localhost:9000/instances/8004/restart" `
    -Method Post `
    -UseBasicParsing
```

## 故障排查

### 启动失败

1. 检查部署目录是否存在 `main.py`
2. 检查 venv 是否正确安装
3. 检查 MT5 路径是否正确
4. 查看 Agent 日志

### 端口冲突

```powershell
# 查看端口占用
netstat -ano | findstr :<端口>

# 停止占用进程
Stop-Process -Id <PID> -Force
```

### 进程无法停止

Agent 会先尝试优雅停止（10秒超时），如果失败会强制 kill。

## 注意事项

1. **MT5 桥接服务的 main.py 必须支持环境变量** - 需要读取 `MT5_PATH` 和 `MT5_PORTABLE`
2. **部署目录必须包含完整的服务代码** - 包括 venv 和所有依赖
3. **端口必须唯一** - 每个实例使用不同的端口
4. **防火墙规则** - 确保内网可以访问实例端口
