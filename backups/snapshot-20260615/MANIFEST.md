# Snapshot 20260615 — 260615最后留存版

- Date: 2026-06-15 (UTC)
- Branch: go
- HEAD at backup: 061c5dde801a2c1046ff24770bf291a59f54b3c0
- Database: **NOT included** (intentionally excluded per request)
- Source + dist also remain in-place on go branch HEAD (061c5dde); these tarballs are a self-contained, independently-restorable copy.

## Contents (4 domains + Go backend + Python backend + legacy frontend)

| File | Source | Notes |
|------|--------|-------|
| frontend-admin-dist.tar.gz | frontend-admin/dist | admin.hustle2026.xyz built dist |
| frontend-admin-src.tar.gz | frontend-admin (excl node_modules,dist) | admin source |
| frontend-auto-dist.tar.gz | frontend-auto/dist | auto.hustle2026.xyz built dist |
| frontend-auto-src.tar.gz | frontend-auto (excl node_modules,dist) | auto source |
| frontend-go-dist.tar.gz | frontend-go/dist | go.hustle2026.xyz built dist |
| frontend-go-src.tar.gz | frontend-go (excl node_modules,dist,backup_*) | go source |
| frontend-www-dist.tar.gz | frontend-www/dist | www.hustle2026.xyz built dist |
| frontend-www-src.tar.gz | frontend-www (excl node_modules,dist) | www source |
| frontend-legacy.tar.gz | frontend (excl node_modules) | legacy combined frontend (dist/dist-*/src/src-*) |
| go-backend.tar.gz | go-backend | Go service source + hustle-go binary |
| backend-app.tar.gz | backend (excl venv,*.log,__pycache__,.env*) | Python FastAPI source |

## Exclusions
- node_modules/ (all frontends), backend/venv/
- *.log / *.log.* (backend logs)
- __pycache__/, *.pyc, *.pyo
- backend/.env, backend/.env.* (secrets — restore config separately)
- Database (no pg_dump in this snapshot)

## Restore (from repo root /data/hustle2026)
```
tar xzf backups/snapshot-20260615/<file>.tar.gz
```
Each tarball restores its original relative path (e.g. frontend-go/dist/...).
