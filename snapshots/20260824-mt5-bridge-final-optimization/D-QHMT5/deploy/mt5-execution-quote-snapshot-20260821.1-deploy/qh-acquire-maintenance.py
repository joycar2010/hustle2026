#!/usr/bin/env python3
"""Acquire the QH blocking maintenance lease for the MT5 bridge cutover."""

import datetime
import json
import os
import sys
from pathlib import Path

import redis


RELEASE = "mt5-execution-quote-snapshot-20260821.1"


def main() -> None:
    if len(sys.argv) != 2 or len(sys.argv[1]) < 16:
        raise SystemExit("usage: qh-acquire-maintenance.py TOKEN")
    token = sys.argv[1]
    client = redis.Redis(host="127.0.0.1", port=6379, db=3,
                         decode_responses=True)
    if client.get("qh:maintenance") is not None:
        raise SystemExit("maintenance already present")

    controls = {}
    for prefix in ("qh:auto_entry:", "qh:auto_exit:"):
        for key in client.scan_iter(match=prefix + "*"):
            suffix = key[len(prefix):]
            if (suffix and ":" not in suffix and
                    suffix not in {"last", "err", "paused"} and
                    client.type(key) == "string"):
                controls[key] = client.get(key)

    payload = {
        "on": True,
        "block_login": False,
        "block_trading": True,
        "stop_strategy": False,
        "title": "QH deployment maintenance",
        "msg": "Deploying MT5 quote snapshot bridge 20260821.1",
        "release": RELEASE,
        "deployment_token": token,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "until": "",
        "by": "codex-release",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if not client.set("qh:maintenance", raw, nx=True):
        raise SystemExit("maintenance acquire race")

    backup_dir = Path(os.environ.get("QH_BACKUP_DIR", "/opt/quanthedge/backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{RELEASE}-controls-before-{token}.json"
    temp = backup.with_suffix(backup.suffix + ".tmp")
    temp.write_text(json.dumps({"token": token, "release": RELEASE,
                                "controls": controls}, sort_keys=True,
                               separators=(",", ":")), encoding="utf-8")
    temp.replace(backup)
    for key in controls:
        client.set(key, "off")
    if any(client.get(key) != "off" for key in controls):
        raise SystemExit("failed to contain automatic controls")
    print(json.dumps({"maintenance": "owned", "controls_saved": len(controls),
                      "backup": str(backup), "release": RELEASE},
                     sort_keys=True))


if __name__ == "__main__":
    main()
