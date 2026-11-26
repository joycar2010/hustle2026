# SOL5M isolated Paper release

This directory is a standalone SOL Up/Down 5-minute release.  It uses the
audited `btc5m` engine implementation with an explicit SOL profile, separate
database (`data/paper_sol5m.db`), market discovery prefix, signal venues and
book cache namespace.  The BTC worker checkout and its `live.db` are not read.

## Paper smoke

```bash
cp .env.example .env
bash scripts/run_sol_paper.sh --once
bash scripts/run_sol_api.sh
curl http://127.0.0.1:8095/api/health
```

The API also exposes `/api/profile`, `/api/market`, `/api/ws/status` and a
read-only `/ws` heartbeat channel.  Market and signal calls may be unavailable
when the Gamma/venue APIs are offline; this leaves the Paper worker idle and
does not place orders.

## Services

`services/sol5m-paper.service` is the normal Paper unit.  The
`sol5m-production.service` file is a production-shaped template for deployment
review; it deliberately runs the Paper entry point with both `LIVE=false` and
`LIVE_TRADING_ENABLED=false`.  `sol5m-api.service` serves the read-only API.

## Live safety

The release has no live command.  `sol5m.runner.paper_config()` rejects a live
environment and the service templates set both safety flags to `false`.  Do not
reuse BTC credentials or database paths in this release.

