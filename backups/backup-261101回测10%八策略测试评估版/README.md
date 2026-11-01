# 261101回测10%八策略测试评估版

服务器 `18.179.50.168`、域名 `polyauto.hustle2026.xyz` 的当前运行备份，采集于 2026-11-01。

## 内容

- `server-auto/polymarketbot-auto/`：当前应用的可审阅后端、策略、脚本、测试、Agent、UI 源码和可恢复的前端 `dist` 资源；活动 BTC release 为 `releases/c-paper-profit-20261024`。
- `paper-shadow/`：当前目录中仍保留的 Paper 影子程序和源代码。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 实际对外网站静态文件，包含前端 JS、CSS、图片、音频等资源。
- `ops/`：脱敏的 systemd、Nginx 和运行状态信息。
- `database-manifest.json`：服务器端 SQLite 快照的来源、大小、SHA-256、表计数和 `quick_check` 元数据；数据库内容不提交到此分支。

公开目录不包含明文 `.env`、钱包私钥、CLOB/LLM 密钥、控制令牌、TLS 私钥或 SQLite 数据库内容。数据库只保留审计元数据，不在此提交。

## 恢复

数据库恢复材料不在此分支。需要数据库时，必须从服务器受控备份路径另行取回，不得从 Git 历史恢复。

先核对 `backup-manifest.json`、`database-manifest.json` 和 `CHECKSUMS.sha256`；恢复程序、前端或配置前保持 Paper/Live 开关关闭，重新创建独立路径和权限。

## 当前运行记录

- BTC Paper 服务：`polymarket-auto-btc-paper.service`，主进程 PID 458255；未执行重启。
- Dashboard：`polymarket-auto-dashboard.service`，主进程 PID 466277；未执行重启。
- 实际 BTC 源码路径：`/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024`。
- 生产账本：`/home/ec2-user/polymarketbot-auto/trades-auto.db`，仅以一致性快照形式保存。

备份操作没有清理、修改、切换策略或重启任何生产服务。Git 树中的源程序和前端资源用于审阅；数据库及敏感原件不属于本次 Git 提交。
