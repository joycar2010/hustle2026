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

## COIN-REG-20260914-LOGO - Browser icon must match the Dashboard logo

- Status: Deployed on 2026-09-14 at 06:38:41 UTC; public verification passed.
- Root cause: the browser entry referenced the purple lightning `/favicon.svg`, while the Dashboard `OwlTopBar.tsx` uses `/assets/logo.png`. Commit `51ed8d7` added the old favicon reference in the retained history. Earlier history was pruned, so this identifies the current introduction point without claiming an unverified earlier fix.
- Fix: favicon, Apple touch icon, and manifest icons now use `/assets/logo.png?v=6416fcb061b9`, the exact Dashboard asset. PNG SHA-256: `6416fcb061b97032cad717fd7ba5ea2a6161b0b42b2f395d00a9e477b1044825`. The manifest URL is versioned as well to refresh browser caches.
- Regression protection: `frontend/scripts/check-branding.mjs` checks source references and Logo content version before every `npm run build`. It can also validate a Vite output directory before deployment. Changing the Dashboard logo requires updating all icon references and cache versions together. Reintroducing `/favicon.svg` fails this check. `emptyOutDir: false` preserves existing static assets during later builds.
- Verification: `npm ci`, TypeScript/Vite build into a separate staging directory, source/artifact branding checks, and a negative check with the retired favicon all passed. Production `/dashboard`, `/login`, versioned PNG, manifest, and the five entry JS/CSS assets returned 200. The PNG content hash matches the Dashboard asset; user HTML uses `no-cache, no-store, must-revalidate`. Admin login also returned 200.
- Deployment: updated production source and icon metadata under `/home/ec2-user/coin-project`; retained the existing JavaScript/CSS bundles. All 38 other existing SPA files retained their hashes and no static files were removed. Business service remained active without a restart. Production HTML SHA-256: `392b3d12085f5361b832577a442524f0f5a1ffc49607c84d0923a82f5162cfc5`.
- Rollback backup: `/home/ec2-user/coin-backups/logo-20260914T063841Z/before.tar.gz` contains the complete previous user SPA and affected source/config files. Local release and verification evidence: `D:/Dev/MixCodex/ops/coin-logo-20260914/`. No account, database, or trading operations were performed.
- Release rule: commit source and this ledger together to the current `coin` branch; validate any rebuilt artifact before publishing. Preserve existing `dist`/SPA directories and do not restore the retired favicon from historical backups. Existing Git history before 2026-07-10 must not be reintroduced.
## COIN-REG-20260914-AUTOTRANSFER - Master-to-subaccount margin safety and inheritance

- Status: Code and UI updated; production deployment verified on 2026-09-14.
- Root cause: `hedge_via_master` and user-level FundRules were configured, but blank subaccount `single_transfer_amount` values caused `margin_balancer` to return before evaluating the common rule. The five production subaccounts therefore never attempted automatic top-ups.
- Policy: subaccount single rule overrides the user common fund rule; a blank common value falls back to the system default (`500 USDT` transfer chunk, `1.5` margin-level threshold). Subaccount `min_balance` remains explicit and is not confused with the master's reserve.
- Safety: master balance reads/transfers are serialized per shared master client. The configured master reserve is retained globally, and at least the same reserve is retained in the master futures wallet before any futures-to-subaccount transfer. This protects the shared one-way futures hedge leg; spot/margin surplus can still be used first according to the configured source order.
- Verification: four focused tests cover override, inheritance, defaults, and preservation of the futures reserve; Python compilation passed. No real Binance transfer was issued during testing.
- Deployment rule: after rollout, verify worker logs and read-only balances. A transfer is allowed only when `hedge_via_master=true`, the subaccount `marginLevel` is below its effective threshold (or its margin free balance is below an explicitly set floor), the master client is available in one-way mode, and the post-transfer master reserves remain sufficient.
- Runtime compatibility: the production orchestrator had the newer `Worker(..., user_id=...)` call while the worker constructor still accepted only three arguments, causing repeated worker crashes after restart. The worker now accepts the optional owner ID and still confirms it from the account row; this keeps rolling deployments compatible and lets the margin-balancer loop actually run.
## COIN-REG-20260914-STUCK-POSITION - Retryable repayment claims and console threshold

- Status: Deployed and production-verified on 2026-09-14.
- Root cause: `execute_repay` changes a position to the transient CAS state `REPAYING`. Its generic exception path previously persisted only `error_message`, leaving the row in a state that the worker never consumed again. The admin console also classified every short-lived execution state as stuck.
- Fix: generic repayment failures now return the row to `PENDING_REPAY`, increment `retry_count`, and write a failed repayment trade log. Workers reclaim abandoned `REPAYING` claims older than five minutes before loading pending repayments. Admin health endpoints report execution states as stuck only after ten minutes, matching the notification threshold.
- Production proof: business and worker services are active after deployment. Read-only position query immediately after rollout reported `CLOSED=57`, `FAILED=10448`, and no `PENDING_BORROW`, `REPAYING`, or other in-flight stuck rows. No database rows were manually changed and no borrow/order/repay/close request was issued for verification.
- Rollback backup: `/home/ec2-user/coin-backups/stuck-position-20260914T105520Z/before.tar.gz`.
