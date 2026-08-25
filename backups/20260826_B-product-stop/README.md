# MIX full snapshot: 20260826-B-product-stop

Snapshot date: 2026-08-25 UTC (requested label: `20260826-B产品停止版`).

This directory is an additive, read-only capture of the four MIX hosts and the
two web domains. Existing source and deployed `dist` directories were not
modified or removed. The host tarballs exclude dependency caches, logs, build
targets, virtual environments, and credential material; the configuration
files retain paths and service definitions but do not contain secret values.

Hosts:

* A-rust `57.182.57.4`: Rust/CEX and A-data services.
* B-exec `54.65.42.207`: execution services and account routing.
* C-ctrl `57.181.130.126`: MIX control plane, API, WebSocket, web domains.
* D-test `13.230.29.158`: research/test services.

Domains resolved from the live C nginx configuration:

* `mix.hustle2026.xyz`
* `mixadmin.hustle2026.xyz`
* `user.hustle2026.xyz`
* Compatibility domains also present: `coin.hustle2026.xyz` and
  `coinadmin.hustle2026.xyz`.

Database note: A and B logical dumps are complete. C schema dumps and a
consistent database/table-size inventory are included. `mix_main` is about
88GB, with `b_signal_event` and `b_rule_log` accounting for most of it; a
full dump cannot fit on the C host's remaining 40GB or within GitHub's file
limits. The previous compact logical dumps remain in the repository under
`backups/20260726_prebackport/`.

All artifacts must be verified with `SHA256SUMS.txt` before restore. Restore
commands must be reviewed against the target environment; this snapshot does
not stop services, revoke credentials, or alter production state.

The complete C source archive and its 40MiB parts are retained in the local
working archive, with their hashes in `manifests/local-only-artifacts.txt`.
They are intentionally excluded from the Git commit because the complete
source is already present in the MIX source tree on this branch and a 700MB
pack exceeds GitHub's practical push window. Concatenate the local parts in
lexical order and verify the recorded hash before extracting.
