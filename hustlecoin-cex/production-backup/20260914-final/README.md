# 20260914最终完成版

本目录为 2026-09-14 生产快照（不含行情采集数据）。

- `rust-engine/`：coinRust 交易服务器 57.181.214.206 当前源代码（src、Cargo.toml、Cargo.lock）。
- 上级仓库 `frontend/`、`frontend-admin/`：用户端与管理端全部前端源程序；`python-business/static/`：构建后的 dist/static 资源。
- 上级仓库 `python-business/`：Python 后端全部源程序。
- `cex_trading-config-20260914.dump`：生产 PostgreSQL 配置与业务数据快照；行情采集表未纳入本快照。
- 服务器：coinRust 57.181.214.206；coinPython 18.176.76.127。
