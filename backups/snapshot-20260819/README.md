# QH Production Snapshot - 2026-08-19

Commit note: `2026819MT5MT4开平仓修复`

Collected from `quant-hedge-server` (`54.238.164.60`) without stopping or
rebuilding production services.

## Included

- `web/`: live frontend for `qh.hustle2026.xyz`.
- `admin/`: live frontend for `qhadmin.hustle2026.xyz`.
- `qhwww/`: live frontend for `qhwww.hustle2026.xyz`.
- `admin-src/`, `client-src/`, `qhwww-source-copy/`, `goview/src/`: source.
- Root Python backend files and the immutable `backend/` source mirror.
- `qh_ws_hub/` Rust source and sanitized service metadata.
- `backups/snapshot-20260819/runtime-binaries/`: exact live installer,
  Rust Hub binary, and GoView binary. The `.bin` suffix avoids Git LFS
  pointers because this host has no Git LFS client.
- `backups/snapshot-20260819/artifacts/frontend-dist/`: exact frontend
  archives and per-file SHA-256 manifests.

## Database Security

The GitHub repository is public. No plaintext database, runtime credential,
or private key is committed. PostgreSQL `quanthedge` and `postgres`, Redis,
and both GoView SQLite databases are inside the encrypted CMS package:

`backups/snapshot-20260819/artifacts/qh-private-databases-and-config-20260819.tar.zst.cms.bin`

Encryption is OpenSSL CMS AES-256-CBC with a dedicated RSA-4096 recovery
certificate. The private key is retained outside GitHub in the local protected
directory `C:\Users\Administrator\qh-backup-private\20260819`.

## Recovery

```bash
openssl cms -decrypt -binary -inform DER \
  -in qh-private-databases-and-config-20260819.tar.zst.cms.bin \
  -recip qh-backup-recovery-public-20260819.crt \
  -inkey qh-backup-recovery-private-20260819.pem \
  -out qh-private-databases-and-config-20260819.tar.zst
zstd -d qh-private-databases-and-config-20260819.tar.zst -c | tar -xf -
```

Verify the decrypted `MANIFEST.sha256` before restoring. PostgreSQL files are
custom-format `pg_dump` files; inspect them with `pg_restore --list` first.

## Integrity

- `PRIVATE_SNAPSHOT_VERIFIED=1` from the server-side decrypt, manifest,
  PostgreSQL, Redis, and SQLite checks.
- Frontend live trees matched their exported SHA-256 manifests.
- `backups/snapshot-20260819/ARTIFACTS.sha256` covers all committed snapshot
  artifacts.
- No production service was stopped and no trading order was sent.
