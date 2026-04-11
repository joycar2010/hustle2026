# MT5 GUI 显示 - 最终解决方案

## 问题根源
Windows Agent 必须在**用户 RDP 会话**中运行，才能启动带 GUI 的 MT5 窗口。通过 SSH 启动的进程会在 Session 0（系统服务会话）中运行，无法显示 GUI。

## 解决方案：在 RDP 会话中手动启动 Windows Agent

### 步骤 1：连接到 Windows 服务器
使用 RDP 连接到：
- 地址：`54.249.66.53`
- 用户名：`Administrator`

### 步骤 2：打开 PowerShell（管理员）
在 RDP 会话中：
1. 按 `Win + X`
2. 选择"Windows PowerShell (管理员)"

### 步骤 3：停止所有现有的 Windows Agent
```powershell
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    if ($wmi.CommandLine -like "*main_v2.py*" -or $wmi.CommandLine -like "*MT5Agent*") {
        Write-Host "Stopping PID: $($_.Id)"
        Stop-Process -Id $_.Id -Force
    }
}
```

### 步骤 4：在用户会话中启动 Windows Agent
```powershell
cd C:\MT5Agent
python main_v2.py
```

**重要**：保持这个 PowerShell 窗口打开！关闭窗口会停止 Windows Agent。

### 步骤 5：验证 Windows Agent 在用户会话中运行
打开另一个 PowerShell 窗口：
```powershell
# 检查 Python 进程的会话 ID
Get-Process python | Where-Object {
    (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*main_v2.py*"
} | Select-Object Id, SessionId

# 查看当前会话
query session
```

**预期结果**：
- Python 进程的 SessionId 应该是 **2**（与 RDP 会话相同）
- 不应该是 0（系统服务会话）

### 步骤 6：测试 MT5 启动
1. 打开浏览器访问：https://admin.hustle2026.xyz/users
2. 找到 **MT5-01 实例**
3. 点击"启动"按钮
4. **MT5 窗口应该会在当前 RDP 会话中显示**

### 步骤 7：验证 MT5 窗口
在 PowerShell 中检查：
```powershell
Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Select-Object Id, SessionId, MainWindowHandle, Path
```

**预期结果**：
- `SessionId` = **2**（与 RDP 会话相同）
- `MainWindowHandle` > **0**（表示有窗口）
- `Path` 应该是正确的 MT5 路径（如 `D:\MetaTrader 5-01\terminal64.exe`）

## 代码改进说明

已对 `windows-agent/main_v2.py` 进行以下改进：

### 1. 精准的进程识别
```python
def is_mt5_running_by_path(mt5_path: str) -> bool:
    """通过绝对路径精准判断 MT5 是否运行，避免误判"""
    target_path = os.path.normpath(mt5_path).lower()
    for proc in psutil.process_iter(['name', 'exe']):
        if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
            proc_path = os.path.normpath(proc.info['exe']).lower()
            if proc_path == target_path:
                return True
    return False
```

### 2. 改进的启动方法
```python
def start_mt5_in_user_session(mt5_path: str) -> Optional[psutil.Process]:
    """使用 PowerShell Start-Process 在用户会话中启动 MT5"""
    ps_cmd = f'Start-Process -FilePath "{mt5_path}" -ArgumentList "/portable" -WorkingDirectory "{mt5_dir}"'
    subprocess.Popen(["powershell", "-Command", ps_cmd], ...)
```

### 3. 精准的停止方法
```python
def stop_mt5_client_by_path(mt5_path: str) -> bool:
    """通过绝对路径精准停止 MT5，避免误杀其他实例"""
    target_path = os.path.normpath(mt5_path).lower()
    for proc in psutil.process_iter(['name', 'exe', 'pid']):
        if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
            proc_path = os.path.normpath(proc.info['exe']).lower()
            if proc_path == target_path:
                proc.terminate()
                ...
```

## 自动启动配置（可选）

如果需要 Windows Agent 在系统启动时自动运行（在用户会话中），可以创建启动快捷方式：

```powershell
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\MT5Agent.lnk")
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-NoExit -Command `"cd C:\MT5Agent; python main_v2.py`""
$Shortcut.WorkingDirectory = "C:\MT5Agent"
$Shortcut.WindowStyle = 7  # 最小化窗口
$Shortcut.Save()
```

这样，每次 Administrator 用户登录时，Windows Agent 会自动在用户会话中启动。

## 故障排除

### MT5 窗口仍然不显示

1. **确认 Windows Agent 在用户会话中运行**：
   ```powershell
   Get-Process python | Select-Object Id, SessionId
   # SessionId 应该是 2，不是 0
   ```

2. **检查 MT5 进程**：
   ```powershell
   Get-Process -Name terminal64 | Select-Object Id, SessionId, MainWindowHandle, Path
   ```

3. **查看 MT5 日志**：
   ```powershell
   Get-Content "D:\MetaTrader 5-01\Logs\$(Get-Date -Format 'yyyyMMdd').log" -Tail 20
   ```

### Windows Agent 无法启动

1. **检查 Python 环境**：
   ```powershell
   python --version
   cd C:\MT5Agent
   pip list | Select-String "fastapi|uvicorn|psutil"
   ```

2. **检查端口占用**：
   ```powershell
   netstat -ano | findstr :9000
   ```

### MT5 启动后立即退出

可能原因：
- MT5 配置文件损坏
- 账号/密码错误
- 服务器连接失败

查看 MT5 日志文件确认具体原因。

## 测试清单

- [ ] Windows Agent 在 RDP 会话中运行（SessionId = 2）
- [ ] 点击"启动"按钮后 MT5 窗口出现在 RDP 会话中
- [ ] MT5 进程的 SessionId = 2
- [ ] MT5 进程的 MainWindowHandle > 0
- [ ] 点击"停止"按钮后 MT5 窗口关闭
- [ ] 只停止指定实例，不影响其他 MT5 实例
- [ ] 点击"重启"按钮后 MT5 窗口重新出现

## 相关文档
- [MT5_SESSION_0_FIX.md](MT5_SESSION_0_FIX.md) - Session 0 隔离问题详细分析
- [MT5_GUI_MODE_FIX.md](MT5_GUI_MODE_FIX.md) - GUI 模式修复记录
- [MT5_STARTUP_FIX_VERIFICATION.md](MT5_STARTUP_FIX_VERIFICATION.md) - 启动功能修复验证
