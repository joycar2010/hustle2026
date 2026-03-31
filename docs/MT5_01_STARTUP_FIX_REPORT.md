# MT5-01 实例启动问题修复报告

## 问题确认

通过 Windows 服务器检查，确认了以下情况：

### 实际进程状态
```
PID: 14152
Name: terminal64.exe
Path: C:\Program Files\MetaTrader 5\terminal64.exe
StartTime: 2026/3/31 13:00:30
```

**结论**：
- ✓ 端口 8001 的 MT5 客户端正在运行（系统服务账户）
- ✗ 端口 8002 的 MT5 客户端**没有运行**（MT5-01 实例）
- ✓ 端口 8002 的桥接服务正在运行
- ✗ 桥接服务错误地报告 `"mt5": true`

## 根本原因

### 1. 桥接服务启动但 MT5 客户端未启动

Windows Agent 的 `start_instance()` 函数只启动了桥接服务（Python uvicorn），但**没有启动 MT5 客户端**。

**代码位置**: `windows-agent/main_v2.py` 第 280-322 行

```python
async def start_instance(port: int):
    # 只启动了桥接服务
    process = start_mt5_bridge(
        mt5_path=config["mt5_path"],
        deploy_path=config["deploy_path"],
        port=port
    )
    # ❌ 没有启动 MT5 客户端
```

### 2. 桥接服务的 MT5 连接检测不准确

桥接服务报告 `"mt5": true`，但实际上 MT5 客户端没有运行。这可能是：
- 桥接服务的健康检查逻辑有问题
- 或者桥接服务缓存了旧的连接状态

## 解决方案

### 方案 1：修改 Windows Agent 启动逻辑（推荐）

在 `start_instance()` 函数中添加 MT5 客户端启动：

```python
async def start_instance(port: int):
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    if is_port_in_use(port):
        return {"message": "Instance is already running", "port": port}

    config = instances[port_str]

    try:
        # 1. 先启动 MT5 客户端
        mt5_path = config["mt5_path"]
        if os.path.exists(mt5_path):
            mt5_process = subprocess.Popen(
                [mt5_path, "/portable"],
                cwd=os.path.dirname(mt5_path),
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # 等待 MT5 启动
            time.sleep(3)

        # 2. 再启动桥接服务
        bridge_process = start_mt5_bridge(
            mt5_path=config["mt5_path"],
            deploy_path=config["deploy_path"],
            port=port
        )

        # 验证服务已启动
        max_retries = 10
        for i in range(max_retries):
            time.sleep(0.5)
            if is_port_in_use(port):
                break

        return {
            "message": "Instance started successfully",
            "port": port,
            "bridge_pid": bridge_process.pid,
            "mt5_pid": mt5_process.pid if 'mt5_process' in locals() else None
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start instance: {str(e)}"
        )
```

### 方案 2：修改桥接服务启动时自动启动 MT5

在桥接服务的启动代码中添加 MT5 自动启动逻辑。

**位置**: `D:\hustle-mt5-cq987\app\main.py` 或 `D:\hustle-mt5-cq987\main.py`

```python
# 在桥接服务启动时
import subprocess
import os

@app.on_event("startup")
async def startup_event():
    """启动时自动启动 MT5 客户端"""
    mt5_path = os.getenv("MT5_PATH")

    if mt5_path and os.path.exists(mt5_path):
        # 检查 MT5 是否已经在运行
        mt5_running = False
        for proc in psutil.process_iter(['name', 'exe']):
            if proc.info['name'] == 'terminal64.exe':
                try:
                    if proc.info['exe'] == mt5_path:
                        mt5_running = True
                        break
                except:
                    pass

        if not mt5_running:
            # 启动 MT5 客户端
            subprocess.Popen(
                [mt5_path, "/portable"],
                cwd=os.path.dirname(mt5_path),
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            logger.info(f"Started MT5 client: {mt5_path}")
```

## 立即修复步骤

### 步骤 1：手动启动 MT5-01 客户端

```powershell
# 在 Windows 服务器上执行
Set-Location "D:\MetaTrader 5-01"
Start-Process -FilePath ".\terminal64.exe" -ArgumentList "/portable" -WindowStyle Hidden
```

或通过 SSH：
```bash
ssh -i /c/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53 \
  "powershell -Command \"Set-Location 'D:\\MetaTrader 5-01'; Start-Process -FilePath '.\\terminal64.exe' -ArgumentList '/portable' -WindowStyle Hidden\""
```

### 步骤 2：验证 MT5 客户端已启动

```bash
ssh -i /c/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53 \
  "powershell -Command \"Get-Process -Name terminal64\""
```

应该看到两个 terminal64.exe 进程。

### 步骤 3：验证桥接服务连接

```bash
curl http://172.31.14.113:8002/health
```

应该返回 `"mt5": true`，且这次是真实的连接状态。

### 步骤 4：部署永久修复

选择方案 1 或方案 2，修改代码并部署到 Windows 服务器。

## 预防措施

### 1. 添加进程检查端点

在 Windows Agent 添加端点来检查实际进程：

```python
@app.get("/system/mt5-processes")
async def get_mt5_processes():
    """获取所有 MT5 进程"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        if proc.info['name'] == 'terminal64.exe':
            processes.append({
                'pid': proc.info['pid'],
                'exe': proc.info['exe'],
                'create_time': proc.create_time()
            })
    return {'count': len(processes), 'processes': processes}
```

### 2. 改进健康检查

桥接服务的健康检查应该真实检测 MT5 连接，而不是返回缓存状态。

### 3. 前端显示改进

在管理界面明确区分：
- 桥接服务状态（端口是否监听）
- MT5 客户端状态（是否真正连接）

## 测试验证

### 完整测试流程

1. 停止实例：`curl -X POST http://172.31.14.113:9000/instances/8002/stop`
2. 验证进程已停止：检查 terminal64.exe 进程
3. 启动实例：`curl -X POST http://172.31.14.113:9000/instances/8002/start`
4. 验证进程已启动：应该看到两个进程
   - 桥接服务（Python）
   - MT5 客户端（terminal64.exe）
5. 验证连接：`curl http://172.31.14.113:8002/health` 应返回 `"mt5": true`
6. 测试 API：调用 MT5 API 确认功能正常

## 相关文件

- `windows-agent/main_v2.py` - Windows Agent（需修改）
- `D:\hustle-mt5-cq987\app\main.py` - 桥接服务（可选修改）
- `D:\MetaTrader 5-01\terminal64.exe` - MT5 客户端
- `D:\MetaTrader 5-01\logs\20260331.log` - MT5 日志

## 修复日期
2026-03-31

## 修复人员
Claude Code (Sonnet 4.6)
