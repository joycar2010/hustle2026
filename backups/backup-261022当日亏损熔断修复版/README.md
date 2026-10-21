# 261022当日亏损熔断修复版

服务器 `18.179.50.168`，域名 `polyauto.hustle2026.xyz` 当前部署备份。
标签按用户要求保留；实际采集时间为 **2026-10-21 17:33:40–17:37:48 UTC**（北京时间 2026-10-22 01:33:40–01:37:48）。
本次备份基于 `a4c00d7706db9f3c38dfe7d80b761d81983cd258` 新增，不删除旧分支历史和旧备份。

## 内容与验证

- `server-auto/polymarketbot-auto/`：可查阅的前后端源码、策略、Agent、脚本、测试、应用 dist 和历史代码副本。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 实际对外静态目录，包括历史哈希资源、图片与音视频。未构建、删除或替换线上 dist。
- `ops/`：polyauto 的 systemd unit、drop-in、Nginx 配置。
- `polyauto-complete.tar.gz.enc`：完整加密归档，经 Git LFS 存放；包括原始应用目录、依赖、历史配置、日志、缓存、所有 dist、实际 web root、部署配置及 5 个 SQLite 在线快照。明文数据库不提交到 Git。
- SQLite 使用 Backup API 合并已提交 WAL，逐库通过 `PRAGMA quick_check`；不是跨库同一时刻事务快照。恢复不依赖旧 WAL/SHM。
- 前端 207 个文件清单项在采集前、采集后和备份中逐项校验；服务状态及 PID 在备份前后未改变。
- 最新的 `bot/risk.py`、`bot/main.py`、`bot/store.py`、`server/dashboard.py` 已包括 BTC 单品种日亏损检查、禁止新开仓与次日恢复相关代码。此处仅备份，不更改策略或执行新的交易。
- `backup-manifest.json`、`database-manifest.json`、`frontend-manifest.json`、`source-manifest.json` 和 `CHECKSUMS.sha256` 提供采集与哈希校验信息。

## 保密与恢复

原始 `.env`、历史凭证和运行记录仅保存在加密归档；公开配置 `environment.redacted` 只保留名称，不保留值。恢复密钥不进入 GitHub。
公开副本中的私有文件/脱敏文件清单见 `private-only-paths.json`、`redacted-source-paths.json`。

加密格式：AES-256-CBC + PBKDF2-SHA256（200000 轮），加独立派生的 HMAC-SHA256 密文认证。
`restore_archive.py` 先验证认证标签，再解密；不要跳过认证。

恢复密钥保存在服务器：

`/home/ec2-user/backups/polyauto-261022-loss-circuit/private/restore.key`

本机独立副本（不在 Git 仓库中）：

`C:\Users\Administrator\poly-backup-keys\261022\restore.key`

先运行 `git lfs pull` 获取归档实体，再在本目录核对 `CHECKSUMS.sha256`，执行：

```sh
python restore_archive.py --key /secure/restore.key --output /restore/polyauto.tar.gz
```

解压到新的空暂存目录核验，禁止直接覆盖正在运行的数据库、前端或凭证。真正恢复数据库前，应停止相关写入服务。
恢复时默认不启动交易服务，人工检查 Paper/Live 配置后再启动；历史 PID、缓存和 `bot.mode` 不代表实盘授权。
跨主机恢复应按依赖锁文件重建虚拟环境。备份过程没有重启服务或改变实盘开关。
