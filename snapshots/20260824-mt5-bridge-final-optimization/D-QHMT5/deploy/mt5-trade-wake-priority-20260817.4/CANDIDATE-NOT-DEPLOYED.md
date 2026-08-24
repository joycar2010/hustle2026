# MT5 .4 durable wakeup candidate

Build: mt5-trade-wake-priority-20260817.4

Status: sealed local candidate only. It has not been deployed and no real
open, close, recovery, or stress order was sent while building or validating
it.

The release adds a generation-scoped cross-process wakeup for durable WAL
admissions, keeps a 50ms durable polling fallback, rechecks admitted trades
before ordinary native reads, exposes a memory-only execution identity probe,
and coalesces low-priority position/account refresh after terminal execution.

Deployment requires blocking QH maintenance, exact .3 production hashes, zero
positions and queues, the single-native-owner process model, and a fully
healthy allocated Cell. The deployer performs only health, position, queue,
hash, and absent-status probes; it does not submit an order.

Rollback restores code and environment only. The live idempotency database,
WAL, and SHM remain at their newest durable state and must never be restored
from the pre-deploy forensic copy.
