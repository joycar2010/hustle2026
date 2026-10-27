# polyauto BTC C 策略：Paper 日止盈补齐

部署时间：2026-10-24 11:19–11:20（北京时间）。

## 实际运行位置

- 服务器：18.179.50.168，域名 polyauto.hustle2026.xyz。
- Paper service：polymarket-auto-btc-paper.service。
- 生产执行目录：`/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024`。
- 生产账本：`/home/ec2-user/polymarketbot-auto/trades-auto.db`，原数据保留。
- 入口脚本：`/home/ec2-user/polymarketbot-auto/scripts/run_paper_asset_c.sh`。
- systemd drop-in：`/etc/systemd/system/polymarket-auto-btc-paper.service.d/c-strategy.conf`。
- C 影子源码仍为 `/home/ec2-user/paper-ab/20261022T020933Z/C`，未修改。
- 注意：根目录 `polymarketbot-auto/bot/main.py` 不是当前生产 BTC worker 的执行源码。

## 本次行为

旧 C 不读取百分比参数，Paper 直接绕过日止盈，旧 live 止盈触发时还会 break 退出整个 worker。

本次仅为生产 C 添加 Paper 百分比止盈：BTC 当日已实现收益 / 固定模拟本金；北京时间交易日。
`MAX_DAILY_REALIZED_PROFIT_FRACTION=0.12`，`PAPER_EQUITY_USD=100`，阈值为 $12。
达到阈值后锁定所有新买入（包括复查、重试、加仓），持仓退出与结算继续；北京时间次日零点自动恢复。
触发后回落或进程重启仍保持当日锁定。
状态文件在生产账本旁：`trades-auto.db.paper-profit-BTC.json`，首次触发才创建。
损坏状态或核算失败会阻断新开仓并返回错误；需要检查原因，不能手动删除状态绕过风控。
dashboard 读取同一状态，显示 `PROFIT_TAKE`；状态损坏显示 `PROFIT_GUARD_ERROR`。

主循环后台检查复用最多 10 秒的核算缓存。两个实际买入风控点始终实时核算；结算、退出、跨日和配置变化使缓存失效。
当前配置仍从生产专用 C 副本 `.env` / systemd EnvironmentFile 加载，页面主目录 `.env` 不代表所有 C 策略参数已经热更新。

## 验证与保留项

- 23 项测试通过：真实临时 SQLite + 模拟行情的主循环，验证阈值、BTC/Paper/账本隔离、跨日、重启、持仓管理、缓存绕过。
- 全部既有 Config 字段比对一致，仅新增百分比字段读取。
- 策略、订单、结算、store 等 20 个模块与原 C 字节一致。
- 价格 0.84–0.90、剩余 120–180 秒入场、止损回撤 40% / 确认 2 次保留。
- Live 关闭，启动命令无 `--live`；A/B/C 影子目录与账本均保留。
- 前端及所有 dist 文件没有修改或删除。
- 公网首页与 `/api/state` 正常；接口返回 fraction=0.12、limit_usd=12、Paper worker running。
- 验证时当日收益未达 $12。达标与跨日行为通过隔离测试验证，没有伪造生产盈亏触发。

## 回滚资料

服务器备份：`/home/ec2-user/polymarketbot-auto/deploy-backups/c-paper-profit-20261024`。
含原 dashboard、launcher、drop-in、源码指纹、服务状态与部署结果；不包含公开密钥输出。
如需撤回，只恢复备份中的 dashboard、launcher、drop-in，再 daemon-reload 并重启对应 Paper/dashboard 服务。
不得覆盖或删除交易数据库，不得删除 frontend dist，不得修改影子源码。撤回旧 C 会同时撤去本次 Paper 日止盈保障。
