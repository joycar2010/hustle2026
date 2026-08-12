# QH Production Snapshot - 2026-08-12

Commit note: `20260812坑位优化版`

This snapshot was collected from `quant-hedge-server` (`54.238.164.60`) without
stopping or rebuilding any production service.

## Contents

- `web/`: exact live files for `qh.hustle2026.xyz`.
- `admin/`: exact live files for `qhadmin.hustle2026.xyz`.
- `qhwww/`: exact live files for `qhwww.hustle2026.xyz`, including the client
  installer.
- `goview/web/`: exact live GoView frontend exposed by the admin domain.
- `admin-src/`, `client-src/`, `qhwww-source-copy/`, and `goview/src/`: source
  trees found on the production host.
- Repository root: deployment-compatible mirror of the active Python backend
  sources and migrations, matching the historical `qh` branch layout.
- `backend/`: immutable snapshot copy of the same active Python backend sources,
  migrations, tests, and runtime data inventory.
- `qh_ws_hub/`: active Rust Hub sources and the release binary actually used by
  `qh-ws-hub.service`.
- `goview/goview-serve`: active GoView binary.
- `ops/`: Nginx configuration and sanitized systemd templates.
- `artifacts/frontend-dist/`: exact timestamped archives and per-file SHA-256
  manifests for every live frontend tree.
- `artifacts/qh-private-databases-and-config-20260812.tar.zst.cms`: encrypted
  PostgreSQL, Redis, SQLite, and private runtime configuration recovery package.
- `public-tree-20260812.tar.zst`: complete expanded public source/program/dist
  tree as exported from production.

## Database Security

The GitHub repository is public. No plaintext database or runtime credential is
stored here. The private package is encrypted with OpenSSL CMS using AES-256-CBC
and a dedicated RSA-4096 recovery certificate.

Only the public certificate is committed. The recovery private key was saved
outside the Git repository at:

`D:\qh-backup-private\20260812\qh-backup-recovery-private-20260812.pem`

Store that private key in an additional access-controlled offline location.
Without it, the encrypted database backup cannot be recovered.

## Recovery

On a machine with OpenSSL and Zstandard:

```bash
openssl cms -decrypt -binary -inform DER \
  -in artifacts/qh-private-databases-and-config-20260812.tar.zst.cms \
  -recip artifacts/qh-backup-recovery-public-20260812.crt \
  -inkey qh-backup-recovery-private-20260812.pem \
  -out qh-private-databases-and-config-20260812.tar.zst

zstd -d qh-private-databases-and-config-20260812.tar.zst -c \
  | tar -xf -
```

Before restoring, verify `MANIFEST.sha256` inside the decrypted package and
restore into an isolated environment first. PostgreSQL dumps are custom-format
`pg_dump` files and should be inspected with `pg_restore --list`.

The production GoView source contains a hard-coded JWT signing string inherited
from that application. It is preserved for source fidelity, but it should be
rotated and moved into an environment-backed secret before any redeployment.

## Integrity

- `DOWNLOADS.sha256` authenticates all exported archives and artifacts.
- `public-tree-20260812.sha256` authenticates every file in the expanded public
  snapshot.
- Each archive in `frontend-dist/` has its own per-file manifest.
- `SNAPSHOT.txt` records the production host, timestamp, and source Git head.

Verification completed before commit:

- All 949 files from the exported public tree matched their production
  SHA-256 values after being re-exported from the Git index.
- PostgreSQL archives were fully decoded by `pg_restore`, Redis RDB passed
  `redis-check-rdb`, and both SQLite files returned `PRAGMA integrity_check=ok`.
- No plaintext database, runtime credential file, or private key was staged.
