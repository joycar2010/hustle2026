# MT5 Windows Agent

Live source from MT5 host `172.31.14.113` (`C:\MT5Agent\`). This directory
mirrors the Windows service `MT5WindowsAgent` — the ambient process that
launches / restarts / GUI-unlocks MT5 terminal instances.

## Live process
nssm-wrapped: `C:\Program Files\Python311\python.exe C:\MT5Agent\main_v3.py`
Listens on 172.31.14.113:8765 (referenced by gateway `.env` `MT5_AGENT_URL`).

## Key files
- `main_v3.py` — the agent daemon (restart / relaunch / session-0 unblock)
- `config.json` — agent-wide config
- `instances.json` — per-broker MT5 instance registry (login, server, path, state)
- `install-service.ps1` / `install-agent-service.ps1` — nssm install scripts
- `requirements.txt` — Python deps (MetaTrader5, fastapi, uvicorn, psutil, etc.)

## Sync workflow
After live changes on MT5 host, re-copy and push:
```powershell
# on MT5 host
scp -i d:/HustleNew.pem C:/MT5Agent/main_v3.py C:/MT5Agent/*.json ubuntu@172.31.2.22:/data/hustle2026/mt5-agent/
```
Then on the gateway: `cd /data/hustle2026 && git add mt5-agent && git commit && git push origin go`
