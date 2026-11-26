# PolyDexTest P0→P3 隔离测试方案

## P0：基础设施与安全边界

* 独立 EC2 实例、独立安全组、独立磁盘和独立 systemd 服务。
* 仅开放 SSH/HTTP/HTTPS；测试服务默认 Paper-only。
* 新实例不复制生产 `.env`、钱包私钥、L2 CLOB 凭证、数据库、WAL/SHM、虚拟环境和历史运行状态。
* `p0_audit.py` 作为部署前检查；P1 服务使用最小文件系统权限并写入 `/var/lib/poly-dex-test`。

## P1：加密资产 Paper 接入（本次执行）

* 公共 Gamma API 发现 SOL、XRP、DOGE、BNB 的 5 分钟 Up/Down 市场；ADA、AVAX、LTC、LINK、SUI、NEAR、AAVE、UNI 保留在配置中，市场不存在时记录为 0，不报错中止。
* 公共 CLOB `/book` 读取订单簿，不使用钱包和 L2 凭证。
* 基线策略只在剩余 30–270 秒、可执行报价、价格折价和流动性条件同时满足时创建 Paper 买入；每资产独立敞口和仓位上限。
* 决策、报价、模拟订单写入独立 SQLite；快照写入 `/var/lib/poly-dex-test/p1/state.json`。
* 结算只使用 Gamma 的公开已结算结果；未解析市场保持 OPEN，不推算输赢。

## P2：量化与风控增强

* 已部署 `poly-dex-p2-p3.service`，计算二元概率点绝对波动率、盘口点差、可见深度、跨资产相关性，并校验公开结算源。
* P1 买入门禁已接入 P2 风险快照、可见深度 VWAP/150bps 滑点上限、相关敞口上限和 Chainlink 解析源校验。
* 风险结果写入 `/var/lib/poly-dex-test/p2-p3/risk.json` 和独立 SQLite；未解析市场保持 OPEN。
* 至少积累 48 小时 Paper 记录，并通过胜率、净 PnL、最大回撤、部分成交和断线恢复验收。

## P3：扩展资产与上线门禁

* 已部署 P3 资产注册表和 Gamma 分页发现器，覆盖加密资产、指数、股票和商品类别。
* 未完成资产级概率模型和结算规则的市场只记录为 `PAPER_WATCH`，不会创建订单；所有新增资产默认 Paper。
* 只有资产级审计、人工批准和独立 live gate 通过后才允许实盘。
* 任何实盘迁移必须与现有 PolyDEX 实例的钱包、CLOB 凭证和策略进程隔离，禁止重复下单。

## 控制台与 TLS

* 只读控制台绑定 `127.0.0.1:8787`，由 Nginx 反代至 `polytest.hustle2026.xyz`。
* Let's Encrypt 证书由 Certbot 管理，HTTP 自动跳转 HTTPS，续期定时器已启用。
