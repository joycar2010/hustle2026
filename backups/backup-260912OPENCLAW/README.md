# 260912OPENCLAW 初版备份

备份时间：2026-09-12 UTC  
来源服务器：DexCexMix-D-test（18.179.50.168）

本目录保存两个域名当前运行版本的前端、后端、源程序、静态发布文件和数据库快照：

- `server-main/polymarketbot/`：`poly.hustle2026.xyz` 主实例，包含后端、前端源代码、`ui/dist`、策略脚本、测试和 `trades.db`。
- `server-auto/polymarketbot-auto/`：`polyauto.hustle2026.xyz` 隔离实例，包含 OpenClaw、BTC/ETH/天气/体育服务、前端源代码、两个 `ui/dist`、静态素材和 `trades-auto.db` 及其 WAL/SHM 文件。
- `web-roots/`：Nginx 实际提供的两个域名静态目录，保留全部历史哈希资源、图片、视频和当前 `dist` 产物。
- `ops/`：两个域名的 Nginx 配置和相关 systemd 服务单元。
- `database/`：通过 SQLite 在线一致性备份生成的数据库快照。运行中的 WAL 数据已合并到快照中。

为保护实盘账户，服务器上的 `.env`、历史 `.env.*`、私钥、API 密钥和证书私钥没有提交到 GitHub；这些文件仍保留在服务器原位置。构建依赖目录（`.venv`、`node_modules`）、运行日志、Python 缓存和旧部署备份也没有提交。所有前端 `ui/dist` 和线上静态资源均已保留。

提交备注：`260912OPENCLAW初版`
