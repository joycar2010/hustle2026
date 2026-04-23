# MT5 实例启动/停止问题 - 完整解决方案

## 问题分析

### 现象
1. 点击"启动"按钮 → 无法启动 MT5 GUI
2. 点击"停止"按钮 → 无法停止 MT5 客户端
3. 点击"重启"按钮 → 可以关闭 MT5，但无法重新启动

### 根本原因

**Windows Session 0 隔离问题**：

```
Windows Agent (Session 0)
    ↓ 启动
MT5 客户端 (Session 2，但无法创建 GUI 窗口)
    ↓ 错误日志
MDI create failed
create frame from resource 131 failed
```

即使 MT5 进程在 Session 2 中运行，但由于是从 Session 0 的进程启动的，它无法正确创建 GUI 窗口框架。

### MT5 日志错误
```
HN	2	15:40:35.563	Window	MDI unhook failed
DS	2	15:40:35.563	Window	MDI create failed
FD	2	15:40:35.563	Document	create frame from resource 131 failed
HL	2	15:40:35.563	Document	load frame from 131 resource failed
LF	2	15:40:35.563	Document	create new frame failed
```

这些错误表明 MT5 无法创建窗口，因为它缺少必要的桌面环境上下文。

## 解决方案

### 新的工作流程

**两步启动流程**：

1. **第一步：在 RDP 会话中手动启动 MT5 客户端**
   - 双击桌面快捷方式 "2325036-8002"
   - 或运行 `C:\MT5Agent\start_mt5_gui.ps1`
   - MT5 窗口会正常显示

2. **第二步：通过管理后台启动 Bridge 服务**
   - 访问 https://admin.hustle2026.xyz/users
   - 点击 MT5-01 实例的"启动"按钮
   - Bridge 服务会连接到已运行的 MT5 实例

### 代码改进

已更新 `C:\MT5Agent\main.py` 的 `start_instance()` 函数：

```python
@app.post("/instances/{port}/start")
async def start_instance(port: int):
    """启动实例（只启动 Bridge 服务，MT5 客户端需要预先在 RDP 会话中启动）"""

    # 1. 检查 MT5 客户端是否已在运行
    if is_mt5_running_by_path(mt5_path):
        print(f"MT5 already running: {mt5_path}")
        # 找到已运行的 MT5 进程
    else:
        # MT5 未运行，返回错误提示
        raise HTTPException(
            status_code=400,
            detail=f"MT5 client is not running. Please start MT5 manually in RDP session first."
        )

    # 2. 启动 MT5 桥接服务
    bridge_process = start_mt5_bridge(...)

    return {
        "message": "Instance started successfully",
        "bridge_pid": bridge_process.pid,
        "mt5_pid": mt5_process.pid,
        "note": "MT5 client was already running"
    }
```

**关键变化**：
- ✅ 不再尝试自动启动 MT5 客户端
- ✅ 检查 MT5 是否已在运行
- ✅ 如果 MT5 未运行，返回明确的错误提示
- ✅ 只启动 Bridge 服务，连接到已运行的 MT5

## 完整操作步骤

### 步骤 1：在 RDP 会话中启动 MT5 客户端

**方法 A：使用桌面快捷方式**
1. 连接到 Windows 服务器（RDP 到 54.249.66.53）
2. 双击桌面快捷方式 **"2325036-8002"**
3. 等待 MT5 窗口出现并登录

**方法 B：使用启动脚本**
1. 在 RDP 会话中打开 PowerShell
2. 运行：
   ```powershell
   C:\MT5Agent\start_mt5_01_instance.ps1
   ```
3. 或双击运行：`C:\MT5Agent\start_mt5_01_instance.bat`

**方法 C：手动启动**
1. 打开文件资源管理器
2. 导航到：`D:\MetaTrader 5-01`
3. 双击 `terminal64.exe`

### 步骤 2：验证 MT5 已正确启动

在 PowerShell 中运行：
```powershell
Get-Process -Name terminal64 | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize
```

**预期结果**：
```
Id    SessionId MainWindowHandle Path
--    --------- ---------------- ----
12345 2         123456           D:\MetaTrader 5-01\terminal64.exe
```

**关键指标**：
- `SessionId` = **2**（RDP 会话）
- `MainWindowHandle` > **0**（有窗口）
- MT5 窗口在 RDP 会话中可见

### 步骤 3：通过管理后台启动 Bridge 服务

1. 打开浏览器访问：https://admin.hustle2026.xyz/users
2. 找到 **MT5-01 实例**（端口 8002）
3. 点击"启动"按钮
4. 应该看到成功消息

**如果 MT5 未运行**，会看到错误提示：
```
MT5 client is not running. Please start MT5 manually in RDP session first.
Path: D:\MetaTrader 5-01\terminal64.exe
```

### 步骤 4：验证 Bridge 服务连接成功

在 PowerShell 中运行：
```powershell
Invoke-RestMethod -Uri "http://localhost:8002/health"
```

**预期输出**：
```json
{
  "status": "healthy",
  "mt5": true,
  "account": 2325036,
  "server": "Bybit-Live-2"
}
```

## 停止实例

