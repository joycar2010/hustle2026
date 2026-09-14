## COIN-REG-20260914-UID - Per-user UID weight isolation

- Status: Implemented; focused regression tests pass.
- Root cause: `/api/engine/health` read the process-wide `engine:uid_weight:latest` max snapshot. A user with no bound sub-account could therefore see another user's (for example lxy) Binance UID weight.
- Fix: select only enabled `SubAccount.id` values owned by the authenticated `user_id` from `engine:uid_weight:by_account`; never fall back to the global snapshot. Users without a bound account receive `uid_scope_available=false`, zero usage/limit, and the dashboard displays `UID unavailable (no bound account)`.
- Verification: `tests/test_uid_weight_isolation.py` (3 passed); Python compilation passed. The test covers no-account isolation, owned-account selection, stale-window reset, and malformed Redis payload safety.
- Safety: this change only affects health telemetry and throttling display; it does not issue Binance requests or change account balances.

## COIN-REG-20260913-FUNDS - Platform position and PNL totals

- Status: Deployed to production at 2026-09-13T19:16Z; business service healthy.
- Root cause: the funds overview endpoint only aggregated Redis wallet snapshots and did not expose position-ledger totals, so realized PNL, active position notional, and close counts were absent from the admin cards.
- Fix: aggregate non-terminal ledger positions by owner, calculate realized net PNL with funding and interest, count all CLOSED rows including NULL realized PNL, and return `total_position_notional`, `total_pnl`, `total_closed`, `today_pnl`, and `today_closed`. The admin UI now renders the three requested totals and shows today's values in the card hints.
- Production read-only verification: `total_position_notional=0`, `total_pnl=-4.23`, `total_closed=55`, `today_pnl=-0.46`, `today_closed=4`.
- Verification: position metrics test passed, Python compilation passed, admin `tsc`/Vite build passed. Production backups: `/home/ec2-user/coin-backups/pnl-metrics-20260913T191627Z` and `/home/ec2-user/coin-backups/pnl-metrics-closed-20260913T192006Z`.

## COIN-REG-20260914-SYSTEM - Git history, operations monitor, and admin AI

- Git history now resolves the monorepo root and reads `origin/coin`, while version probes are isolated from the page load and remote checks run concurrently.
- Added read-only Rust/Python host telemetry, persistent per-user Rust/Python failure notification bindings, and an idempotent `server_fault` notification template.
- The admin AI assistant keeps its `coinadmin` conversation/FAQ scope and falls back to the enabled `coin` provider configuration when no usable admin provider is configured.
- Production verification: `/api/admin/system/versions`, `/api/admin/system/monitoring`, and `/api/admin/system/monitoring/subscriptions` return 200; `cex-business.service` is active. Rust host `57.181.214.20` is unreachable and `57.181.214.206` currently lacks an SSH route/key from the business host, so its telemetry is explicitly marked unavailable.
