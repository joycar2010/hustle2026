# MT5/MT4 桥接服务器备份 (43.206.15.17 / 私网 172.31.5.62)

QuantHedge 桥接服务器上**桥相关程序文件与部署模板**的备份。所有凭证(共享 API key、MT5/MT4 密码)已脱敏为 `<REDACTED_*>`;终端二进制、venv、登录态(accounts.dat/start.ini)、ledger 数据库、日志均已排除。

## 拓扑

Windows Server,同机三套并存、互不干扰:

- **`D:\QHCELL`** — 区域自治 Cell（暖池秒供）。`cell.py`(FastAPI@8600)管 6 个预热槽位：s1-s4 = MT5（IC/Exness 族），m1/m2 = MT4（IC/Exness 族）。分配 = 写凭证→起桥/终端自登录→等 `/health` 就绪→返回 `bridge_url`+实测路由指标；释放 = 杀进程+抹凭证+回暖。`QHCELL-Agent` 交互计划任务(session 2)拉起，看门狗自愈。
- **`D:\QHMT5`** — MT5 生产桥。`supervisor.ps1`(受监督单一所有者，session 1/2 交互会话)+ `guardian.ps1` 双拉守护；4 桥合并式 `mt5.initialize(path,login,password,server)` 自登录。桥权威代码 `runtime/ic/app/main.py` 与 `runtime/bybit/app/main.py`。
- **`D:\MT4LAB\agent`** — 自建 MT4 桥。`QHBridge.mq4`(EA，OnTimer 导出 state + 处理命令）→ 文件桥 → Python Agent(`main.py`，复刻 `/mt5/*` 协议 + `ledger.py` 命令账本 SQLite-WAL 幂等）。

## 会话拓扑铁律（关键运维知识）

- **MT5 桥必须交互会话**（session 1/2）：session 0 下 `mt5.initialize` IPC 超时。
- **MT4 GUI 终端必须 session 0**：交互会话（RDP）登录失败(443 建立但认证不过)。Cell 自身跑交互会话供 MT5，起 MT4 终端经 **SYSTEM 计划任务**(`QHCELL-t-m1/m2`)甩到 session 0。二者会话需求相反。

## 目录

- `QHCELL/` — cell.py、run_cell.ps1、cell.env.template、slots.template.json
- `QHMT5/` — supervisor/guardian/launch/seed 脚本、instances/\*/.env.template、runtime/{ic,bybit}/app/main.py
- `MT4LAB/agent/` — filebridge/ledger/main/simulator/test_phased.py、QHBridge.mq4/ex4、run_agent.ps1.template
- `scheduled-tasks/` — 9 个计划任务 XML（部署模板，无密码）

## 部署要点（还原）

1. 复制目录结构到 D:\；`pip install` 桥依赖（MetaTrader5 5.0.45 + numpy==1.26.4 钉版，fastapi/uvicorn）建 venv-ic/venv-bybit。
2. 填 `.env` / `cell.env` 的 `<REDACTED_*>`（共享 API key + MT5/MT4 密码）。
3. 导入 `scheduled-tasks/*.xml`（交互任务须落 session 1/2，SYSTEM 任务 `QHCELL-t-*` 落 session 0）。
4. MT4 终端：用安装版复制 + `QHBridge.ex4` 铺 `MQL4\Experts` + profile 挂 EA chart 并勾「允许实时交易」。
5. ⚠写 MT4 `start.ini` 用 `newline=""`（否则 Windows 文本模式把 `\n`→`\r\n` 叠加成双回车，账号带尾随 `\r` 认证失败）。