### 通过管理后台停止

1. 访问 https://admin.hustle2026.xyz/users
2. 点击 MT5-01 实例的"停止"按钮
3. 这会停止 Bridge 服务和 MT5 客户端

### 手动停止 MT5 客户端

如果需要单独停止 MT5 客户端：
```powershell
Get-Process -Name terminal64 | Where-Object { $_.Path -like "*MetaTrader 5-01*" } | Stop-Process -Force
```

## 重启实例

### 通过管理后台重启

1. 确保 MT5 客户端已在 RDP 会话中运行
2. 访问 https://admin.hustle2026.xyz/users
3. 点击 MT5-01 实例的"重启"按钮
4. 这会：
   - 停止 Bridge 服务
   - 停止 MT5 客户端
   - **但不会重新启动 MT5 客户端**（需要手动启动）

### 完整重启流程

1. **停止实例**（通过管理后台）
2. **在 RDP 会话中重新启动 MT5 客户端**
   ```powershell
   C:\MT5Agent\start_mt5_01_instance.ps1
   ```
3. **启动实例**（通过管理后台）

## 故障排除

### 问题 1：点击"启动"按钮后提示 MT5 未运行

**原因**：MT5 客户端未在 RDP 会话中启动

**解决方法**：
1. 连接到 Windows 服务器（RDP）
2. 双击桌面快捷方式 "2325036-8002"
3. 等待 MT5 窗口出现
4. 再次点击管理后台的"启动"按钮

### 问题 2：MT5 窗口不可见

**原因**：MT5 在 Session 0 中运行

**解决方法**：
1. 停止所有 MT5 进程：
   ```powershell
   Get-Process -Name terminal64 | Stop-Process -Force
   ```
2. 在 RDP 会话中重新启动 MT5

### 问题 3：Bridge 服务无法连接到 MT5

**原因**：MT5 未正确初始化或未登录

**解决方法**：
1. 在 RDP 会话中查看 MT5 窗口
2. 确认显示账号信息：2325036@Bybit-Live-2
3. 如果未登录，手动输入账号密码
4. 重启 Bridge 服务

### 问题 4：停止按钮无法停止 MT5

**原因**：可能有多个 MT5 实例在运行

**解决方法**：
1. 检查所有 MT5 进程：
   ```powershell
   Get-Process -Name terminal64 | Select-Object Id, Path
   ```
2. 手动停止特定实例：
   ```powershell
   Get-Process -Name terminal64 | Where-Object { $_.Path -like "*MetaTrader 5-01*" } | Stop-Process -Force
   ```

## 自动化建议

### 创建桌面快捷方式

已创建以下快捷方式：
- `Start MT5 GUI.lnk` - 启动所有 MT5 实例
- `2325036-8002` - 启动 MT5-01 实例（如果存在）

### 开机自动启动（可选）

如果需要 MT5 在系统启动时自动运行：

```powershell
# 创建启动任务
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\MT5-01.lnk")
$Shortcut.TargetPath = "D:\MetaTrader 5-01\terminal64.exe"
$Shortcut.Arguments = "/portable"
$Shortcut.WorkingDirectory = "D:\MetaTrader 5-01"
$Shortcut.Save()
```

## 架构说明

### 当前架构

```
RDP 会话 (Session 2)
    ↓ 手动启动
MT5 客户端 (Session 2, 有 GUI)
    ↑ 连接
MT5 Bridge 服务 (Session 0)
    ↑ 控制
Windows Agent (Session 0)
    ↑ HTTP API
管理后台
```

### 为什么需要两步启动

1. **MT5 客户端必须在用户会话中启动**才能显示 GUI
2. **Windows Agent 在 Session 0 中运行**，无法在用户会话中创建 GUI
3. **Bridge 服务可以连接到已运行的 MT5**，无论 MT5 在哪个会话中

### 未来改进方向

1. **前端提示**：在管理后台添加提示，告知用户需要先启动 MT5 客户端
2. **状态检测**：显示 MT5 客户端是否已运行
3. **一键启动脚本**：提供下载链接，用户可以在 RDP 会话中运行
4. **远程桌面集成**：通过 RDP API 在用户会话中启动 MT5（需要额外开发）

## 总结

**关键要点**：
1. ✅ MT5 客户端必须在 RDP 会话中手动启动
2. ✅ 管理后台只控制 Bridge 服务
3. ✅ Bridge 服务会自动连接到已运行的 MT5
4. ✅ 停止功能会同时停止 Bridge 和 MT5
5. ✅ 重启功能需要手动重新启动 MT5 客户端

**操作流程**：
1. RDP 连接到服务器
2. 双击桌面快捷方式启动 MT5
3. 在管理后台点击"启动"按钮
4. 完成！

## 相关文件

- `C:\MT5Agent\main.py` - Windows Agent 主程序（已更新）
- `C:\MT5Agent\start_mt5_01_instance.ps1` - MT5-01 启动脚本
- `C:\MT5Agent\start_mt5_gui.ps1` - 启动所有 MT5 实例
- 桌面快捷方式：`Start MT5 GUI.lnk`
- 桌面快捷方式：`2325036-8002`（如果存在）
