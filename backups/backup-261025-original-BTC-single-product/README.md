# 261025 原始 BTC 单产品初版

来源：PolyDextest（实例 i-058a2591186a61b31）。快照创建时实例原地址 35.78.246.81 已释放，启动后 AWS 分配临时地址 18.177.149.23；DNS 当时仍指向 18.179.50.168。

内容：

- `source/poly-dex-test-source.tar.gz`：`/opt/poly-dex-test` 当前前后端源程序及 `ui/dist` 构建产物，排除 node_modules、历史 ops-backups、缓存和 Python 字节码。
- `database/poly-dex-test-database.tar.gz`：`/var/lib/poly-dex-test` 的 P1 crypto、P2/P3 和 Paper feeds SQLite 数据库。
- `deployment/poly-dex-test-services.tar.gz`：PolyDex systemd 服务和 Nginx 配置片段。
- `SHA256SUMS`：快照文件校验值。

出于安全原因，未备份 `.env`、私钥、API 密钥、证书私钥和其他凭据；前端 dist 未删除并已包含在源程序归档中。

此备份对应用户备注：`261025原始BTC单产品初版`。
