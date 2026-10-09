# 261009OPENCLAW 四产品修正版备份

备份时间：2026-10-09 UTC  
来源服务器：DexCexMix-D-test（18.179.50.168）  
域名：`polyauto.hustle2026.xyz`

本目录保存本次 polyauto 四产品版本的可恢复备份：

- `server-auto/polymarketbot-auto/`：后端、策略、OpenClaw agents、脚本、测试、文档、前端源码和两个 `ui/dist` 构建目录。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 当前实际发布的完整静态目录，包含历史 hash 资源、OpenClaw 图片、视频和 favicon。
- `database/`：运行中 SQLite 数据库的一致性快照；快照通过 SQLite online backup 生成，已包含 WAL 中的已提交数据。
- `database/sidecars/`：备份时服务器上的原始 WAL/SHM 伴随文件，仅用于追溯，不作为恢复时的首选数据源。
- `ops/`：polyauto 的 Nginx 配置和 systemd 单元/覆写配置。

安全处理：服务器 `.env`、历史 `.env.*`、钱包私钥、API 密钥和证书私钥均未提交到 GitHub；备份中保留了 `EnvironmentFile` 路径和 `.env.example`，恢复时需在服务器重新配置密钥。`.venv`、`node_modules`、Python 缓存、运行日志和 PID 文件未提交；所有前端 `dist` 目录均已保留。

数据库文件超过 GitHub 普通单文件限制，数据库路径使用 Git LFS 跟踪。恢复 `trades-auto.snapshot.db` 或 `p0-shadow-btc.snapshot.db` 时，应先停止对应服务，再将快照复制为目标数据库文件。

备注：`261009OPENCLAW四产品修正版`
