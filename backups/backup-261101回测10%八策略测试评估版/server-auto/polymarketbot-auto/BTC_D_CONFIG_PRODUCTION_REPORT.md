# polyauto 生产 BTC 同步 D 组配置

部署：2026-10-27 12:18:21 北京时间，18.179.50.168。

## 已完成

生产 BTC 按影子 D 组实际运行配置同步，用户指定的两个差异是关闭日亏损熔断、日止盈使用 10%。保持 BTC Paper，未开启实盘。

| 参数 | 调整前 | 当前 |
|---|---:|---:|
| 入场价格 | 0.84–0.90 | 0.84–0.90 |
| 入场剩余时间 | 120–180 秒 | 90–150 秒 |
| 入场确认 | 2 次 | 2 次 |
| 止损监控窗口 | 剩余 90 秒以内 | 剩余 150 秒以内 |
| 止损回撤 | 40% | 30% |
| 止损确认 | 2 次 | 2 次 |
| 日亏损熔断 | 1% | 0，关闭 |
| 日止盈 | 本次检查时已经 10% | 10%，确认有效 |
| 模拟本金 | $100 | $100 |
| 单笔风险比例 | 2% | 2% |
| 最大未结仓位 / 小时次数 | 3 / 40 | 3 / 40 |

D 组和生产 main/config/strategy/risk/store 源码在操作前一致，策略差异来自参数。本次未替换交易策略源码；按实际 Worker 进程环境验证了 172 个配置字段，除用户明确指定的日亏损 0、日止盈 10% 外均与 D 组一致。

## 日亏损与止盈核查

操作前生产实际收益约 -$1.171022，1% 日亏损正在阻断，恢复状态为 LOSS_CAP_HOLD。生产进程已读取 MAX_DAILY_REALIZED_PROFIT_FRACTION=0.1，并非仍在用 6%；当日无止盈锁文件，所以没有删除任何锁记录或历史数据。

生产根 .env 与实际 release .env 同步更新，BTC 专用回撤字段同时更新。原设置接口把 0 强制夹至 1%，本次修复为 0=关闭，正数仍保留 1%–50% 范围；非法、非有限或负值拒绝保存。页面输入允许 0，指标与模态框明确显示“关闭”。

新的日亏损配置令恢复模块自然进入 NORMAL。因为日亏损闸门已关闭，条件恢复模块保留但不需要为日亏损授予例外。单笔止损、持仓上限、小时频率、价格与行情检查继续执行。

日止盈以北京时间 BTC Paper 当日已实现损益 / $100 模拟本金计算，10% 对应 $10；达到后阻断新开仓直到次日北京时间零时，已有持仓继续管理和结算。它不是浮盈浮亏收益率的绝对上限。

## 验证

- Worker PID 3611107，dashboard PID 3611108，均 active。
- 启动日志：window=90.0-150s，exit=150-0s dd>=30%/2x，Paper daily_target=10.0%，limit=$10。
- 北京时间 12:18:58，本机及公网 /api/state 均 200，Paper、RUNNING、risk_state=OK、new_entries_blocked=false；亏损恢复文件已为 NORMAL。
- 设置接口 15 项隔离测试通过；TypeScript 检查与 Vite 构建通过；新 JS/CSS 公网 200，MIME 正确。
- 策略源码哈希未变；A/B/C/D 四组 PID、配置文件哈希均未变。影子组继续 1% 日亏损 / 6% 日止盈。
- 数据库一致性快照成功；历史 orders/decisions/resolutions 行保留，没有新增实盘订单。没有强制生成订单，恢复后的买入仍需满足策略信号。
- ui/dist 原件及原网站旧静态资源校验保留。新前端在独立目录构建、增量发布资源，index.html 原件已备份。

## 运行路径与备份

- BTC 仍在 `/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024` 执行；目录名保留 C 历史命名，但参数已为本报告 D 配置。
- 根目录 `/home/ec2-user/polymarketbot-auto`，数据库 `trades-auto.db`。
- 私有备份 `/home/ec2-user/backups/polyauto-before-prod-d-20261027T041707Z`：双 .env、dashboard/App 原稿、原首页、数据库快照、配置和哈希清单。
- 运行记录 `BTC_D_CONFIG_PRODUCTION.json`。本机证据为 `production-before.json`、`production-after.json`、`health-after.json`、`deployment.json`、`verification.json`。
- 回滚只恢复受影响的配置/源码/首页并重启目标两个服务；不覆盖持续写入的数据库、不删除 dist 或旧资源、不操作四组影子。
