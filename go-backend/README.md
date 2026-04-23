# hustle-go (Go market service)

Live source previously lived at `/data/hustle-go` outside any git repo.
Mirrored here as part of the unified `origin/go` backup on 2026-04-23.

## Layout
- `cmd/server/main.go` — service entrypoint (binds 8080)
- `internal/` — 18 modules (accounts / agentclient / auth / automation /
  config / db / healthwatch / market / middleware / monitor / mt5 / mt5config /
  notifications / opportunities / pairs / proxy / rbac / risk / strategies /
  sysops / users)

## Service
`hustle-go.service` (systemd) execs `/data/hustle-go/hustle-go`. Binary
is excluded from git (.gitignore) — rebuild via `go build -o hustle-go ./cmd/server`.

## Sync workflow
Edits to `/data/hustle-go/` should be mirrored back here:
```
rsync -a --exclude='hustle-go' --exclude='hustle-go.bak*' /data/hustle-go/ /data/hustle2026/go-backend/
cd /data/hustle2026 && git add go-backend && git commit -m 'sync go-backend' && git push origin go
```
