# MT5/MT4 bridge snapshot: 20260824 final optimization

Collected read-only from `43.206.15.17` (`EC2AMAZ-2SH9D10`) on 2026-08-24
UTC. The snapshot contains the bridge programs and deployment material used
by the current production tasks:

Backup note: 20260824 MT5/MT4 final optimization.

* `C-MT5Agent` contains the new MT5 bridge entry point and redacted runtime
  configuration.
* `D-QHMT5` contains the IC/Bybit Python bridge sources, per-instance app
  trees, supervisor/guardian scripts, all dated deployment releases and
  staged hedge-pro releases, small idempotency snapshots, and deployment
  task material.
* `D-QHCELL` contains the MT4 cell controller, pool start templates, active
  `QHBridge.mq4/.ex4` files, templates, and task backups.
* `D-MT4LAB` contains the MT4 agent, file bridge, ledger, EA build/release
  sources, watchdog scripts, and task templates.
* `user-home` contains the explicitly identified historical bridge source
  files used during the recent repairs.
* `MANIFEST.json` records SHA-256 and byte size for every copied file.

Exact account passwords, `.env` files, cell environment values, and bridge
configuration secrets are in `secrets/qh-mt5-sensitive-20260824.tar.gz.enc`.
The runtime/ledger SQLite snapshots (including dated idempotency backups) are
in `secrets/qh-mt5-runtime-state-20260824.tar.gz.enc`; no account/trade DB is
stored as a plaintext Git blob. Both artifacts are encrypted with the same
local AES-256-CBC key used by the QH snapshot and the key remains outside GitHub at
`C:\Users\Administrator\qh-backup-work-20260824\qh-secret-key.txt`.

MetaTrader vendor terminals, editors, generated history/cache/log trees and
virtual environments were not copied: several individual binaries exceed
GitHub's 100 MiB blob limit. Their paths and size information are recorded in
`manifest-mt5-inventory.md`; the bridge source, EA files, runtime scripts and
deployment templates are all included.
