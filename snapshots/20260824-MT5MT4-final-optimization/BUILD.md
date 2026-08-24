# Capture metadata

* Capture time: 2026-08-24 UTC
* QH host: `54.238.164.60` (private host `ip-172-31-36-34`)
* Live build reported by `/api/health`: `hedge-pro-mt5-terminal-projection-manual-eager-20260824.3`
* Live API source: `python/app.py`, SHA-256
  `24852143B8F580D8BCF79AE0777742C7898D1FA7920EBCE6D11009EAD4341961`
* Frontend `qh` index SHA-256:
  `8733D07EBDA2524A0DB72821486C693D73C89A41BE40861E348EEB82C97CD720`
* Health checks at capture: `qh.hustle2026.xyz/api/health` and
  `qhadmin.hustle2026.xyz/api/health` returned HTTP 200; the public site
  config endpoint returned HTTP 200.
* Source branch baseline before this snapshot: `qh` at
  `948eb83fd6f00146573ed7c50e9470657c1b0a59`.

The snapshot is a filesystem capture of the live roots, not a reset or merge
of the dirty `/opt/quanthedge` working tree. This preserves the production
dist/assets exactly as served.
