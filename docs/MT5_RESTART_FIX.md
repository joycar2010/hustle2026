# MT5 实例重启失败问题 - 解决方案

## 问题描述

在管理后台点击"重启"按钮时，出现 500 错误：
```
AxiosError: Request failed with status code 500
error while attempting to bind on address ('0.0.0.0', 8002): only one usage of each socket address (protocol/network address/port) is normally permitted
```

## 根本原因

系统中存在**两种方式**来管理 MT5 Bridge 服务：

### 方式 1：Windows Agent API（端口 9000）
- 通过管理后台的"启动/停止/重启"按钮控制
- 使用 `http://172.31.14.113:9000/instances/{port}/start|stop|restart`

### 方式 2：Windows 系统服务
- 服务名称：`hustle-mt5-cq987`（8002 端口）
- 服务名称：`hustle-mt5-system`（8001 端口）
- 这些服务会自动重启 Bridge 进程

**冲突**：当 Windows 服务正在运行时，通过 Windows Agent API 停止实例后，Windows 服务会立即重新启动进程，导致端口仍然被占用，重启失败。

## 解决方案

### 临时解决方案（已实施）

停止 Windows 系统服务：
```powershell
Stop-Service -Name "hustle-mt5-cq987" -Force
Stop-Service -Name "hustle-mt5-system" -Force
```

现在可以通过管理后台正常控制实例的启动/停止/重启。

### 长期解决方案

选择一种管理方式：

#### 选项 A：只使用 Windows Agent API（推荐）

**优点**：
- 统一管理界面
- 更灵活的控制
- 支持 MT5 GUI 显示

**步骤**：
1. 禁用 Windows 系统服务：
   ```powershell
   Set-Service -Name "hustle-mt5-cq987" -StartupType Disabled
   Set-Service -Name "hustle-mt5-system" -StartupType Disabled
   Stop-Service -Name "hustle-mt5-cq987" -Force
   Stop-Service -Name "hustle-mt5-system" -Force
   ```

2. 通过管理后台控制实例

#### 选项 B：只使用 Windows 系统服务

**优点**：
- 系统启动时自动运行
- 更稳定（系统级管理）

**缺点**：
- MT5 GUI 无法显示（在 Session 0 中运行）
- 管理后台的控制按钮会失效

**步骤**：
1. 启用并启动 Windows 系统服务：
   ```powershell
   Set-Service -Name "hustle-mt5-cq987" -StartupType Automatic
   Set-Service -Name "hustle-mt5-system" -StartupType Automatic
   Start-Service -Name "hustle-mt5-cq987"
   Start-Service -Name "hustle-mt5-system"
   ```

2. 在管理后台隐藏或禁用控制按钮

## 代码改进

已对 `windows-agent/main.py` 进行以下改进：

### 1. 改进的 `stop_instance()` 函数

```python
# 添加了更强的进程终止逻辑
proc.terminate()
try:
    proc.wait(timeout=5)
except psutil.TimeoutExpired:
    proc.kill()
    proc.wait(timeout=3)

# 额外检查端口是否已释放
time.sleep(1)
if is_port_in_use(port):
    # 强制终止残留进程
    proc = get_process_by_port(port)
    if proc:
        proc.kill()
```

### 2. 改进的 `restart_instance()` 函数

```python
# 增加等待时间
max_wait = 20  # 10 秒

# 添加详细的日志输出
print(f"Restarting instance on port {port}: Step 1 - Stopping...")
print(f"Restarting instance on port {port}: Step 2 - Waiting for port release...")
print(f"Restarting instance on port {port}: Step 3 - Starting...")

# 添加错误处理
try:
    # ... 重启逻辑 ...
except HTTPException:
    raise
except Exception as e:
    error_msg = f"Failed to restart instance on port {port}: {str(e)}"
    raise HTTPException(status_code=500, detail=error_msg)
```

## 验证步骤

1. **检查 Windows 服务状态**：
   ```powershell
   Get-Service | Where-Object { $_.DisplayName -like "*hustle*" } | Select-Object Name,DisplayName,Status
   ```

2. **检查端口占用**：
   ```powershell
   netstat -ano | findstr ":8001 :8002"
   ```

3. **测试重启功能**：
   - 访问 https://admin.hustle2026.xyz/users
   - 点击 MT5-01 实例的"重启"按钮
   - 应该成功重启，不再出现 500 错误

4. **检查实例状态**：
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:9000/instances/8002/status"
   ```

## 当前状态

- ✅ Windows 服务 `hustle-mt5-cq987` 已停止
- ✅ Windows 服务 `hustle-mt5-system` 已停止
- ✅ Windows Agent API 可以正常控制实例
- ✅ 重启功能已修复并测试通过
- ✅ 8002 实例正在运行

## 建议

**推荐使用选项 A（只使用 Windows Agent API）**，原因：

1. 与管理后台集成更好
2. 支持 MT5 GUI 显示（需要先在 RDP 会话中启动 MT5 客户端）
3. 更灵活的控制和调试
4. 避免两种管理方式的冲突

如果需要系统启动时自动运行，可以：
- 将 Windows Agent 配置为 Windows 服务（已有 `MT5WindowsAgent` 服务）
- 或者使用任务计划程序在用户登录时启动

## 相关文件

- `C:\MT5Agent\main.py` - Windows Agent 主程序（已更新）
- Windows 服务：
  - `hustle-mt5-cq987` - 8002 端口 Bridge 服务
  - `hustle-mt5-system` - 8001 端口 Bridge 服务
  - `MT5WindowsAgent` - Windows Agent 服务
