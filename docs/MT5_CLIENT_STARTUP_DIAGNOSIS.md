# MT5 客户端启动问题诊断报告

## 问题描述

用户点击 MT5-01-实例的启动按钮后，期望启动 Windows 服务器上的 MT5 客户端 `D:\MetaTrader 5-01\terminal64.exe`，但 MT5 客户端没有启动。

## 诊断结果

### 1. 实例状态检查

**数据库状态**：
```sql
instance_id: b5a31203-2752-444e-a0d4-71602e0c5115
instance_name: MT5-01-实例
server_ip: 172.31.14.113
service_port: 8002
deploy_path: D:\hustle-mt5-cq987
status: running
is_active: true
```

**Windows Agent 状态**：
```json
{
  "port": 8002,
  "status": "running",
  "mt5_path": "D:\\MetaTrader 5-01\\terminal64.exe",
  "deploy_path": "D:\\hustle-mt5-cq987"
}
```

**桥接服务健康检查**：
```json
{
  "status": "ok",
  "service": "mt5-bridge",
  "instance": "cq987",
  "mt5": true  ← MT5 显示已连接
}
```

### 2. 问题分析

根据诊断结果：
1. ✓ 数据库中实例状态为 "running"
2. ✓ Windows Agent 认为实例正在运行
3. ✓ 桥接服务（端口 8002）正在运行
4. ✓ 桥接服务报告 MT5 已连接 (`"mt5": true`)

**但是**：用户报告 MT5 客户端没有启动。

### 3. 可能的原因

#### 原因 A：MT5 进程在后台运行（最可能）
- 桥接服务以无头模式启动 MT5
- MT5 进程存在但没有 GUI 窗口
- 用户看不到 MT5 界面，认为没有启动

#### 原因 B：健康检查返回错误状态
- 桥接服务的健康检查逻辑有问题
- 返回 `"mt5": true` 但实际上 MT5 未连接
- 需要验证实际的 MT5 进程状态

#### 原因 C：启动逻辑不完整
- Windows Agent 的 `start_instance()` 只启动桥接服务
- 桥接服务没有自动启动 MT5 客户端
- 需要手动启动 MT5 或修改启动逻辑

## 验证步骤

### 步骤 1：检查 Windows 服务器上的实际进程

需要在 Windows 服务器上执行：
```powershell
# 检查 terminal64.exe 进程
Get-Process -Name terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    [PSCustomObject]@{
        PID = $_.Id
        Path = $wmi.ExecutablePath
        CommandLine = $wmi.CommandLine
        StartTime = $_.StartTime
    }
}
```

### 步骤 2：检查桥接服务的 MT5 初始化逻辑

桥接服务应该在启动时初始化 MT5 连接。需要检查：
- `D:\hustle-mt5-cq987\app\main.py` 或 `D:\hustle-mt5-cq987\main.py`
- MT5 初始化代码
- 是否自动启动 MT5 客户端

### 步骤 3：测试 MT5 API

如果 MT5 真的在运行，应该能调用 MT5 API：
```bash
curl -H "X-API-Key: <api-key>" http://172.31.14.113:8002/mt5/account/info
```

如果返回账户信息，说明 MT5 确实在运行。

## 解决方案

### 方案 1：如果 MT5 进程确实在运行（原因 A）

**问题**：MT5 以无头模式运行，用户看不到界面。

**解决**：
1. 这是正常的服务器部署方式
2. MT5 不需要 GUI 就能工作
3. 通过 API 和健康检查确认 MT5 状态即可

**前端改进**：
- 在界面上明确显示 "MT5 客户端状态：已连接"
- 添加 MT5 连接状态指示器
- 区分"桥接服务状态"和"MT5 客户端状态"

### 方案 2：如果 MT5 进程未运行（原因 B/C）

**问题**：桥接服务启动了，但 MT5 客户端没有启动。

**解决步骤**：

#### 2.1 修改桥接服务启动逻辑

在桥接服务的启动代码中添加 MT5 自动启动：

```python
# 在桥接服务启动时
import subprocess
import os

MT5_PATH = os.getenv("MT5_PATH")
if MT5_PATH and os.path.exists(MT5_PATH):
    # 启动 MT5 客户端
    subprocess.Popen(
        [MT5_PATH, "/portable"],
        cwd=os.path.dirname(MT5_PATH),
        creationflags=subprocess.CREATE_NO_WINDOW
    )
```

#### 2.2 修改 Windows Agent 的 start_instance()

在 `start_mt5_bridge()` 之后添加 MT5 启动：

```python
def start_instance(port: int):
    # 1. 启动桥接服务
    process = start_mt5_bridge(...)

    # 2. 启动 MT5 客户端
    config = instances[str(port)]
    mt5_path = config["mt5_path"]

    if os.path.exists(mt5_path):
        subprocess.Popen(
            [mt5_path, "/portable"],
            cwd=os.path.dirname(mt5_path),
            creationflags=subprocess.CREATE_NO_WINDOW
        )
```

#### 2.3 添加进程检查端点

在 Windows Agent 添加端点来检查实际进程：

```python
@app.get("/instances/{port}/processes")
async def get_instance_processes(port: int):
    """获取实例相关的进程信息"""
    config = instances[str(port)]
    deploy_path = config["deploy_path"]

    # 检查桥接服务进程
    bridge_proc = get_process_by_port(port)

    # 检查 MT5 进程
    mt5_procs = []
    for proc in psutil.process_iter(['name', 'pid', 'exe']):
        if proc.info['name'] == 'terminal64.exe':
            # 检查是否属于这个实例
            try:
                cwd = proc.cwd()
                if deploy_path in cwd:
                    mt5_procs.append({
                        'pid': proc.info['pid'],
                        'exe': proc.info['exe']
                    })
            except:
                pass

    return {
        "bridge_service": {
            "running": bridge_proc is not None,
            "pid": bridge_proc.pid if bridge_proc else None
        },
        "mt5_client": {
            "running": len(mt5_procs) > 0,
            "processes": mt5_procs
        }
    }
```

## 立即行动

### 优先级 1：验证 MT5 是否真的在运行

执行 PowerShell 脚本 `scripts/check_mt5_processes.ps1` 来检查实际进程状态。

### 优先级 2：如果 MT5 未运行，修复启动逻辑

根据验证结果，选择方案 2 的修复步骤。

### 优先级 3：改进前端显示

无论 MT5 是否在运行，都应该在前端明确显示：
- 桥接服务状态
- MT5 客户端连接状态
- 区分两者，避免混淆

## 相关文件

- `windows-agent/main_v2.py` - Windows Agent 主程序
- `D:\hustle-mt5-cq987\app\main.py` - 桥接服务代码（Windows 服务器）
- `frontend/src-admin/views/UserManagement.vue` - 前端管理界面
- `backend/app/api/v1/mt5_instances.py` - 后端实例控制 API

## 修复日期
2026-03-31

## 修复人员
Claude Code (Sonnet 4.6)
