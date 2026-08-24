#!/usr/bin/env python3
"""CAS-release the QH maintenance lease after bridge verification."""

import datetime
import json
import sys
from pathlib import Path

import redis
from redis.exceptions import WatchError


RELEASE = "mt5-execution-quote-snapshot-20260821.1"


def main() -> None:
    if len(sys.argv) != 2 or len(sys.argv[1]) < 16:
        raise SystemExit("usage: qh-release-maintenance.py TOKEN")
    token = sys.argv[1]
    backup = Path("/opt/quanthedge/backups") / (
        f"{RELEASE}-controls-before-{token}.json")
    data = json.loads(backup.read_text(encoding="utf-8"))
    if data.get("token") != token or data.get("release") != RELEASE:
        raise SystemExit("maintenance backup identity mismatch")
    controls = data.get("controls")
    if not isinstance(controls, dict) or not controls:
        raise SystemExit("maintenance control backup is empty")
    if any(not (key.startswith("qh:auto_entry:") or
                key.startswith("qh:auto_exit:")) for key in controls):
        raise SystemExit("unexpected control key")

    client = redis.Redis(host="127.0.0.1", port=6379, db=3,
                         decode_responses=True)
    for _ in range(8):
        try:
            with client.pipeline() as pipe:
                pipe.watch("qh:maintenance")
                raw = pipe.get("qh:maintenance")
                state = json.loads(raw or "")
                if (state.get("deployment_token") != token or
                        state.get("release") != RELEASE or
                        state.get("on") is not True or
                        state.get("block_trading") is not True):
                    raise SystemExit("maintenance ownership mismatch")
                pipe.multi()
                for key, value in sorted(controls.items()):
                    pipe.set(key, value)
                pipe.delete("qh:maintenance")
                pipe.execute()
            break
        except WatchError:
            continue
    else:
        raise SystemExit("maintenance changed during CAS release")

    observed = {key: client.get(key) for key in sorted(controls)}
    expected = {key: str(value) for key, value in sorted(controls.items())}
    if observed != expected or client.get("qh:maintenance") is not None:
        raise SystemExit("maintenance release verification failed")
    report = backup.with_name(f"{RELEASE}-controls-restored-{token}.json")
    report.write_text(json.dumps({
        "release": RELEASE,
        "released_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "maintenance": "released",
        "controls": observed,
    }, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"maintenance": "released", "release": RELEASE,
                      "report": str(report)}, sort_keys=True))


if __name__ == "__main__":
    main()
