# 启动 MT5-01 实例（账号 2325036-8002）

## 快速启动步骤

### 方法 1：使用桌面快捷方式（如果存在）

如果桌面上有 "2325036-8002" 快捷方式：
1. 在 RDP 会话中双击该快捷方式
2. 等待 MT5 窗口出现
3. 确认 MT5 已登录（显示账号 2325036）

### 方法 2：使用启动脚本

如果桌面快捷方式不存在或无法使用：

1. **在 RDP 会话中**打开 PowerShell
2. 运行以下命令：
   ```powershell
   C:\MT5Agent\start_mt5_01_instance.ps1
   ```

   或者双击运行：
   ```
   C:\MT5Agent\start_mt5_01_instance.bat
   ```

### 方法 3：手动启动

1. 在 RDP 会话中打开文件资源管理器
2. 导航到：`D:\MetaTrader 5-01`
3. 双击 `terminal64.exe`
4. 等待 MT5 启动并登录

## 验证 MT5 已正确启动

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
- `Path` = `D:\MetaTrader 5-01\terminal64.exe`

## 启动 Bridge 服务

MT5 客户端启动后：

1. 打开浏览器访问：https://admin.hustle2026.xyz/users
2. 找到 **MT5-01 实例**（端口 8002）
3. 点击"启动"按钮
4. Bridge 服务会连接到已运行的 MT5 客户端

## 验证连接成功

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

## 故障排除

### MT5 窗口不可见

**原因**：MT5 在 Session 0 中启动（通过 SSH 或系统服务）

**解决方法**：
1. 停止所有 MT5 进程：
   ```powershell
   Get-Process -Name terminal64 | Stop-Process -Force
   ```

2. 在 RDP 会话中重新运行启动脚本：
   ```powershell
   C:\MT5Agent\start_mt5_01_instance.ps1
   ```

### Bridge 服务无法连接

**原因**：MT5 客户端未正确初始化或未登录

**解决方法**：
1. 在 RDP 会话中查看 MT5 窗口
2. 确认显示账号信息：2325036@Bybit-Live-2
3. 如果未登录，手动输入账号密码
4. 重启 Bridge 服务（管理后台点击"重启"）

### MT5 启动后立即退出

**原因**：配置文件损坏或账号密码错误

**解决方法**：
1. 查看 MT5 日志：
   ```powershell
   Get-Content "D:\MetaTrader 5-01\Logs\$(Get-Date -Format 'yyyyMMdd').log" -Tail 20
   ```

2. 检查日志中的错误信息
3. 如果是账号密码问题，手动启动 MT5 并重新登录

## 重要提示

1. **必须在 RDP 会话中启动**：通过 SSH 启动的 MT5 无法显示 GUI
2. **先启动 MT5 客户端，再启动 Bridge 服务**：这样 Bridge 会连接到已运行的 MT5
3. **保持 RDP 会话活跃**：断开 RDP 后 MT5 窗口会隐藏，但进程继续运行
4. **不要重复启动**：如果 MT5 已经运行，不需要再次启动

## 相关文件

- `D:\MetaTrader 5-01\terminal64.exe` - MT5 客户端程序
- `C:\MT5Agent\start_mt5_01_instance.bat` - 批处理启动脚本
- `C:\MT5Agent\start_mt5_01_instance.ps1` - PowerShell 启动脚本
- `C:\MT5Agent\MT5_GUI_SOLUTION.md` - 完整解决方案文档
