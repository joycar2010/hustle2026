## COIN-REG-20260918-PUSH-VANISH - Manual push re-arms 禁移禁还 protection

- Symptom: POST `/api/engine/push-symbol/{symbol}` returned 200 and the dashboard showed the「已推送」toast, but the slot row never appeared (FILUSDT/SLPUSDT, user lxy). Worker logs show `Auto-removed FILUSDT: remove_spread` 187ms after the push (13:22:57 push → 13:22:57,187 removal; reproduced again at 16:25:31 and 16:26:17-24 UTC).
- Root cause: the 20260918 manual-push protection is bypassed when a persisted single-symbol rule has `source='custom'` and `allow_remove=True`. Both `symbol_rules.allow_remove/allow_repay` carry `server_default='true'`, and the rule dialog re-sends the loaded truthy values on any save (e.g. editing only 借币金额), so an「explicit opt-in」was persisted that the user never chose. With the live spread below the effective remove line, the Worker removed the freshly pushed slot within its next cycle.
- Fix (backend only, no SPA change): (1) `push_symbol` calls `rearm_manual_push_protection` before writing list membership: explicit `True` values of `allow_remove/allow_repay` on the user's `SymbolRule` and `AccountSymbolRule` rows for that symbol are reset to `False` (NULL/inherit untouched), committed, and `rules:reload:{uid}` is published — a manual push is the latest explicit intent and defaults to 禁移禁还, matching the documented policy; a later explicit single-symbol save still re-enables removal/repayment. (2) `Worker._maybe_auto_remove` confirms the bypass against the CURRENT persisted rules via the shared `explicit_rule_optin_persisted` (extracted from `manual_push_operation_allowed`, one policy source for HTTP and Worker) before removing a manual-marked symbol; DB read failure keeps the symbol protected. Ordering makes the race impossible: the flag reset commits before the Redis list add, and the Worker can only observe the symbol after the add, so its confirming DB read sees the reset even if its in-memory rule snapshot is stale.
- Preserved behavior: safety exits (`blacklist`, `not_tradable`, `market_feed_stale`) unchanged; automatic pushes (no manual marker) keep the low-spread lifecycle; `removed_cooldown`, ordered queue semantics, hysteresis conflict validation, and the DELETE-endpoint policy are untouched.
- Verification: 9 new focused tests in `tests/test_manual_push_rearm.py` (re-arm on both rule layers, NULL preservation, opt-in blocked after re-arm, account-level opt-in, Worker keeps symbol on stale snapshot / DB failure / non-custom rule, and short-circuits before taking the borrow transition lock); full suite passes. No borrow/order/repay/transfer was issued during verification.
- Regression rule: a manual push must always re-arm 禁移禁还 regardless of previously persisted rule flags, and any Worker removal of a manual-marked symbol must be confirmed against the persisted opt-in at decision time, never against the in-memory snapshot alone.

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

## COIN-REG-20260914-ROLLBACK-GUARDS - Pushed-slot order, inventory rate, and low-spread lifecycle

- Status: Deployed to production on 2026-09-14T13:40Z after restoring the complete 5039-line worker/API bundle; business and worker services are active.
- Root causes: a regression converted the pushed-symbol queue through `set/sorted`, the dashboard reused the independent borrow-submit rate (`2.00/s`) for inventory reads, and the compact worker had no low-spread pushed-list lifecycle gate.
- Fix: Redis pushed symbols remain an insertion-ordered list across manual push, automatic push, confirmation, close cleanup, and removal; the dashboard uses that list index for slot ordering. Inventory polling has separate global/per-sub-account `inventory_probe_rate_per_sec` settings and health telemetry, with account overrides inheriting the user global value (default `3.8/s`). Automatic pushes are tagged `auto` and are removed when fresh spread is below the effective `remove_spread`; manual and legacy untagged pushes remain protected, active positions are never removed, and `allow_remove=false` keeps the symbol.
- Migration: `aa99bb00cc11_inventory_probe_rates` is idempotent because production already contains these columns on some installations.
- Regression rule: never deploy the shortened historical worker over the complete worker; preserve ordered queue semantics, the separate inventory rate field, and automatic/manual push origin markers in every future worker change.
- Production backup: `/home/ec2-user/coin-backups/rollback-guards-20260914T125010Z/before.tar.gz`. The migration command was skipped after the production database rejected the repository's default `postgres` password; read-only runtime checks confirmed the existing inventory-rate columns and the application started normally.

