# Hustle2026 系统启动配置说明

## 📋 自动启动服务列表

系统已配置以下服务在开机时自动启动：

### 1. PostgreSQL 数据库服务
- **服务名称**: `postgresql-x64-16`
- **启动类型**: Windows 服务（自动启动）
- **启动延迟**: 无（系统服务优先启动）
- **状态**: ✅ 已配置

### 2. Nginx Web 服务器
- **任务名称**: `HustleNginxService`
- **启动脚本**: `C:\app\hustle2026\start_nginx_service.vbs`
- **启动延迟**: 30秒
- **端口**: 80, 443
- **访问地址**: https://app.hustle2026.xyz
- **状态**: ✅ 已配置

### 3. MetaTrader 5 客户端
- **任务名称**: `HustleMT5Service`
- **启动脚本**: `C:\app\hustle2026\start_mt5_service.vbs`
- **启动延迟**: 1分钟
- **安装路径**: `C:\Program Files\MetaTrader 5\terminal64.exe`
- **状态**: ✅ 已配置

### 4. 后端 API 服务
- **任务名称**: `HustleBackendService`
- **启动脚本**: `C:\app\hustle2026\start_backend_service.vbs`
- **启动延迟**: 1分30秒
- **端口**: 8000
- **访问地址**: http://localhost:8000
- **日志文件**: `C:\app\hustle2026\backend\backend_live.log`
- **状态**: ✅ 已配置

### 5. 前端开发服务器
- **任务名称**: `HustleFrontendService`
- **启动脚本**: `C:\app\hustle2026\start_frontend_service.vbs`
- **启动延迟**: 2分钟
- **端口**: 5173
- **访问地址**: http://localhost:5173
- **日志文件**: `C:\app\hustle2026\frontend\frontend_dev.log`
- **状态**: ✅ 已配置

## 🖥️ 桌面快捷方式

系统已在桌面创建以下快捷方式，方便日常管理：

### 1. Start Hustle2026 Services
- **功能**: 手动启动所有服务
- **图标**: 绿色播放图标
- **说明**: 双击即可启动 Nginx、MT5、后端、前端所有服务

### 2. Check Hustle2026 Services
- **功能**: 检查所有服务状态
- **图标**: 信息图标
- **说明**: 双击查看所有服务的运行状态和任务计划状态

### 重新创建快捷方式
如果快捷方式被删除，可以运行：
```powershell
powershell -ExecutionPolicy Bypass -File C:\app\hustle2026\create_desktop_shortcuts.ps1
```

## 🔧 启动顺序和延迟说明

服务按以下顺序启动，确保依赖关系正确：

```
系统启动
  ↓
PostgreSQL (立即启动)
  ↓ 30秒
Nginx (30秒延迟)
  ↓ 30秒
MetaTrader 5 (1分钟延迟)
  ↓ 30秒
后端 API (1分30秒延迟)
  ↓ 30秒
前端服务器 (2分钟延迟)
```

**总启动时间**: 约2-3分钟完成所有服务启动

## 📝 管理命令

### 查看所有自启动任务
```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -like 'Hustle*'}
```

### 查看任务详细信息
```powershell
Get-ScheduledTask -TaskName "HustleBackendService" | Get-ScheduledTaskInfo
```

### 手动启动任务
```powershell
Start-ScheduledTask -TaskName "HustleBackendService"
```

### 停止任务
```powershell
Stop-ScheduledTask -TaskName "HustleBackendService"
```

### 禁用任务
```powershell
Disable-ScheduledTask -TaskName "HustleBackendService"
```

### 启用任务
```powershell
Enable-ScheduledTask -TaskName "HustleBackendService"
```

### 重新配置所有任务
```powershell
powershell -ExecutionPolicy Bypass -File C:\app\hustle2026\configure_startup.ps1
```

## 🔍 故障排查

### 检查服务是否运行

**PostgreSQL:**
```cmd
sc query postgresql-x64-16
```

**Nginx:**
```cmd
tasklist | findstr nginx.exe
```

**MetaTrader 5:**
```cmd
tasklist | findstr terminal64.exe
```

**后端服务:**
```cmd
netstat -ano | findstr :8000
```

**前端服务:**
```cmd
netstat -ano | findstr :5173
```

### 查看日志

**后端日志:**
```cmd
type C:\app\hustle2026\backend\backend_live.log
```

**前端日志:**
```cmd
type C:\app\hustle2026\frontend\frontend_dev.log
```

**任务计划程序日志:**
```powershell
Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 50 | Where-Object {$_.Message -like '*Hustle*'}
```

### 手动启动所有服务

如果自动启动失败，可以手动运行：
```cmd
C:\app\hustle2026\start_services.bat
```

## 🛠️ 维护说明

### 修改启动脚本

如果需要修改启动配置：

1. 编辑对应的 `.vbs` 文件
2. 重新运行配置脚本：
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\app\hustle2026\configure_startup.ps1
   ```

### 添加新服务

1. 创建新的 `.vbs` 启动脚本
2. 在 `configure_startup.ps1` 中添加服务配置
3. 运行配置脚本

### 移除自启动

如果需要移除某个服务的自启动：
```powershell
Unregister-ScheduledTask -TaskName "HustleBackendService" -Confirm:$false
```

## ⚠️ 注意事项

1. **启动延迟**: 各服务设置了启动延迟，确保依赖服务先启动
2. **日志文件**: 所有服务都会生成日志文件，定期检查和清理
3. **端口冲突**: 确保端口 80, 443, 8000, 5173 没有被其他程序占用
4. **权限**: 所有任务以 SYSTEM 权限运行，确保有足够的权限
5. **重启策略**: 如果服务崩溃，任务计划程序会自动重启（最多3次，间隔1分钟）

## 📞 支持

如有问题，请检查：
1. 任务计划程序中的任务状态
2. 各服务的日志文件
3. Windows 事件查看器中的错误信息

---

**最后更新**: 2026-03-17
**配置版本**: 1.0
