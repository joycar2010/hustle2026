# Operations memory


## 2026-11-01：polytest 同步 polyauto 生产BTC及每日历史修复

- polytest当前服务器18.177.149.23；旧35.78.246.81失效。不要触碰该机另一个域名的polymarket-auto-*服务。
- BTC服务polymarket-test-btc-paper.service已切至`/home/ec2-user/polymarketbot-test/releases/polyauto-d-20261101`，drop-in为90-polyauto-d.conf。30个bot Python源码及manifest脚本取自polyauto实际运行release，31文件哈希一致、169项有效配置一致。
- 当前策略D：0.84–0.90，剩余90–150秒入场，delta±10，入场/止损确认2次，止损10%（150秒窗口），风险2%，本金100美元，日亏5%，日盈8%；Paper且实盘关闭，Kelly关闭。失效旧别名BTC_REVERSAL_HELD_BID_DRAWDOWN同步为0.10。
- Dashboard仍从`releases/85056d2-20261025`运行、端口8897，继续使用它原来的bot.store/risk接口，禁止直接覆盖其bot目录为新worker源码，否则dashboard会缺少旧会计接口而崩溃。
- 账本`releases/85056d2-20261025/trades-test.db`及原熔断/止盈sidecars原地保留，无清理、无复制生产钱包凭据。新launcher将bot_btc.pid、bot.mode和runtime-manifest.json写回旧dashboard release目录（上级BASE目录root所有，不可写）。
- 策略保存API同时更新dashboard ROOT/.env和systemd实际worker.env，原子备份保存，异步重启并核验新PID、Paper命令、账本及6项风控配置。实际同值保存/重启测试约1.48秒通过。
- 每日历史改为只读FIFO投影/2秒短缓存；UI合并请求、30秒缓存复用、15秒超时、分页及刷新按钮。8天旧历史完全一致；内部11毫秒首次/2毫秒命中，线上PC/手机0.20–0.27秒，缓存重开约0.14秒。止损状态正确显示150秒窗口，保留所有历史事件。
- 50项worker+42项历史/风控回归及18项线上浏览器检查通过。发布资源index-DxQIIagm.js、index-DLPKg7Ji.css；所有旧dist资源保留。
- 完整本机备份`/home/ec2-user/polymarketbot-test/backups/strategy-history-sync-20261101T035338Z`：源码/配置/全部dist及站点、unit、SQLite一致性备份；含敏感配置，禁止明文提交Git。
- 生产18.179.50.168 BTC进程PID458255未变；目标机另一域名BTC/dashboard5265/5267、OpenClaw13530未变。收益不可据同步保证，需积累独立Paper样本。
