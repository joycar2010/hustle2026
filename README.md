# Hustle2026 MT5 Bridge — Windows Server 2025

## 服务器信息
- Windows Server 2025: 54.249.66.53
- 系统账户服务: http://54.249.66.53:8001/health
- 用户cq987服务: http://54.249.66.53:8002/health

## 部署目录
| 实例 | 目录 | 端口 | MT5 终端 |
|------|------|------|----------|
| 系统账户 | D:\hustle-mt5\ | 8001 | C:\Program Files\MetaTrader 5\terminal64.exe |
| 用户cq987 | D:\hustle-mt5-cq987\ | 8002 | C:\Program Files\MetaTrader 5-01\terminal64.exe |

## 快速部署
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
cd <本目录>
.\deploy-mt5.ps1
```

## 环境配置
- `.env.system`  → 系统账户配置（填写 MT5 账号密码）
- `.env.cq987`   → 用户cq987配置（填写 cq987 MT5 账号密码）

## 服务管理
```powershell
Start-Service hustle-mt5-system   # 启动系统服务
Stop-Service  hustle-mt5-system   # 停止系统服务
Get-Content D:\hustle-mt5\logs\stderr.log -Tail 50 -Wait  # 查看日志
```

## API Key
X-API-Key: OQ6bUimHZDmXEZzJKE

## 依赖
- Python 3.11+
- MetaTrader5==5.0.45
- numpy>=1.20,<2.0 (必须 <2.0，否则 MT5 SDK 不兼容)
- NSSM (Windows 服务管理)
