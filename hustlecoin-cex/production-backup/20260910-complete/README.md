# Coin production backup — 20260910完整跑通版

This directory contains authenticated-encrypted, host-separated production backups for `18.176.76.127` (Python business/Worker) and `57.181.214.206` (Rust market engine). The GitHub repository is public, so no credentials, environment values, TLS private keys, database rows, or private age identity are included.

The current `coin` branch had no removable old-backup files. Existing source and compiled SPA trees remain preserved. The protected frontend roots are `python-business/static/spa` and `python-business/static/admin-spa`; historical static trees are included in the encrypted runtime archive.

## Restore

Install `age`, place the retained SSH private key at a protected local path, concatenate each artifact's ordered `part-*.bin` files, and verify the whole ciphertext SHA-256 from its manifest. Decrypt with `age -d -i <private-key> -o <archive> <rebuilt.age>`. Verify the plaintext SHA-256 recorded in the artifact JSON. Extract only after checking the archive listing.

The PostgreSQL custom dumps were checked with PostgreSQL 15 `pg_restore --list` (394 entries for `cex_trading`, 15 for `postgres`). This is a structural check, not a full isolated restore. Restore globals first, then create the target databases and restore the custom dumps with PostgreSQL 15 tools.

The Rust archive includes the ARM64 running binary, matching `rust-traffic-candidate` build source, project source, compiled frontend trees, local Redis configuration/RDB, and service configuration. The local Redis RDB is not a snapshot of the external shared Redis endpoint used by the applications; restore that dependency separately.
