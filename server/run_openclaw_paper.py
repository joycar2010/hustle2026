"""Local OpenClaw-compatible Paper heartbeat publisher."""
import json
import os
import time
from pathlib import Path

ROLES = ("desk", "search", "whale", "shill", "risk", "sniper", "exit", "rug")

def main() -> None:
    root = Path(__file__).resolve().parent.parent
    heartbeat = root / "openclaw-heartbeat.json"
    while True:
        now = time.time()
        roles = {
            role: {
                "status": "blocked" if role == "sniper" else ("running" if role in ("desk", "risk") else "idle"),
                "heartbeat_ts": now,
                "queue_depth": 0,
                "market": "BTC/ETH/天气/体育",
                "mode": "paper",
                "detail": "本地 Paper 调度；无钱包和下单权限",
            }
            for role in ROLES
        }
        state = {
            "schema_version": 1,
            "instance": "polyauto" if "polymarketbot-auto" in str(root).lower() else "main",
            "pid": os.getpid(),
            "updated_ts": now,
            "roles": roles,
        }
        tmp = heartbeat.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(heartbeat)
        time.sleep(5)

if __name__ == "__main__":
    main()