### Follow-up: supported Binance transfer route

- Status: Deployed to production on 2026-09-14 at 14:22 UTC; worker active and balances verified read-only.
- Root cause confirmed in production: Binance returns `-9000 Unsupported operation` for direct `USDT_FUTURE -> sub-account MARGIN` universal transfers. Rules and balances were valid (`hedge_via_master=true`, master futures available about `1982.83 USDT`, child margin free balances below their `300/200 USDT` floors).
- Fix: when the configured source is the master futures wallet, first use the supported internal `UMFUTURE_MAIN` transfer into the master spot wallet, then call `SPOT -> MARGIN` universal transfer to the child. The futures reserve remains excluded from the source budget, and per-user transfer locking is unchanged. Transfer failures now emit the source, amount, target, and Binance error for diagnosis.
- Verification: five focused margin-balancer tests pass; Python compilation passes. After restart, read-only balances were approximately `linxiaoyun01=299.995`, `02=199.996`, `03=199.997`, `04=200.000`, `05=199.998 USDT`; master futures available was `500.010 USDT`, preserving the configured 500U reserve. Worker logs recorded successful top-ups for all five accounts. No manual transfer test was issued; only the configured automatic worker path ran.
- Rollback backup: `/home/ec2-user/coin-backups/autotransfer-route-20260914T142134Z/margin_balancer.py`.

### Follow-up: reserve gate and spot repatriation

- Status: Ready for production rollout after focused tests pass.
- Correction: `base_margin_amount` is a minimum gate for the master futures wallet. It must not force the master to keep exactly that amount in futures while leaving additional transferable USDT in spot.
- Fix: every balancing pass first sweeps transferable master spot USDT to `USDT_FUTURE` with `MAIN_UMFUTURE`. Only after that sweep, if futures available is below the configured reserve, the child transfer is blocked. If it is above the reserve, only the futures surplus may be sent to children through the supported futures→spot→child-margin bridge.
- Safety: child top-ups no longer consume master spot directly; extra funds remain in the master futures wallet for the shared hedge leg. The configured reserve value remains user-controlled.
- Status: Deployed to production at 2026-09-14 14:51 UTC. Each balancing cycle now sweeps master spot USDT back to the futures wallet before applying the reserve gate. Worker restarted successfully and remains active.
- Rollback backup: `/home/ec2-user/coin-backups/autotransfer-reserve-gate-20260914T145120Z/margin_balancer.py`.

## COIN-REG-20260914-MARKET-STATUS-RESTORE - Restore market status semantics after Worker/UI rollback

