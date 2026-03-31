# MT5 GUI 显示问题解决方案

## 问题诊断

### 当前状态
- ✓ MT5 进程已启动（PID: 9556）
- ✗ **SessionId = 0**（系统服务会话）
- ✗ **MainWindowHandle = 0**（无窗口句柄）
- ✗ MT5 窗口不显示在 RDP 会话中

### 根本原因
**Session 0 隔离问题**：
- Windows Agent 在 Session 0（系统服务会话）中运行
- 从 Session 0 启动的进程也在 Session 0 中
- Session 0 中的 GUI 应用程序无法显示在用户桌面上
- 用户 RDP 会话在 Session 2 中

## 解决方案

### 方案 1：使用 PsExec 在用户会话中启动（推荐）

#### 步骤 1：下载 PsExec
```powershell
# 在 Windows 服务器上执行
Invoke-WebRequest -Uri "https://download.sysinternals.com/files/PSTools.zip" -OutFile "C:\Temp\PSTools.zip"
Expand-Archive -Path "C:\Temp\PSTools.zip" -DestinationPath "C:\Tools\PSTools"
```

#### 步骤 2：修改 Windows Agent 代码

在 `windows-agent/main_v2.py` 中添加使用 PsExec 的启动函数：

```python
def start_mt5_in_user_session_psexec(mt5_path: str) -> Optional[int]:
    """
    使用 PsExec 在活动用户会话中启动 MT5

    Returns:
        MT5 进程 PID，失败返回 None
    """
    try:
        # 获取活动用户会话 ID
        result = subprocess.run(
            ['query', 'session'],
            capture_output=True,
            text=True
        )

        # 解析活动会话 ID
        active_session = None
        for line in result.stdout.split('\n'):
            if 'Active' in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'Active':
                        active_session = parts[i-2]
                        break
                break

        if not active_session:
            print("No active user session found")
            return None

        # 使用 PsExec 在用户会话中启动 MT5
        psexec_path = r"C:\Tools\PSTools\PsExec.exe"
        cmd = [
            psexec_path,
            '-accepteula',
            '-i', active_session,  # 在指定会话中启动
            '-d',  # 不等待进程结束
            mt5_path,
            '/portable'
        ]

        subprocess.run(cmd, cwd=str(Path(mt5_path).parent))

        # 等待进程启动
        time.sleep(3)

        # 查找启动的 MT5 进程
        for proc in psutil.process_iter(['name', 'exe', 'create_time', 'pid']):
            try:
                if (proc.info['name'] == 'terminal64.exe' and
                    proc.info['exe'] == mt5_path and
                    time.time() - proc.info['create_time'] < 10):
                    return proc.info['pid']
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue

        return None

    except Exception as e:
        print(f"Failed to start MT5 with PsExec: {e}")
        return None
```

#### 步骤 3：修改 start_instance() 函数

```python
if not mt5_already_running:
    # 尝试使用 PsExec 在用户会话中启动
    mt5_pid = start_mt5_in_user_session_psexec(mt5_path)

    if mt5_pid:
        mt5_process = psutil.Process(mt5_pid)
    else:
        # 回退到普通启动
        mt5_process = subprocess.Popen(
            [mt5_path, "/portable"],
            cwd=str(Path(mt5_path).parent)
        )

    time.sleep(3)
```

### 方案 2：将 Windows Agent 作为用户进程运行

#### 步骤 1：停止当前的 Windows Agent
```powershell
Get-Process python | Where-Object {
    (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*MT5Agent*"
} | Stop-Process -Force
```

#### 步骤 2：在 RDP 会话中手动启动 Windows Agent
```powershell
# 在 RDP 会话中执行
cd C:\MT5Agent
python main.py
```

#### 步骤 3：创建启动脚本
创建 `C:\MT5Agent\start_agent.bat`：
```batch
@echo off
cd /d C:\MT5Agent
python main.py
```

#### 步骤 4：添加到启动项
```powershell
# 创建快捷方式到启动文件夹
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\MT5Agent.lnk")
$Shortcut.TargetPath = "C:\MT5Agent\start_agent.bat"
$Shortcut.WorkingDirectory = "C:\MT5Agent"
$Shortcut.Save()
```

### 方案 3：使用 Task Scheduler 在用户登录时启动

#### 创建计划任务
```powershell
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "MT5 Windows Agent" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
```

## 临时解决方案（立即可用）

### 手动启动 MT5 客户端

在 RDP 会话中直接启动 MT5：

```powershell
# MT5-01 实例
cd "D:\MetaTrader 5-01"
Start-Process -FilePath ".\terminal64.exe" -ArgumentList "/portable"

# 系统服务实例
cd "C:\Program Files\MetaTrader 5"
Start-Process -FilePath ".\terminal64.exe" -ArgumentList "/portable"
```

### 创建桌面快捷方式

```powershell
# 为 MT5-01 创建快捷方式
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\MT5-01.lnk")
$Shortcut.TargetPath = "D:\MetaTrader 5-01\terminal64.exe"
$Shortcut.Arguments = "/portable"
$Shortcut.WorkingDirectory = "D:\MetaTrader 5-01"
$Shortcut.Save()
```

## 验证方法

### 检查进程会话
```powershell
Get-Process -Name terminal64 | Select-Object Id, ProcessName, SessionId, MainWindowHandle, MainWindowTitle
```

**期望结果**：
- SessionId = 2（或当前 RDP 会话 ID）
- MainWindowHandle > 0（有窗口句柄）
- MainWindowTitle 显示 MT5 窗口标题

### 检查活动会话
```powershell
query session
```

找到 "Active" 状态的会话 ID。

## 推荐实施步骤

### 立即操作（临时方案）
1. 在 RDP 会话中手动启动 MT5 客户端
2. 创建桌面快捷方式方便后续使用

### 永久修复（推荐方案 1）
1. 下载并安装 PsExec
2. 修改 Windows Agent 代码使用 PsExec
3. 重启 Windows Agent
4. 测试通过管理界面启动 MT5

### 备选方案（方案 2）
1. 停止当前的 Windows Agent
2. 在 RDP 会话中手动启动 Windows Agent
3. 添加到启动项确保重启后自动运行

## 注意事项

### Session 0 隔离
- Windows Vista 及更高版本强制执行 Session 0 隔离
- 系统服务无法直接显示 GUI 到用户桌面
- 必须使用特殊方法（如 PsExec）跨会话启动进程

### RDP 会话要求
- GUI 应用程序需要活动的 RDP 会话
- 断开 RDP 连接后，窗口可能不可见
- 使用 Console Session 可以避免此问题

### 安全考虑
- PsExec 需要管理员权限
- 确保 PsExec 来自官方来源
- 考虑使用 Windows API（CreateProcessAsUser）作为替代

## 相关文档

- [Session 0 Isolation](https://docs.microsoft.com/en-us/windows/win32/services/interactive-services)
- [PsExec Documentation](https://docs.microsoft.com/en-us/sysinternals/downloads/psexec)
- [Task Scheduler](https://docs.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page)

## 修复日期
2026-03-31

## 修复人员
Claude Code (Sonnet 4.6)
