# 261101回测10%八策略测试评估版

服务器 `18.179.50.168`、域名 `polyauto.hustle2026.xyz` 的当前运行备份，采集于 2026-11-01。

## 内容

- `server-auto/polymarketbot-auto/`：当前应用的可审阅后端、策略、脚本、测试、Agent、UI 源码和可恢复的前端 `dist` 资源；活动 BTC release 为 `releases/c-paper-profit-20261024`。
- `paper-shadow/`：当前目录中仍保留的 Paper 影子程序和源代码。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 实际对外网站静态文件，包含前端 JS、CSS、图片、音频等资源。
- `ops/`：脱敏的 systemd、Nginx 和运行状态信息。
- `database-manifest.json`：18 个 SQLite 一致性快照的来源、大小、SHA-256、表计数和 `quick_check` 结果。
- `poly-complete.tar.gz.enc`：AES-256-CBC/PBKDF2-SHA256（200000 轮）加密归档，包含原始环境文件、程序、数据库快照和部署所需的敏感文件。加密归档已经在服务器上完成解密回读校验。

公开目录不包含明文 `.env`、钱包私钥、CLOB/LLM 密钥、控制令牌、TLS 私钥或明文 SQLite 数据库；这些原件只在加密归档中。加密归档的 HMAC 文件用于恢复前完整性认证。

## 恢复

恢复密钥不在 Git 仓库中：

- 服务器：`/home/ec2-user/backups/polyauto-261101-backtest-10pct-eight-strategy/private/restore.key`
- 本机安全目录：`C:\Users\Administrator\poly-backup-keys\261101\restore.key`

先在空的临时目录中验证，不要直接覆盖运行中的应用：

```sh
python restore_archive.py --key C:\secure\restore.key --verify-only
python restore_archive.py --key C:\secure\restore.key --output C:\restore\polyauto-261101.tar.gz
```

解密归档后，先核对 `backup-manifest.json`、`database-manifest.json` 和 `CHECKSUMS.sha256`。恢复数据库前必须停止对应写入进程，保持 Paper/Live 开关关闭，重新创建独立路径和权限。

## 当前运行记录

- BTC Paper 服务：`polymarket-auto-btc-paper.service`，主进程 PID 458255；未执行重启。
- Dashboard：`polymarket-auto-dashboard.service`，主进程 PID 466277；未执行重启。
- 实际 BTC 源码路径：`/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024`。
- 生产账本：`/home/ec2-user/polymarketbot-auto/trades-auto.db`，仅以一致性快照形式保存。

备份操作没有清理、修改、切换策略或重启任何生产服务。Git 树中的源程序和前端资源用于审阅，完整敏感原件以加密归档为准。