- Status: Deployed to production on 2026-09-14T16:09Z; `cex-worker.service` and `cex-business.service` active.
- Root cause: production had a newer complete 4,800+ line Worker than the repository's 1,300-line historical copy, but its `-3045` inventory cooldown branch published the retired `无券` status. The dashboard bundle also rendered backend labels verbatim, so `行情异常` and `无券` reappeared after previous fixes.
- Fix: synchronized the complete production Worker back into the repository (preserving inventory throttling, ordered pushed slots, UID scope, position recovery, automatic transfer reserve gate, and residual cleanup). The inventory cooldown branch now remains `运行中`; legacy payloads are rendered as `寻币中`. UI status mapping applies `无券→寻币中` and `行情异常→行情未到` on desktop, compact, mobile, and sub-account rows, including tooltips. Dead-coin icon logic remains limited to explicit `死币`/delisting markers.
- Verification: local Python compilation and frontend build passed. Production login for `lxy` succeeded; `/api/engine/health` returned `HEALTHY`, `RUNNING`, five fresh workers, `uid_scope_available=true`, `spread_count=349`, and zero API errors. Production Worker is 5,043 lines after deployment. The new Dashboard bundle hash matches the local build and is served by the current index.
- Rollback backup: `/home/ec2-user/coin-backups/market-status-rollback-20260914T160808Z/` (Worker, API/schema, and complete prior SPA archive). Existing static assets were retained; no SPA/dist files were deleted and no trading action was issued.
- Regression rule: never deploy the shortened historical Worker or a UI bundle that exposes raw `无券`/`行情异常` labels. Preserve the explicit market-state mapping and the complete Worker source in future releases.

## COIN-REG-20260914-FRONTEND-BUNDLE-CLEANUP - Archive obsolete SPA bundles

- Status: Completed on 2026-09-14T16:26Z.
- The current entry `index-B9MEsjel.js` reaches 17 hashed JS dependencies plus `index-naR2FL25.css`; 68 prior hashed JS/CSS files were unreachable historical builds.
- Those 68 files were moved out of the public SPA directory into `/home/ec2-user/coin-backups/frontend-old-bundles-20260914T162626Z/assets/` before cleanup. No current asset, `dist` directory, Service Worker, Logo, or source file was deleted.
- Production root and all current entry/dependency assets return HTTP 200. Both business and Worker services remain active; authenticated engine health remains `HEALTHY/RUNNING` with five workers and UID scope enabled.
- Release rule: publish only assets reachable from the current entry manifest, archive obsolete bundles before removal, and retain the archive for rollback.

## COIN-REG-20260914-2DAY-AUDIT - Restore account-rule display and scheduled residual scan

- Audit window: commits from 2026-09-12 through 2026-09-14. The largest change was `2ff1306`, which restored the complete Worker (about 1,372 lines to 5,043 lines); subsequent commits did not remove its rule reload, ordered push, transfer reserve, position recovery, or market status logic.
- Confirmed gap: the dashboard loaded only user-level `SymbolRule` rows. A valid per-subaccount `AccountSymbolRule` therefore affected execution but the coin row still said `通用规则`. `DashboardPage` now merges real account overrides from each owned subaccount and marks that symbol `单一规则`; empty placeholder rows remain `通用规则`.
- Confirmed gap: `run_terminal_residual_scan` and provenance-gated margin-dust conversion existed but were never scheduled by Worker. Worker now runs this scan every 1,800 seconds; it requires no active position, zero debt, matching CLOSED provenance, isolated wallet balance, and Binance-supported dust conversion before acting.
- Production deployment: updated Worker, residual checker, user dashboard source, and rebuilt SPA on 2026-09-14T17:16Z. Engine was explicitly started for lxy after restart; health now reports `HEALTHY/RUNNING`, five workers, and `uid_scope_available=true`.
- Verification: all 13 Python regression tests pass; frontend branding check, TypeScript, and Vite build pass. Current index and Dashboard bundle return HTTP 200. No borrow, order, repay, or transfer test was issued.
- Rollback backup: `/home/ec2-user/coin-backups/regression-audit-20260914T171630Z/`.

## COIN-REG-20260914-MASTER-USDT-BALANCE - Use actual futures USDT asset for display and transfers

