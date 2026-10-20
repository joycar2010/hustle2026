# polyauto 备份：2601020收益修复版

本目录是服务器 `18.179.50.168` 上 `polyauto.hustle2026.xyz` 的脱敏归档，备份标签为 **2601020收益修复版**。

## 归档范围

- `server-auto/polymarketbot-auto/`：后端、策略、Agent、脚本、测试、前端源代码和项目文档。
- `server-auto/polymarketbot-auto/ui/dist/`：服务器当前构建产物。
- `web-roots/polyauto.hustle2026.xyz/`：Nginx 实际对外静态根目录完整副本。
- `ops/`：Nginx 与 systemd 服务配置副本。
- `database/`：使用 SQLite online backup 生成的一致性快照，包含 Paper/交易台账数据库。
- `incoming/`：脱敏后的源码、dist、web root 和服务配置压缩包。
- `CHECKSUMS.sha256`：归档文件 SHA-256 校验值。

## 安全边界

真实 `.env`、历史 `.env.before-*`、钱包私钥、CLOB API 凭证、LLM API 密钥、虚拟环境、依赖目录、日志、PID 和缓存均未纳入归档。仅保留不含真实凭证的 `bot/.env.example`。数据库快照可能包含交易记录和市场数据，按敏感数据处理。

## 数据库校验

四个 SQLite 快照均已执行 `PRAGMA quick_check`，结果为 `ok`。恢复时应先停止写入服务，将目标数据库复制到独立目录，再按服务配置设置路径；不要覆盖正在运行的生产数据库。

## 来源与时间

- 来源主机：`18.179.50.168`
- 域名：`polyauto.hustle2026.xyz`
- Git 分支：`poly`
- 备份标签：`2601020收益修复版`

