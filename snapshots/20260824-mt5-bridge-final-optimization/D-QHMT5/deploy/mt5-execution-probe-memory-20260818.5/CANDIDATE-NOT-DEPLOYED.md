# MT5 .5 memory execution probe candidate

Build: mt5-execution-probe-memory-20260818.5

Status: sealed local candidate only. It has not been deployed and no real
open, close, recovery, or stress order was sent while building or validating
it.

The release keeps every .4 durable wakeup and single-native-owner guarantee,
then removes the last SQLite operation from the execution keepalive path.
`execution_probe=true` reads only cached account identity, manager state, and a
fail-closed in-memory coordinator health snapshot. It does not call full
metrics, lock SQLite, count WAL rows, or issue native RPC.

Deployment requires blocking QH maintenance, exact .4 production hashes, zero
positions and queues, the single-native-owner process model, and a fully
healthy allocated Cell. The deployer performs only health, position, queue,
hash, and absent-status probes; it does not submit an order.

The app package marker is now a sealed deployment file. Rollback restores the
exact .4 package shape, including removing it when it was absent before the
upgrade.

Rollback restores code and environment only. The live idempotency database,
WAL, and SHM remain at their newest durable state and must never be restored
from the pre-deploy forensic copy.