- Root cause: the master balance API and margin balancer used Binance top-level futures `availableBalance`, which is a multi-asset USDT valuation. It exceeded the actual USDT asset balance (for example 685.69 valuation versus 580.63 USDT wallet).
- Fix: `/api/master-account/balance` now returns `futures_usdt_wallet` and `futures_usdt_available` from the `assets[].asset=USDT` row. The dashboard's “合约可转” card displays the actual USDT wallet amount first. The balancer budgets `min(walletBalance, availableBalance)` for USDT transfers, preventing non-USDT collateral from being treated as transferable USDT.
- Production verification: API returned `futures_usdt_wallet=580.62644022`; UI source now prefers this field. After restart and explicit engine start, health returned `HEALTHY/RUNNING` with all five workers active.
- No manual transfer or trading operation was issued. Existing reserve gate remains in force.

## COIN-REG-20260914-HEADER-USDT-ORDERS - Actual USDT and confirmed futures order count

- Status: Deployed at 2026-09-14T18:14:21Z. This supersedes the incomplete display/transfer formula in MASTER-USDT-BALANCE above.
- Balance root cause: the earlier patch changed RulesPage only; the header and AccountsPage still displayed collateral valuations. Even the USDT asset row's `availableBalance` can include other collateral (686.05 versus the actual 580.63 USDT wallet). Desktop/mobile headers and master-account panels now share `masterFuturesUsdt`: wallet=`walletBalance`, occupied margin=`initialMargin`, transferable=`max(0,min(walletBalance,maxWithdrawAmount))`. Missing telemetry displays unknown and never falls back to valuation. The balancer likewise treats missing/invalid data or zero withdrawable USDT as zero while retaining the configured reserve policy.
- Counter root cause: `position_count/total_contracts` represented OPEN/all Position lifecycle rows, not exchange fills. The production 0/10635 included 10578 FAILED rows and 57 CLOSED rows. The user explicitly selected cumulative filled futures order count, including opens and closes, deduplicated per order.
- Counter implementation: `futures_filled_order_count` counts user-scoped SUCCESS TradeLog rows with finite positive executed quantity and valid positive Binance order IDs. Includes open/close, limit tranches, market fallbacks, and rollback-close records when supported by a real order ID. Deduplication key is executing master/subaccount + symbol + order ID; shared master hedges across child accounts count once. Synthetic `limit` summaries, failures, zero fills and non-futures events are excluded. Counts reflect retained system execution records, not unrecorded manual Binance trades. Redis and WebSocket use the same field. Desktop/mobile show `合约成交 48 笔`; old lifecycle fields remain API-compatible but are no longer displayed as contract executions.
- Verification: 24 Python regression tests passed (including database-level user isolation, duplicate orders, invalid IDs and zero/missing transferable funds); frontend branding, TypeScript/Vite build and USDT display tests passed. Production database, Redis and authenticated WebSocket all returned 48 (30 opens + 18 closes). Authenticated balance API returned wallet/transferable=580.62644022 and initialMargin=0. Public dashboard/login and 19 asset URLs passed, with all served asset bytes matching the release; admin login returned HTTP 200.
- Deployment: `cex-business.service` and `cex-worker.service` are active. The user's trading engine was already STOPPED in preflight and remains STOPPED; no start/borrow/order/repay/transfer request was issued. All 148 pre-existing SPA files were preserved. Entry is `index-JJA8SZEQ.js`; index SHA-256=`d5030ccb119ce4e0e7930dac0ea1d19a88025afe5e643f9a2edc855676ed80eb`.
- Rollback backup: `/home/ec2-user/coin-backups/header-balance-order-count-20260914T181421Z/before.tar.gz`. Release manifest, previous files, deployment/probe scripts and public verification evidence: `D:/Dev/MixCodex/ops/coin-header-release-20260914/`.
- Regression rule: never relabel Position row counts as fills or use futures collateral valuation as actual USDT. Preserve per-user/account order deduplication, zero-withdrawable semantics, missing-data display and both desktop/mobile renderers. Production frontend source has older/different edits than its active bundles; the previous release's complete reachable JS/CSS was verified equal to the prior local build before publishing this patch. Build from the reviewed repository and release manifest, not unreviewed server source or historical bundles. No complete Worker or residual/rule lifecycle code was replaced.
