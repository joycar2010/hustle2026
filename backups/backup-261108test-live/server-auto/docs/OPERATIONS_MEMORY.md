# Polyauto 运维记忆

## 2026-09-12：前端空白页根因与固定流程

- `polyauto.hustle2026.xyz` 使用 Nginx 静态目录 `/var/www/polyauto.hustle2026.xyz`。
- 前端部署后必须确保目录可遍历、文件可读取：目录权限 `755`，文件权限 `644`。
- 如果 `assets/*.js` 或 `assets/*.css` 被 Nginx 返回为 `text/html`，说明资源不可读并触发了 `try_files ... /index.html` 回退，浏览器会显示空白页。
- 每次同步 `ui/dist` 后执行：

  ```bash
  sudo find /var/www/polyauto.hustle2026.xyz -type d -exec chmod 755 {} +
  sudo find /var/www/polyauto.hustle2026.xyz -type f -exec chmod 644 {} +
  sudo nginx -t && sudo systemctl reload nginx
  ```

- 部署后必须验证：主页引用的 JS/CSS URL 返回 `200`，且 JS 为 `application/javascript`、CSS 为 `text/css`，不能只验证主页 HTML 的 `200`。

## 当前运行边界

- BTC、ETH：polyauto 实盘 Worker；OpenClaw 负责调度、分析、风控和状态汇总。
- 天气、体育：Paper-only。
- OpenClaw 不持有私钥，不能绕过确定性风控直接下单。

## OpenClaw / LLM 调用核验

- `server/run_openclaw_paper.py` 只维护角色心跳和队列，不会自动调用模型。
- 模型调用必须通过 `/api/llm/advisor` 或 `/api/openclaw/consensus`，调用后 `/api/llm/usage` 才会出现模型 TOKEN 统计。
- 核验时同时查看 `LLM_PRIMARY_ENABLED`、`LLM_SECONDARY_ENABLED`、`LLM_ADVISOR_ENABLED` 和 `/api/llm/usage`；配置关闭或模型列表为空时，界面应显示“尚未调用 / 0 TOK”，不得伪造消耗数据。


## 2026-11-01：BTC 生产止损参数与保存链路修复（当前运行边界）

- 本次用户确认保留日亏损 5%、日止盈 8%、单笔风险 2%，将回撤止损设为 10%。
- 当前仅 BTC 生产 Paper，`BTC_LIVE_ENABLED=false`。活跃源码仍为 `releases/c-paper-profit-20261024`，策略 D，生产账本 `trades-auto.db`；本次未更改历史账本或影子 A–H。
- 保存设置前 Worker 为 failed：`write_runtime_manifest.py` 把策略名 D 错比为 D-production，并锁死旧的 3%/12% 及未启用的部分止损默认值。已仅对生产可编辑字段做范围校验，保留 A/B 固定实验校验。
- 策略管理新增回撤止损 %、单笔风险 %，分别写入 `REVERSAL_HELD_BID_DRAWDOWN`、`ORDER_RISK_FRACTION`；前端输入百分比，API 使用 fraction。
- `/api/settings/risk` 完整校验后同步更新 ROOT/.env 与 systemd 实际 EnvironmentFile；只重启生产 BTC Paper。成功前核验新 PID、Paper 模式、源码目录、账本及全部保存风控参数；重启/加载失败返回 503，不再吞错。等待运行在后台线程，避免卡住状态推送。
- UI 保存后立即刷新 state，轮询保留未提交草稿。回撤/单笔风险输入范围为大于 0%、不超过 100%。
- `runtime-manifest.json` 的 pid 现在对应随后 exec 的 Worker 父 shell PID，另保留 manifest_writer_pid。
- 已验证：64 项后端回归通过；线上 1440px / 390px 浏览器页面错误为 0；进程、manifest、ROOT/release 配置、state 均为止损 10% / 单笔风险 2% / 日亏损 5% / 日止盈 8%，risk_state=OK。
- 备份：`backups/btc-stop-controls-20261101T024939Z/before.tgz`，含变更前源码、ROOT/release .env、manifest、完整 ui/dist 和站点目录；受限权限，含密钥，勿提交到公开仓库。
- 发布采用新增 hashed assets 后替换 index 的方式，保留全部旧 dist 资源；影子组、OpenClaw 与另一域名的服务 PID 均未改变。


## 2026-11-01：BTC 每日历史加速与 H MISPRICE Paper 执行修复

- 历史接口旧实现逐日调用全账本 FIFO，46 天 Paper 首次 5.63 秒。新增 `server/pnl_history.py`：同一只读快照读取一次、按 lot/日聚合退出与剩余份额结算、短缓存 2 秒，结束日期也会刷新，避免迟到结算永远不更新。保持原 store 的 (cutoff,end]、部分退出、dust 和胜负口径。未改 bot/store.py 或生产策略。
- 真实账本逐行比对 Paper/BTC 46 天、ETH 32 天及 Live 和全资产记录完全一致；纯计算 0.15 秒；部署后接口约 0.32 秒，缓存命中约 0.003 秒。
- 前端增加请求合并、15 秒超时、刷新按钮和近期快照复用；已有较大历史页可供弹框切页先显示再刷新，不再显示加载期间的假 0 天。线上 PC/手机验证无脚本/资源错误，分页正确。
- H 已是独立 MISPRICE，原 H 累计仅一笔：0.58 买 DOWN，0.28 卖出，45% 紧急止损，毛 -1.416 美元；按现有 fee 模型估计手续费 0.147164，净 -1.563164。原订单与亏损保留，样本不足以判断策略收益。
- 修复 H-only `code/bot/protection_runner.py` 最终门：真实 fair-price-fee-slippage 边际复核；来源、时效、时间窗、token/方向和价格校验；真实模型参数写入 accepted BUY 的审计元数据。
- H 新 `code/bot/misprice_execution.py` 将固定 12 美元视为上限，按 min(12,本金×2%,剩余日亏预算) 裁剪，计入估算买入费用并向下取整；不足最小订单明确跳过。保留 H 3% 日亏、12% 日盈、45% 紧急止损，不放开风控。
- H 代码 `/home/ec2-user/paper-protection/misprice-h-20261031T200000Z/code`；账本及审计脚本 `/home/ec2-user/paper-protection/20261028T080000Z/H`。不要误改成生产 release。
- 修复 H 审计北京时间日期及平均净边际读取；旧单缺少真实最终边际继续显示 null，不伪造历史。H 卡片与日记录优先使用后端真实标签 MISPRICE Paper。
- OpenClaw 这里只做确定性 Paper 适配、审计及 SHA256 模拟签名，未调用双 AI 决策，不能描述成真实 CLOB 签名或实盘。
- 本次只重启 H Paper 和 polyauto dashboard；生产 BTC Worker PID 458255 保持不变，仍为 Paper，止损10%/单笔2%/日亏5%/日盈8%。A–G 和另一域名未重启；agents oneshot 按既有 timer 正常运行。
- 新增 23 项历史/H 执行回归通过，已有 64 项风控回归通过。备份 `backups/history-misprice-h-20261101T032904Z`，含变更前源码、完整 dist/站点、H 配置/审计与一致性 SQLite 备份；所有旧 dist assets 保留。
