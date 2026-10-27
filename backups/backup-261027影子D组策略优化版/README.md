# 261027影子D组策略优化版

服务器 `18.179.50.168`、域名 `polyauto.hustle2026.xyz` 的完整应用备份。此次备份不切换策略、不重置账本，不停用或重启服务。

## 内容

- `server-auto/polymarketbot-auto/`：可查阅的前后端源码、脚本、测试、OpenClaw / agents、实际生产 release，以及全部可公开保存的 dist 原件。
- `paper-shadow/`：当前 `20261026T110000Z` A/B/C/D 与旧 `20261022T020933Z` A/B/C 的程序和源码。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 当前真正使用的前端，含旧哈希 JS/CSS、图片、音乐和视频。恢复当前 UI 应以此目录为准，不能直接拿应用 ui/dist 覆盖。
- `ops/`：相关 systemd unit/timer/drop-in、Nginx 和部署信息。
- `poly-complete.tar.gz.enc`：Git LFS 完整加密归档，包括上述三个原始目录、依赖、日志、历史文件、所有 dist、精确原配置、13 个 SQLite 一致性快照，以及该域名 TLS 证书和私钥。

可查阅树是脱敏副本；原始 `.env`、数据库、密码、钱包及 API 密钥只在加密归档内。恢复密钥独立保管，不上传 GitHub。`environment.redacted` 仅列配置名称，不代表实际运行参数。

`database-manifest.json` 记录每个数据库的归档路径、表行数、大小、SHA-256、快照时间和完整性检查结果；包括特殊 `.db.bak-*` 文件。SQLite Backup API 合并已提交 WAL，以只读事务固定各库快照；各数据库不构成同一时刻的跨库事务。恢复不需要旧 WAL/SHM。

## 当前版本

生产 BTC 为 Paper，实盘关闭。实际执行目录仍是：

`/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024`

目录中的 C 是历史路径名；生产已经同步 D 组参数：价格 0.84–0.90、剩余 90–150 秒入场、止损回撤 30% / 确认 2 次、止损监控窗口 150 秒、$100 模拟本金、单笔风险比例 2%。生产日亏损熔断关闭，日止盈 10%。根目录 `bot/main.py` 不能代替实际 release 执行文件。

生产数据库为根 `trades-auto.db`。当前四个影子各自使用 `paper-ab/20261026T110000Z/{A,B,C,D}/ab.db`，全部 Paper，日亏损 1%、日止盈 12%。各组入场和止损差异保留。达标后暂停新开仓至北京时间次日零时，持仓退出及结算继续运行。D 组此前的 6% 止盈锁已归档，不应在恢复时额外恢复成旧门槛。

## 完整性

- 每个 SQLite 一致性快照执行 quick_check。
- 完整加密归档经过解密读取，逐项检查文件内容、大小、权限、属主和符号链接。
- `frontend-manifest.json` 列出所有 dist 和真实网站文件；采集前后字节 SHA-256 一致，归档内容一致。没有清空、构建或删除服务器 dist。
- `frontend-private-only.json` 标识因路径兼容性或敏感内容只能保留加密原件的文件；若为空，所有前端原件也在可查阅树中。
- 持久服务状态及 PID 前后一致。定时 Agent 的自然运行/结束另行记录。
- `CHECKSUMS.sha256` 覆盖公开备份；发布前执行凭证扫描，密文具有独立 HMAC 完整性认证。

## 恢复

独立密钥位置（文件内容不进入仓库）：

- 服务器：`/home/ec2-user/backups/polyauto-261027-shadow-d/private/restore.key`
- 本机：`C:\Users\Administrator\poly-backup-keys\261027\restore.key`

先执行 `git lfs pull`，核对校验和，然后认证、解密：

```sh
python restore_archive.py --key /secure/restore.key --verify-only
python restore_archive.py --key /secure/restore.key --output /restore/poly-complete.tar.gz
```

采用 AES-256-CBC、PBKDF2-SHA256（200000 次）和独立派生的 HMAC-SHA256，先认证再解密。脚本拒绝覆盖既有输出，不解压或启动服务。

在 Linux 空暂存目录中检查解压结果。历史中存在 Windows 不兼容的目录名，原件保留于密文。实际恢复需处理原属主/权限、独立数据库路径、Paper/Live 开关；不得直接覆盖运行中的数据库、前端、证书或 `.env`。旧 PID 和心跳不代表恢复后应开启实盘。

业务环境为 Amazon Linux 2023、Python 3.11.15、Node 22.22.3。venv 的 Python 链接指向 `/usr/bin/python3.11`；跨主机应按锁文件重建依赖。TLS live/archive/renewal 文件已保存，系统软件包与 Certbot ACME 账户不属于应用范围，迁机需验证续期环境。
