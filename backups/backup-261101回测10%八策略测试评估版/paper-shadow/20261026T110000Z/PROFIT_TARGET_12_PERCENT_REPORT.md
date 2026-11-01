# A/B/C/D Paper 日止盈调整为 12%

执行时间：2026-10-27 12:38:16 北京时间；服务器 18.179.50.168。

四组实际环境均已设置 `MAX_DAILY_REALIZED_PROFIT_FRACTION=0.12`，随后重启四个影子 Worker 并从进程环境重新加载 Config 验证。各组 $100 模拟本金，对应 BTC 当日已实现止盈门槛 $12；北京时间次日零时解除当天止盈暂停。保持 1% 日亏损及各组原入场、止损、仓位参数。

| 组别 | 日止盈 | 日亏损 | 重启后 PID | 复核状态 |
|---|---:|---:|---:|---|
| A | 12% | 1% | 3613497 | Worker 正常运行，日亏损熔断仍阻断买入 |
| B | 12% | 1% | 3613498 | 正常策略评估 |
| C | 12% | 1% | 3613499 | 正常策略评估 |
| D | 12% | 1% | 3613500 | 原 6% 止盈暂停已解除，恢复策略评估 |

D 原有持久 6% 止盈锁已在停止 Worker 后归档至私有备份。新 Worker 启动后先按当前累计当日已实现损益检查 12% 门槛，再进行入场判断；复核时 D 为 +$6.202564，未达新门槛，已产生新的 SKIP_PRICE / SKIP_TIME 策略判断。没有伪造或强制生成订单。

亏损恢复状态文件保持原样，A 的 1% 亏损保护没有解除。四组继续 Paper、非实盘订单数为 0。源代码哈希与历史 orders/decisions/resolutions 行计数核验通过。

生产 BTC Worker、dashboard 的 PID 与环境文件哈希均未变化。生产仍为 D 配置、日亏损关闭、日止盈 10%。页面及前端 dist 未修改。

私有备份：`/home/ec2-user/backups/shadow-abcd-profit12-20261027T043800Z`，含每组原环境文件、候选配置、SQLite 一致性快照、旧止盈锁及校验清单。原 D 锁保存在 `D/archived-lower-profit-latch.json`。

证据：`before.json`、`after.json`、`deployment.json`、`verification.json`。远端配置记录：`/home/ec2-user/paper-ab/20261026T110000Z/PROFIT_TARGET_12_PERCENT.json`。

回滚时仅恢复四组备份的环境文件及适用的当日止盈状态并重启四组，不回写数据库快照，不操作生产或前端资源。
