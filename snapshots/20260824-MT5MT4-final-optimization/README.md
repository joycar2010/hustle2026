# QH production snapshot: 20260824 MT5/MT4 final optimization

This snapshot was collected from `54.238.164.60` on 2026-08-24 UTC without
stopping the production services or changing the server repository. It covers
the three live domains and the runtime used by the current build:

* `frontend/qh` is the complete `/opt/quanthedge/web` tree for
  `qh.hustle2026.xyz`.
* `frontend/qhadmin` is the complete `/opt/quanthedge/admin` tree for
  `qhadmin.hustle2026.xyz`.
* `frontend/qhwww` is the complete `/opt/qhwww` tree for
  `qhwww.hustle2026.xyz`, including the installer and all `dist/assets`
  content present on the host.
* `python` contains the live Python service files, tests, admin/client source,
  and deployment staging files.
* `rust` contains the Rust WebSocket hub source, release metadata, and the
  deployed hub copy (build `target` cache is intentionally omitted).
* `deploy/redacted-config` contains the Nginx and systemd templates with
  credential values replaced by `<REDACTED>`.

The encrypted database/config artifact is split into six GitHub-compatible
parts under `database/` (`qh-sensitive-20260824.part-000` through `005`). It
contains a PostgreSQL custom dump of `quanthedge`, PostgreSQL globals, the
Redis RDB snapshot, exact Nginx/systemd/history archives, and the exact MT5
secret archive. No plaintext credentials, private keys, or database contents
are committed to this public repository.

To restore the encrypted artifact on the backup workstation, concatenate the
parts in lexical order and decrypt with the local key file
`C:\Users\Administrator\qh-backup-work-20260824\qh-secret-key.txt` using
OpenSSL AES-256-CBC (`-pbkdf2 -iter 200000`). The key is deliberately kept
outside GitHub. The inventory reports at the snapshot root record source
paths, service versions, and SHA-256 hashes.

The full historical staging/backup trees and volatile virtual environments,
logs, caches, and Python bytecode are inside the encrypted archive or are
listed as exclusions in the inventory; the live frontend trees above are
complete and were not filtered or cleaned.
