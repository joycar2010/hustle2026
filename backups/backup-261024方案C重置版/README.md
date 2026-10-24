# 261024方案C重置版

服务器 `18.179.50.168` 的 **poly.hustle2026.xyz 与 polyauto.hustle2026.xyz** 双域名完整备份。
这是当前部署的快照标签，备份操作不重置交易历史，也不切换策略。
准确采集时间及各数据库快照时间见 `backup-manifest.json` 与 `database-manifest.json`，时间字段为 UTC。

## 备份范围

- `server-main/polymarketbot/`：poly 前后端源码、程序、脚本、测试、所有应用 dist 和历史程序副本。
- `server-auto/polymarketbot-auto/`：polyauto 前后端源码、程序、OpenClaw、策略、所有应用 dist，以及当前生产 C 的独立 release。
- `paper-shadow/20261022T020933Z/`：A/B/C 独立实验代码及可查阅配置说明。完整实验记录、数据库、日志和原配置在加密归档内。
- `web-roots/`：两个 Nginx 实际静态目录，保留旧哈希 JS/CSS、图片、音频等文件。
- `ops/`：相关 Nginx、systemd unit、drop-in，以及影子实验 LATEST 标记。
- `poly-complete.tar.gz.enc`：Git LFS 中的完整加密归档。包括两个原始应用目录、依赖、当前及历史配置、日志、缓存、全部 dist、A/B/C、部署静态目录、相关服务配置、两个域名的 TLS 证书及私钥，以及 **10 个 SQLite 一致性快照**。

可查阅副本不含明文私钥、API 密钥、控制令牌、原始 `.env`、原始数据库或恢复密钥。
`environment.redacted` 仅列配置名称；被脱敏和仅保存在密文中的路径见对应 manifest。
数据库并非遗漏：其精确归档位置、表行数、大小、SHA-256 和 quick_check 结果记录在 `database-manifest.json`。

## 当前运行版本

polyauto 的 BTC 生产 worker 实际运行：

`/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024`

入口为 `scripts/run_paper_asset_c.sh`，由 `polymarket-auto-btc-paper.service.d/c-strategy.conf` 指向该 release。
**根目录 `bot/main.py` 不等于当前生产 BTC worker 的执行文件。**
生产账本是 `/home/ec2-user/polymarketbot-auto/trades-auto.db`；A/B/C 独立使用各组的 `ab.db`。

本版保留 C 策略：价格 0.84–0.90、剩余 120–180 秒入场、止损回撤 40% / 确认 2 次；生产 BTC 为 Paper，实盘关闭。
包含 12% Paper 日止盈：以 BTC 北京时间当日已实现收益 / $100 模拟本金计，达到 $12 锁定新开仓至次日零点，继续退出及结算，重启保持当日锁定。
包含前端 A/B/C 影子统计移至 BTC 卡右侧的改动；顶部生产今日损益不再混入 A 影子统计。
poly 网页 API 已恢复，服务为 `polymarket-dashboard.service`、端口 8787；polyauto API 为 8887。

## 完整性与不干扰验证

- SQLite Backup API 从只读事务快照采集，包含已提交 WAL 数据；每库 quick_check。不同数据库不构成同一时刻的跨库事务。
- 数据库归档保留原文件属主与权限，内容使用一致性快照；恢复无需旧 WAL/SHM。
- 加密归档已完整解密读取，逐文件核对内容、大小、链接与权限元数据。
- 所有前端清单逐项核对服务器采集前、采集后和公开备份 SHA-256；没有清空、构建或删除线上 dist。
- `poly` 的应用 `ui/dist/index.html` 与当前 Nginx 静态目录入口不同，两个版本都已原样保留。恢复当前线上界面应以 `web-roots/poly.hustle2026.xyz/` 为准，不能直接用应用 dist 覆盖；`polyauto` 两处当前入口一致。
- 两个 dashboard、BTC Paper 和 OpenClaw 持久服务的状态及 PID 前后一致。定时 Agent 自然运行/结束会单独如实记录。
- `CHECKSUMS.sha256` 覆盖 GitHub 备份文件；公开副本通过凭证扫描。

## 恢复密钥与步骤

服务器密钥（不进入 GitHub）：

`/home/ec2-user/backups/poly-261024-c-reset/private/restore.key`

本机受限目录中的独立副本（不在仓库）：

`C:\Users\Administrator\poly-backup-keys\261024\restore.key`

先运行 `git lfs pull`，核对 `CHECKSUMS.sha256`，再进行认证解密：

```sh
python restore_archive.py --key /secure/restore.key --verify-only
python restore_archive.py --key /secure/restore.key --output /restore/poly-complete.tar.gz
```

算法为 AES-256-CBC、PBKDF2-SHA256（200000 次）及独立派生的 HMAC-SHA256；必须先认证密文，再解密。
脚本拒绝覆盖已存在的输出文件，且不会解压或启动服务。

在 Linux 新的空暂存目录中检查归档；部分历史路径不兼容 Windows，原样保存在加密归档中。
禁止直接覆盖运行中的数据库、证书、环境配置或前端。实际恢复数据库前先停止对应写入服务，确认属主、路径和 Paper/Live 配置。
旧 PID、心跳和 `bot.mode` 不代表恢复时应开启实盘。跨主机应按依赖锁文件重建环境。
TLS live 链接、archive 实体及 renewal 配置已保留；系统软件包和 Certbot ACME 账户不属于应用备份，迁机后须配置并验证证书续期环境。
