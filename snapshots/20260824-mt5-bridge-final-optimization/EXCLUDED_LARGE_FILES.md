# Files intentionally outside the Git snapshot

GitHub rejects normal Git blobs of 100 MiB or larger. The live bridge does
not need these vendor/runtime artifacts to rebuild the Python/EA services, so
they remain on the bridge host and are recorded here rather than silently
deleted:

* `D:\QHMT5\terminals\{by01,bysys,ic01,icsys,icsysnew}\terminal64.exe`
  (about 109-132 MiB each) and the corresponding `MetaEditor64.exe` files.
* `D:\QHCELL\pool\{s1,s2,s3,s4}\terminal\terminal64.exe` and
  `MetaEditor64.exe`, plus the matching `D:\QHCELL\templates\{ic,exness}`
  vendor terminals (about 109-128 MiB each).
* Rotated bridge/agent logs and generated terminal history/cache files, which
  are hundreds of MiB and change while the service is running.

The SQLite idempotency and agent-ledger snapshots are retained in the
encrypted `secrets/qh-mt5-runtime-state-20260824.tar.gz.enc` artifact instead
of being exposed as plaintext database blobs.

The exact path and byte-size inventory for the host is in
`manifest-mt5-inventory.md`; no source, EA, deployment script, task XML, or
bridge configuration template is omitted for size reasons. If a binary
mirror is needed later, publish it as a separately permissioned release or
Git-LFS artifact rather than raising the normal GitHub blob limit.
