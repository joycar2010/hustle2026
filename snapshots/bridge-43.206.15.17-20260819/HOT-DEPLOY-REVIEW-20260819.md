# Bridge hot-deploy and new-client review

Source: `EC2AMAZ-2SH9D10` (`43.206.15.17`), read-only review on 2026-08-19. The snapshot covers `D:\QHMT5`, `D:\QHCELL`, `D:\MT4LAB\agent`, bridge root scripts, current scheduled tasks, and the independent `C:\MT5Agent` source/config shape.

## One-line bridge change summary

Cell warm-pool provisioning/self-healing was enabled; MT4 session-0 task handling, `schtasks` end-then-run ordering, and `start.ini` double-CRLF authentication were fixed; `hedge_pro` independent MT5 two-leg and `jj456` MT4 closed-loop verification was completed.

## Deployment timing

- The supervisor and Cell watchdog poll every 30 seconds. Three failed samples are required before recovery, so detection starts at about 90 seconds; restart cooldown is 180 seconds.
- A new `/cell/allocate` request is a cold provision. Health is polled every 2 seconds with a 150-second hard budget. MT4 also requires the session-0 terminal task end/run sequence and EA login.
- The current `.5` deployment template is maintenance/quiesce, not rolling: it pauses the watchdog and Cell, stops the 8061/8063 bridges, installs files, then waits for Cell (up to 150 seconds) and each bridge (up to 90 seconds) sequentially.
- Reserve 3-6 minutes for the strict worst case. Normal restarts are usually seconds to tens of seconds, but the affected account is unavailable while its terminal/bridge is replaced.

## New MT4/MT5 client compatibility

No API redesign is required when the client implements the current `/mt5/*` v3 contract. It must use a stable unique `request_id`, query order status after HTTP 202/PENDING/UNKNOWN, provide an exact positive close `ticket`, and never blindly resend an uncertain order.

Each new account needs an isolated terminal path, environment file, bridge port, and idempotency DB/WAL/SHM. MT4 additionally needs the matching EA, AutoTrading, atomic state files, and the session-0 scheduled task.

The open/close protocol should remain v3: single native owner, durable idempotency, exact-ticket close, bounded quote refresh retry, filling-mode selection, and post-trade position reconciliation. `close-all` is still sequential per ticket and cannot promise sub-second completion for a burst. Broker `order_send` and terminal serialization remain external latency sources.

## Follow-up risks

The audit observed `execution_queue.single_thread=false` while the nested MT5 API queue is single-threaded, and read calls such as `history_deals_get`/`symbol_info_tick` can reach roughly 2.5/2.3 seconds. Normalize the queue admission flag and move non-critical reads off the trade lane before promising a 0.5-second end-to-end target. Verify the live hash/build before treating a `CANDIDATE-NOT-DEPLOYED` package as production.

This snapshot excludes credentials, login state, terminal runtimes, virtual environments, logs, ledgers/WAL files, and market-data caches. Hard-coded API keys found in historical scripts were replaced with `<REDACTED_API_KEY>` before commit. `MANIFEST.sha256.json` covers the sanitized snapshot; `REMOTE-MANIFEST.sha256.json` records the pre-redaction export hashes.
