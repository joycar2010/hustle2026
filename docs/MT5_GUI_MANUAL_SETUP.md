# MT5 GUI 手动设置指南

## 问题说明
Windows Agent 通过 SSH 启动时会在 Session 0（系统服务会话）中运行，导致启动的 MT5 进程无法在 RDP 会话中显示 GUI 窗口。

## 解决方案
必须在 RDP 会话中手动启动 Windows Agent，使其运行在用户会话中。

## 操作步骤

### 1. 连接到 Windows 服务器
使用 RDP 连接到服务器：
- 地址：`54.249.66.53`
- 用户名：`Administrator`
- 密码：（使用您的密码）

### 2. 打开 PowerShell（管理员）
在 RDP 会话中：
1. 按 `Win + X`
2. 选择"Windows PowerShell (管理员)"或"终端 (管理员)"

### 3. 停止现有的 Windows Agent
在 PowerShell 中执行：
```powershell
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    if ($wmi.CommandLine -like "*main_v2.py*" -or $wmi.CommandLine -like "*MT5Agent*") {
        Write-Host "Stopping PID: $($_.Id)"
        Stop-Process -Id $_.Id -Force
    }
}
```

### 4. 在用户会话中启动 Windows Agent
执行以下命令：
```powershell
cd C:\MT5Agent
python main_v2.py
```

**重要**：保持这个 PowerShell 窗口打开！关闭窗口会停止 Windows Agent。

### 5. 验证服务状态
打开另一个 PowerShell 窗口，执行：
```powershell
# 检查服务健康状态
Invoke-RestMethod -Uri "http://localhost:9000/" -Method Get

# 检查进程会话 ID
Get-Process python | Where-Object {
    (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*main_v2.py*"
} | Select-Object Id, SessionId

# 查看当前会话
query session
```

**预期结果**：
- Windows Agent 的 SessionId 应该是 2（与 RDP 会话相同）
- 不应该是 0（系统服务会话）

### 6. 测试 MT5 启动
1. 打开浏览器访问：https://admin.hustle2026.xyz/users
2. 找到 MT5-01 实例
3. 点击"启动"按钮
4. MT5 窗口应该会在当前 RDP 会话中显示

### 7. 验证 MT5 窗口
在 PowerShell 中检查：
```powershell
Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Select-Object Id, SessionId, MainWindowHandle
```

**预期结果**：
- `SessionId` 应该是 2（与 RDP 会话相同）
- `MainWindowHandle` 应该大于 0（表示有窗口）

## 故障排除

### MT5 窗口仍然不显示
1. 确认 Windows Agent 在用户会话中运行：
   ```powershell
   Get-Process python | Select-Object Id, SessionId
   ```
   SessionId 应该是 2，不是 0

2. 检查 MT5 进程：
   ```powershell
   Get-Process -Name terminal64 | Select-Object Id, SessionId, MainWindowHandle
   ```

3. 查看 MT5 日志：
   ```powershell
   Get-Content "D:\MetaTrader 5-01\Logs\$(Get-Date -Format 'yyyyMMdd').log" -Tail 20
   ```

### Windows Agent 无法启动
1. 检查 Python 环境：
   ```powershell
   python --version
   cd C:\MT5Agent
   pip list | Select-String "fastapi|uvicorn|psutil"
   ```

2. 检查端口占用：
   ```powershell
   netstat -ano | findstr :9000
   ```

### 需要自动启动
如果需要 Windows Agent 在系统启动时自动运行（在用户会话中），可以：

1. 创建启动快捷方式：
   ```powershell
   $WshShell = New-Object -comObject WScript.Shell
   $Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\MT5Agent.lnk")
   $Shortcut.TargetPath = "powershell.exe"
   $Shortcut.Arguments = "-NoExit -Command `"cd C:\MT5Agent; python main_v2.py`""
   $Shortcut.WorkingDirectory = "C:\MT5Agent"
   $Shortcut.Save()
   ```

2. 或使用任务计划程序：
   - 打开"任务计划程序"
   - 创建基本任务
   - 触发器：用户登录时
   - 操作：启动程序
     - 程序：`powershell.exe`
     - 参数：`-NoExit -Command "cd C:\MT5Agent; python main_v2.py"`

## 长期解决方案

当前方案要求 Windows Agent 在用户会话中运行。更好的长期方案：

1. **使用 Windows 服务 + PsExec**：
   - Windows Agent 作为系统服务运行
   - 使用 PsExec 跨会话启动 MT5
   - 需要解决 MT5 通过 PsExec 启动时的崩溃问题

2. **专用 MT5 管理服务**：
   - 创建独立的用户级服务专门管理 MT5 进程
   - Windows Agent 通过 API 与 MT5 管理服务通信

3. **使用 Task Scheduler**：
   - 配置任务在用户登录时自动启动 Windows Agent
   - 保持用户会话活跃

## 相关文档
- [MT5_SESSION_0_FIX.md](MT5_SESSION_0_FIX.md) - Session 0 隔离问题详细分析
- [MT5_SESSION_0_QUICK_FIX.md](MT5_SESSION_0_QUICK_FIX.md) - 快速修复指南
- [MT5_GUI_MODE_FIX.md](MT5_GUI_MODE_FIX.md) - GUI 模式修复记录
