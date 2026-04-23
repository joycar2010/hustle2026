# MT5 基础设施加固 — 2026-04-23

本次加固解决了 2026-04-23 上午 admin 面板报"Failed to fetch account data: 网络错误: 638"的故障，并对整套 MT5 Bridge 基础设施做了系统性自愈、监控与告警建设。

## 故障复盘

| 症状 | 根因 |
|---|---|
| `joycar2011@gmail.com` MT5 账户报 638 (Internal Server Error, socks5 代理) | Python 后端 MT5 分支冗余调用 Bybit `get_bybit_daily_pnl`，走账户 socks5 代理失败被 `asyncio.gather` 抛出整体失败 |
| MT5WindowsAgent 服务无法启动 (`SCM 7000: 找不到指定文件`) | 注册表 `ImagePath` 仍指向 WinGet 旧 junction `C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\nssm.exe`（已失效） |
| 7 个 hustle-mt5-* bridge 服务全部 Paused | Agent 长期未运行 → bridge 失去编排心跳，被反复挂起 |

## 加固清单

### 1. 应用层根因修复
- `backend/app/services/account_service.py` 移除 MT5 分支对 `get_bybit_daily_pnl` 的调用；保留的 3 个 MT5 Bridge 调用改为 `asyncio.gather(..., return_exceptions=True)`，单路失败降级为 None/[]，不拖垮整体拉取。

### 2. Windows 服务自愈层
- `MT5WindowsAgent` 注册表 `ImagePath` 修正为 `C:\nssm\nssm.exe`
- `MT5WindowsAgent` + 7 bridge 全部应用 `sc failure` 三档退避：30s / 60s / 120s（24h 复位）
- `MT5WindowsAgent` nssm `AppEvents Start/Pre` 钩子调用 `preflight.ps1`：启动前自检 python.exe / main_v3.py / nssm.exe / 8765 端口、工作目录
- 7 bridge 设置 `ServicesDependedOn = MT5WindowsAgent`：开机/重启时按依赖顺序起服务

### 3. /health 端点增强
- `MT5WindowsAgent /health` 返回完整状态：uptime、MT5 instances、7 bridge 的 SCM 状态、对应监听端口
- 热路径 < 200ms（sc.exe 并行查询）
- `BRIDGE_SERVICE_PORTS` 改为"内置默认 + `bridge_ports.json` 持久化"合并加载，`bridge/deploy` 端点会自动注入新部署的 bridge

### 4. 主动监控与告警
- Windows Task Scheduler `MT5InfraHealthcheck` 每分钟触发 `healthcheck_loop.ps1`，内部跑两次 `healthcheck.ps1`（间隔 30s）
- `healthcheck.ps1` 探测 Agent /health + 7 bridge 端口 HTTP 200/4xx 存活，连续失败 2 次写入 `healthcheck.alert.json`
- `healthcheck_alert.ps1` 消费告警文件：BurntToast/msg.exe 桌面弹窗 + 后端 `/api/v1/mt5-infra/alert` POST → 飞书卡片到管理员 open_id + Redis publish `ws:admin_event`
- 自动恢复：恢复健康时清空 alert 文件 + dispatch 状态，下次故障重新告警

### 5. 部署链路注入加固
- Agent `bridge/deploy` 在 nssm install 之后、start 之前调用 `_harden_bridge_service(svc)` 自动套用 sc failure + depend= MT5WindowsAgent
- 同时调用 `_persist_bridge_port(svc, port)` 把新 bridge 注册进 `bridge_ports.json` 让 `/health` 立刻反映
- admin 前端 UserManagement.vue 部署进度面板从 9 步扩到 11 步，新增"配置崩溃自动重启策略"和"绑定 MT5WindowsAgent 启动依赖"

### 6. admin 面板 Bridge 卡片增强
- MasterDashboard.vue MT5 Bridge 服务器卡片底部新增 Agent + Bridges 子区域：
  - Agent 状态 / uptime
  - Bridges N/N 活跃
  - 7 端口状态点（绿/红）
- 数据源：后端新增 `/api/v1/mt5-infra/{status, alert, alert/last}` 三个端点；nginx 加 `/api/v1/mt5-infra/` location

## 文件清单

| 路径 | 说明 |
|---|---|
| `MT5Agent/main_v3.py` | Agent 主程序，含本次加固（+800 行） |
| `MT5Agent/preflight.ps1` | nssm Pre-Start 启动前自检 |
| `MT5Agent/healthcheck.ps1` | 30s 巡检主体 |
| `MT5Agent/healthcheck_loop.ps1` | Task Scheduler 1 分钟触发，内部跑 2 次 |
| `MT5Agent/healthcheck_alert.ps1` | 桌面弹窗 + 后端 POST 派发器 |
| `hustle-mt5-template/app/main.py` | bridge 模板（与生产 by02 同步） |
| `docs/HARDENING_2026-04-23.md` | 本文件 |
| `docs/nssm-dumps/*.txt` | 8 个 Windows 服务的 nssm 配置（密码自动脱敏为 `****`） |
| `docs/db-schema.sql` | mt5_clients/mt5_instances/mt5_config 三张表 schema + 脱敏行（密码全部 REDACTED） |

## 部署清单（备份用）

7 个 Bridge 服务的 service ↔ port 映射（备份用，bridge_ports.json 是运行时事实）：

| 服务名 | 端口 | MT5 Login | MT5 Server |
|---|---|---|---|
| hustle-mt5-mt5-by01 | 8001 | 2163899 | Bybit-Live-3 |
| hustle-mt5-mt5-by02 | 8002 | 6380983 | Bybit-Live-2 |
| hustle-mt5-mt5-by03 | 8003 | 3971962 | Bybit-Live-2 |
| hustle-mt5-mt5-bysys | 8886 | 2325036 | Bybit-Live-2 |
| hustle-mt5-mt5-ic01 | 8021 | 15016910 | ICMarketsSC-MT5-6 |
| hustle-mt5-mt5-ic02 | 8022 | 15017157 | ICMarketsSC-MT5-6 |
| hustle-mt5-mt5-icsys | 8888 | 15015331 | ICMarketsSC-MT5-6 |

完整 Schema 与字段见 `docs/db-schema.sql`。

## 操作记录

- Windows scheduled task: `MT5InfraHealthcheck`（SYSTEM 账户，每分钟触发）
- Agent /health: `http://127.0.0.1:8765/health`（无需 API key）
- 后端聚合接口: `https://admin.hustle2026.xyz/api/v1/mt5-infra/status`（X-API-Key 或 user JWT）
- 飞书告警接收人 open_id: `ou_613cc2eabae277733bdee67edb3d8cc5`
