# polytest BTC 策略同步及每日盈亏历史修复

执行日期：2026-11-01。目标：`https://polytest.hustle2026.xyz`。

## 根因

1. polytest 的 BTC 仍在运行旧 release，止损为30%；polyauto 当前实际配置已为10%，两者的策略源码也不同，不能只复制页面参数。
2. polytest 每日历史接口原本约14毫秒，没有重现 polyauto 旧版逐日重复全表FIFO的5秒问题。原前端缺少快照复用、请求合并和超时恢复；本次同步缓存、分页、主动刷新及只读聚合查询，减少重复等待。
3. 新旧 release 切换后，单独写 dashboard 的.env 会造成显示与运行不一致；现在保存设置同时更新两处，并验证新进程确实加载参数。
4. 旧 dashboard 将Paper止损窗口写成全程保护；已改为显示当前策略实际150秒窗口。历史退出原因保留原值。

## 已部署

| 参数 | polytest 当前实际生效值 |
| --- | --- |
| 策略来源 | polyauto 当前实际运行的生产BTC代码，D配置 |
| 入场价格 | 0.84–0.90 |
| 入场剩余时间 | 90–150秒 |
| 入场确认 | 2次 |
| BTC delta | UP ≥ +10美元；DOWN ≤ -10美元 |
| 止损 | 相对买入价格回撤10%，确认2次；150秒窗口 |
| 单笔风险 | 2%；$100模拟本金的基础预算为$2 |
| 日亏损门槛 | 5% |
| 日止盈门槛 | 8% |
| 模式 | Paper；BTC实盘关闭，Kelly关闭 |

复制30个bot Python文件和manifest脚本，31个文件哈希逐项一致；169个有效非敏感策略字段一致。公开RTDS源、TWAP topic、时区和feed ID显式一致。已将失效的旧BTC止损别名同步为10%，消除歧义。

## 验证

- 50项Worker行为测试、42项dashboard/历史/保存链路测试通过；目标服务器原依赖可直接使用。
- 行为例：买价0.90，卖一买盘回落到0.81时需连续两次确认才触发Paper卖出；回升会清除确认。超出窗口或已到期不伪造卖出。
- 通过实际认证的保存接口提交同值设置并重启，约1.48秒返回；新PID与两份.env、运行环境、manifest及状态API一致。
- 历史查询服务器内首次约11毫秒，缓存命中约2毫秒。现有8天Paper日盈亏及胜负与原账本完全一致；Live无历史数据。
- 线上浏览器18/18通过：PC/手机首次历史显示0.20–0.27秒，缓存重开约0.14秒，无空白、脚本错误或资源请求失败。
- 原orders596条、resolutions415条完整保留；新决策记录持续增长。没有复制polyauto账本或账号凭据。
- polyauto生产BTC PID458255保持运行；目标服务器另一域名BTC/dashboard PID5265/5267、test OpenClaw PID13530未变。

## 运维位置

- polytest当前SSH：`18.177.149.23`，原35.78.246.81已失效。
- 新BTC release：`/home/ec2-user/polymarketbot-test/releases/polyauto-d-20261101`。
- Dashboard保留旧兼容依赖：`/home/ec2-user/polymarketbot-test/releases/85056d2-20261025`，端口8897。
- 账本仍为旧release的`trades-test.db`，止盈/熔断状态文件同目录保留。
- systemd切换：`polymarket-test-btc-paper.service.d/90-polyauto-d.conf`。
- manifest：旧dashboard release中的`runtime-manifest.json`；该目录允许ec2-user写入，勿误放到root所有的上级目录。
- 备份：`/home/ec2-user/polymarketbot-test/backups/strategy-history-sync-20261101T035338Z`，包含源程序、配置、完整dist/网站、unit及SQLite一致性备份。
- 新静态资源：`index-DxQIIagm.js` / `index-DLPKg7Ji.css`；所有旧assets均保留，发布先资源后index。

参数与代码一致，只保证执行规则一致。两站的起跑时间、独立历史账本、行情采样、已有仓位和风控锁状态不同，不要求历史收益相同；新参数的实际收益仍需后续Paper样本验证。
