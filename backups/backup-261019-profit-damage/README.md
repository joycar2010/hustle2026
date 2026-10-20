# 261019收益破损版（polyauto 当前版本备份）

备份时间：2026-10-19 UTC  
来源服务器：DexCexMix-D-test（18.179.50.168）  
域名：`polyauto.hustle2026.xyz`  
Git 提交备注：`261019收益破损版`

本目录是执行还原前的完整可回滚快照，保存当前线上版本，用于后续与 `31e693b`（`260919OpenClawAuto四产品调试初版`）逐项比较。此次仅备份，不包含任何恢复或代码切换操作。

目录说明：

- `server-auto/polymarketbot-auto/`：当前服务器的后端、策略、OpenClaw agents、脚本、测试、文档、前端源码及两个 `ui/dist` 构建目录。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 当前实际发布的静态资源，包括页面、hash 资源、OpenClaw 图片、视频和 favicon。
- `database/`：通过 SQLite online backup 生成的一致性快照，包含 WAL 中已提交的数据。
- `database/sidecars/`：备份时服务器上的 `trades-auto` WAL/SHM 原始伴随文件，仅供追溯。
- `ops/`：当前 Nginx 配置及 polyauto 的 systemd 服务单元和 Paper 覆盖配置。

安全处理：服务器 `.env`、历史 `.env.*`、钱包私钥、API 密钥、证书私钥、`.venv`、运行日志和 PID 文件未提交。所有前端 `dist` 目录均已保留。数据库快照使用 Git LFS 跟踪。

源文件快照校验：远程文件与本地备份的 SHA-256 已逐项核对；详见 `CHECKSUMS.sha256`。
