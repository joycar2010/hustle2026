# MT5 Session 0 快速修复指南

## 问题描述
点击 MT5 实例启动按钮后，MT5 进程启动了但窗口不在 RDP 会话中显示。

**原因**: Windows Agent 作为系统服务运行在 Session 0，启动的 MT5 进程也在 Session 0，无法在用户 RDP 会话（Session 2）中显示窗口。

## 快速修复步骤

### 1. 连接到 Windows 服务器
使用 RDP 连接到 `54.249.66.53`（Administrator 账户）

### 2. 下载并安装 PsExec
在 PowerShell 中执行：
```powershell
# 创建目录
New-Item -ItemType Directory -Force -Path "C:\Tools\PSTools"

# 下载 PSTools
Invoke-WebRequest -Uri "https://download.sysinternals.com/files/PSTools.zip" `
    -OutFile "C:\Tools\PSTools.zip" -UseBasicParsing

# 解压
Expand-Archive -Path "C:\Tools\PSTools.zip" -DestinationPath "C:\Tools\PSTools" -Force

# 删除压缩包
Remove-Item "C:\Tools\PSTools.zip"

# 验证安装
Test-Path "C:\Tools\PSTools\PsExec.exe"  # 应该返回 True
```

### 3. 上传更新后的代码
将本地的 `windows-agent/main_v2.py` 上传到服务器的 `C:\Temp\main_v2.py`

可以使用 SCP：
```bash
scp -i /c/Users/HUAWEI/.ssh/id_ed25519 \
    d:/git/hustle2026/windows-agent/main_v2.py \
    Administrator@54.249.66.53:C:/Temp/main_v2.py
```

或者在 RDP 会话中直接复制粘贴文件内容。

### 4. 运行修复脚本
在 Windows 服务器的 PowerShell（管理员）中执行：
```powershell
# 如果已经上传了修复脚本
C:\Temp\fix_mt5_session0.ps1

# 或者手动执行以下步骤：

# 停止现有的 Windows Agent
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    if ($wmi.CommandLine -like "*main_v2.py*") {
        Stop-Process -Id $_.Id -Force
    }
}

# 备份旧文件
Copy-Item C:\MT5Agent\main_v2.py C:\MT5Agent\main_v2.py.backup

# 复制新文件
Copy-Item C:\Temp\main_v2.py C:\MT5Agent\main_v2.py -Force

# 在当前用户会话中启动 Windows Agent
cd C:\MT5Agent
python main_v2.py
```

### 5. 验证修复
1. 保持 PowerShell 窗口打开（Windows Agent 在其中运行）
2. 打开浏览器访问 https://admin.hustle2026.xyz/users
3. 找到 MT5-01 实例，点击"启动"按钮
4. MT5 窗口应该会在当前 RDP 会话中显示

### 6. 验证进程会话
在 PowerShell 中检查：
```powershell
# 查看 MT5 进程的会话 ID 和窗口句柄
Get-Process -Name terminal64 | Select-Object Id, SessionId, MainWindowHandle

# 应该看到：
# - SessionId 与当前 RDP 会话相同（通常是 2）
# - MainWindowHandle 大于 0（表示有窗口）
```

## 工作原理

更新后的 `start_mt5_in_user_session()` 函数：

1. **优先使用 PsExec**: 检测活动 RDP 会话 ID，使用 PsExec 在该会话中启动 MT5
2. **回退机制**: 如果 PsExec 不可用，使用 `cmd /c start` 作为备选方案
3. **进程验证**: 启动后查找并返回 MT5 进程对象

关键代码：
```python
# 使用 PsExec 在指定会话中启动
cmd = [
    "C:\\Tools\\PSTools\\PsExec.exe",
    "-accepteula",
    "-i", session_id,  # 在用户会话中运行
    "-d",  # 不等待进程结束
    mt5_path,
    "/portable"
]
```

## 故障排除

### MT5 窗口仍然不显示
1. 检查 PsExec 是否正确安装：
   ```powershell
   Test-Path "C:\Tools\PSTools\PsExec.exe"
   ```

2. 检查 Windows Agent 是否在用户会话中运行：
   ```powershell
   Get-Process python | Select-Object Id, SessionId
   # SessionId 应该与当前 RDP 会话相同
   ```

3. 手动测试 PsExec：
   ```powershell
   $sessionId = (query session | Select-String "Active" | Select-Object -First 1) -replace '.*rdp-tcp#(\d+).*', '$1'
   C:\Tools\PSTools\PsExec.exe -accepteula -i $sessionId -d "D:\MetaTrader 5-01\terminal64.exe" /portable
   ```

### Windows Agent 无法启动
检查 Python 环境和依赖：
```powershell
cd C:\MT5Agent
python --version
pip list | Select-String "fastapi|uvicorn|psutil"
```

### 端口冲突
如果 9000 端口被占用：
```powershell
netstat -ano | findstr :9000
# 找到占用进程的 PID，然后：
Stop-Process -Id <PID> -Force
```

## 长期解决方案

当前方案要求 Windows Agent 在用户会话中运行。如果需要作为系统服务运行，可以考虑：

1. **使用 Task Scheduler**: 配置任务在用户登录时自动启动 Windows Agent
2. **Windows 服务 + PsExec**: 保持服务模式，但始终使用 PsExec 跨会话启动 MT5
3. **专用 MT5 启动服务**: 创建独立的用户级服务专门管理 MT5 进程

## 相关文档
- [MT5_SESSION_0_FIX.md](MT5_SESSION_0_FIX.md) - 详细技术分析和多种解决方案
- [MT5_GUI_MODE_FIX.md](MT5_GUI_MODE_FIX.md) - GUI 模式修复记录
- [MT5_STARTUP_FIX_VERIFICATION.md](MT5_STARTUP_FIX_VERIFICATION.md) - 启动功能修复验证
