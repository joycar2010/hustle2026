# 2601021收益完整版

服务器 `18.179.50.168`、域名 `polyauto.hustle2026.xyz` 的当前部署备份。
采集时间、文件数、数据库检查结果和哈希见本目录清单。

## 内容

- `server-auto/polymarketbot-auto/`：可查阅的前后端源码、策略、Agent、脚本、测试、所有应用 dist、历史代码副本；`environment.redacted` 仅保留环境配置名，原值在加密归档中。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 实际对外静态目录完整副本，包括图片、音频和历史哈希资源。没有重新构建或删除线上 dist。
- `ops/`：polyauto systemd unit、drop-in、Nginx 配置。
- 数据库：SQLite Backup API 生成的快照，已合并已提交 WAL 数据；为保护交易及运行记录，全部收录在完整加密归档的原始相对路径中，不上传明文数据库。所有快照均通过 `PRAGMA quick_check`。逐库一致，不宣称跨库同一时刻事务快照。
- `polyauto-complete.tar.gz.enc`：完整加密归档，包含原始应用目录（含 `.env` 及历史配置、依赖、日志、缓存、程序和源码）、实际 web root、部署配置及一致性数据库快照。SQLite WAL/SHM 不复制，恢复以快照为准。
- `frontend-manifest.json`：每个应用 dist 和 web root 的 SHA-256 清单；采集前后及备份文件逐项比对。
- `source-manifest.json`、`database-manifest.json`、`backup-manifest.json`：文件及采集校验信息。
- `services-before.txt`、`services-after.txt`：备份前后服务状态。
- `CHECKSUMS.sha256`：本次发布文件校验清单。

## 凭证与恢复

GitHub 不保存明文私钥、CLOB/LLM API 密钥、实盘令牌或恢复密钥。
确需保留的原始敏感文件全部位于加密归档。可查阅副本中的脱敏文件/私有文件名单分别见
`redacted-source-paths.json` 和 `private-only-paths.json`；完整版本以加密归档为准。

加密使用 AES-256-CBC + PBKDF2-SHA256（200000 轮），并使用独立派生的 HMAC-SHA256 对密文认证。
恢复工具先验证认证标签，再解密。请勿仅凭未认证的解密结果恢复交易系统。

服务器恢复密钥路径：
`/home/ec2-user/backups/polyauto-2601021-complete/private/restore.key`

本机离线副本路径（不在 Git 仓库中）：
`C:\Users\Administrator\poly-backup-keys\2601021\restore.key`

恢复前运行 `git lfs pull` 获取归档实体，校验 `CHECKSUMS.sha256`，然后执行：

```sh
python restore_archive.py --key /secure/restore.key --output /restore/polyauto.tar.gz
```

将 tar 解压至新的暂存目录进行验证，不直接覆盖正在运行的数据库、前端或凭证。
数据库恢复应先停止相关写入进程；恢复期间默认禁用交易服务，核验 Paper/Live 配置后再手动启动。
PID 文件、缓存和 `bot.mode` 是历史运行记录，不代表恢复后已获准启动实盘。
虚拟环境包含原服务器绝对路径和系统依赖，跨服务器恢复应按锁文件重建依赖。

此备份仅新增归档，不变更 BTC 策略、模型配置、服务启停或历史 Git 提交。
天气和体育服务的停止/禁用状态在服务清单中保留。
