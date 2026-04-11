# MT5 GUI 显示问题 - 根本原因和解决方案

## 问题根本原因

通过分析 `main_v4.py` 和 MT5 Bridge 服务代码，发现了问题的根本原因：

### MT5 启动流程

1. **Windows Agent** 调用 `start_mt5_bridge()` 启动 MT5 Bridge 服务
2. **MT5 Bridge 服务** 在启动时调用 `mt5.initialize(path=MT5_PATH)`
3. **mt5.initialize()** 会自动启动 MT5 客户端（如果尚未运行）
4. **关键问题**：MT5 Bridge 服务在 Session 0 中运行，所以它启动的 MT5 也在 Session 0 中，**无法显示 GUI**

### Session 0 隔离

Windows 有一个安全特性叫 "Session 0 Isolation"：
- **Session 0**：系统服务会话，无法显示 GUI
- **Session 1+**：用户会话（Console 或 RDP），可以显示 GUI

通过 SSH 启动的进程会在 Session 0 中运行，因此：
- Windows Agent → Session 0
- MT5 Bridge 服务 → Session 0
- MT5 客户端 → Session 0（无 GUI）

## 解决方案

### 方案 1：先手动启动 MT5 客户端（推荐）

**原理**：如果 MT5 客户端已经在用户会话中运行，`mt5.initialize()` 会连接到现有实例，而不是启动新实例。

**步骤**：

1. **在 RDP 会话中运行启动脚本**：
   ```powershell
   # 方法 A：双击运行
   C:\MT5Agent\start_mt5_gui.bat

   # 方法 B：PowerShell 运行
   C:\MT5Agent\start_mt5_gui.ps1
   ```

2. **验证 MT5 在用户会话中运行**：
   ```powershell
   Get-Process -Name terminal64 | Select-Object Id, SessionId, MainWindowHandle, Path
   ```

   **预期结果**：
   - `SessionId` = 2（RDP 会话）
   - `MainWindowHandle` > 0（有窗口）

3. **通过管理后台启动 Bridge 服务**：
   - 访问 https://admin.hustle2026.xyz/users
   - 点击 MT5-01 实例的"启动"按钮
   - Bridge 服务会连接到已运行的 MT5 实例

### 方案 2：将 Windows Agent 作为用户进程运行

**原理**：如果 Windows Agent 在用户会话中运行，它启动的所有进程也会在用户会话中。

**步骤**：

1. **停止 Session 0 中的 Windows Agent**：
   ```powershell
   Get-Process python | Where-Object {
       (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*main*.py*"
   } | Stop-Process -Force
   ```

2. **在 RDP 会话中启动 Windows Agent**：
   ```powershell
   cd C:\MT5Agent
   python main.py
   ```

   **重要**：保持 PowerShell 窗口打开！

3. **验证 Windows Agent 在用户会话中**：
   ```powershell
   Get-Process python | Select-Object Id, SessionId
   # SessionId 应该是 2，不是 0
   ```

4. **通过管理后台启动实例**：
   - 现在启动的 MT5 Bridge 和 MT5 客户端都会在用户会话中
   - MT5 窗口会正确显示

### 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| 方案 1：先启动 MT5 | 简单，不需要改变 Windows Agent | 需要手动启动 MT5 | ⭐⭐⭐⭐⭐ |
| 方案 2：用户进程 | 自动化程度高 | Windows Agent 窗口必须保持打开 | ⭐⭐⭐ |

## 详细操作步骤（方案 1 - 推荐）

### 步骤 1：连接到 Windows 服务器

使用 RDP 连接到：
- 地址：`54.249.66.53`
- 用户名：`Administrator`

### 步骤 2：运行 MT5 GUI 启动脚本

在 RDP 会话中，双击运行：
```
C:\MT5Agent\start_mt5_gui.bat
```

或者在 PowerShell 中运行：
```powershell
C:\MT5Agent\start_mt5_gui.ps1
```

脚本会：
1. 检查是否在 RDP 会话中运行
2. 启动 MT5-01 实例（`D:\MetaTrader 5-01\terminal64.exe`）
3. 启动 MT5 系统服务实例（`D:\MetaTrader 5\terminal64.exe`）
4. 验证 MT5 进程状态

### 步骤 3：验证 MT5 窗口

在 RDP 会话中，你应该能看到 MT5 窗口。

在 PowerShell 中验证：
```powershell
Get-Process -Name terminal64 | Select-Object Id, SessionId, MainWindowHandle, Path | Format-Table -AutoSize
```

**预期输出**：
```
Id    SessionId MainWindowHandle Path
--    --------- ---------------- ----
12345 2         123456           D:\MetaTrader 5-01\terminal64.exe
12346 2         123457           D:\MetaTrader 5\terminal64.exe
```

**关键指标**：
- `SessionId` = **2**（与 RDP 会话相同）
- `MainWindowHandle` > **0**（表示有窗口）

### 步骤 4：通过管理后台启动 Bridge 服务

1. 打开浏览器访问：https://admin.hustle2026.xyz/users
2. 找到 **MT5-01 实例**
3. 点击"启动"按钮
4. Bridge 服务会连接到已运行的 MT5 实例

### 步骤 5：验证连接

检查 Bridge 服务状态：
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

## 故障排除

### MT5 窗口仍然不显示

**原因**：MT5 可能是在 Session 0 中启动的。

**解决方法**：
1. 停止所有 MT5 进程：
   ```powershell
   Get-Process -Name terminal64 | Stop-Process -Force
   ```

2. 在 RDP 会话中重新运行启动脚本：
   ```powershell
   C:\MT5Agent\start_mt5_gui.ps1
   ```

### MT5 启动后立即退出

**原因**：可能是配置文件损坏或账号密码错误。

**解决方法**：
1. 查看 MT5 日志：
   ```powershell
   Get-Content "D:\MetaTrader 5-01\Logs\$(Get-Date -Format 'yyyyMMdd').log" -Tail 20
   ```

2. 手动启动 MT5 并检查错误信息：
   ```powershell
   cd "D:\MetaTrader 5-01"
   .\terminal64.exe /portable
   ```

### Bridge 服务无法连接到 MT5

**原因**：MT5 客户端可能未正确初始化。

**解决方法**：
1. 确认 MT5 进程正在运行：
   ```powershell
   Get-Process -Name terminal64
   ```

2. 检查 MT5 是否已登录：
   - 在 RDP 会话中查看 MT5 窗口
   - 确认显示账号信息和余额

3. 重启 Bridge 服务：
   - 在管理后台点击"停止"
   - 等待 2 秒
   - 点击"启动"

## 自动化配置（可选）

如果需要 MT5 在系统启动时自动运行，可以创建启动任务：

### 方法 A：启动文件夹快捷方式

```powershell
# 创建快捷方式到启动文件夹
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\MT5-GUI.lnk")
$Shortcut.TargetPath = "C:\MT5Agent\start_mt5_gui.bat"
$Shortcut.WorkingDirectory = "C:\MT5Agent"
$Shortcut.Save()
```

### 方法 B：任务计划程序

1. 打开"任务计划程序"
2. 创建基本任务
3. 触发器：用户登录时
4. 操作：启动程序
   - 程序：`C:\MT5Agent\start_mt5_gui.bat`
5. 完成

## 测试清单

- [ ] MT5 客户端在 RDP 会话中启动（SessionId = 2）
- [ ] MT5 窗口在 RDP 会话中可见
- [ ] MT5 进程的 MainWindowHandle > 0
- [ ] Bridge 服务成功连接到 MT5
- [ ] 管理后台显示实例状态为"运行中"
- [ ] 可以通过 Bridge API 获取账户信息
- [ ] 停止 Bridge 服务不会关闭 MT5 客户端
- [ ] 重启 Bridge 服务可以重新连接到 MT5

## 相关文件

- `C:\MT5Agent\start_mt5_gui.bat` - 批处理启动脚本
- `C:\MT5Agent\start_mt5_gui.ps1` - PowerShell 启动脚本（推荐）
- `C:\MT5Agent\main.py` - Windows Agent 主程序
- `D:\hustle-mt5-cq987\app\main.py` - MT5 Bridge 服务

## 技术细节

### mt5.initialize() 行为

```python
# MT5 Bridge 服务中的初始化代码
if not mt5.initialize(path=MT5_PATH):
    logger.error(f"mt5.initialize failed: {mt5.last_error()}")
    return False
```

**行为**：
- 如果 MT5 已运行：连接到现有实例
- 如果 MT5 未运行：启动新实例（继承调用进程的会话）

**关键**：新启动的 MT5 会继承调用进程的 Session ID。如果 Bridge 服务在 Session 0，MT5 也会在 Session 0。

### 为什么不能通过 Windows Agent 启动 MT5 GUI

即使 Windows Agent 使用 `PowerShell Start-Process` 启动 MT5，如果 Windows Agent 本身在 Session 0 中运行，启动的 MT5 仍然会在 Session 0 中。

唯一的解决方案是：
1. 在用户会话中预先启动 MT5
2. 或者将 Windows Agent 移到用户会话中运行

## 总结

**推荐方案**：在 RDP 会话中运行 `C:\MT5Agent\start_mt5_gui.ps1`，先启动 MT5 客户端，然后通过管理后台启动 Bridge 服务。

这个方案：
- ✅ 简单可靠
- ✅ MT5 窗口正确显示
- ✅ 不需要修改 Windows Agent
- ✅ 不需要保持额外的窗口打开
- ✅ MT5 和 Bridge 服务解耦，更灵活
