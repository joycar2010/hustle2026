import json
import os
import sqlite3
import time
from datetime import datetime, timezone

ROOT = "/home/ec2-user/paper-ab/20261022T020933Z"
END = time.time() + 48 * 3600

def snapshot(name):
    path = os.path.join(ROOT, name, "ab.db")
    try:
        c = sqlite3.connect(path, timeout=5)
        orders = c.execute(
            "select status, side, count(1), coalesce(sum(size),0), coalesce(sum(filled_size),0) "
            "from orders group by status, side"
        ).fetchall()
        actions = c.execute(
            "select action, count(1) from decisions group by action"
        ).fetchall()
        latest = c.execute(
            "select ts, action, reason from decisions order by id desc limit 1"
        ).fetchone()
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "group": name,
            "orders": orders,
            "actions": actions,
            "latest": latest,
            "db_bytes": os.path.getsize(path),
        }
        c.close()
        return row
    except Exception as exc:
        return {"ts": datetime.now(timezone.utc).isoformat(), "group": name, "error": repr(exc)}

log_path = os.path.join(ROOT, "metrics.jsonl")
while time.time() < END:
    with open(log_path, "a", encoding="utf-8") as out:
        for group in ("A", "B"):
            out.write(json.dumps(snapshot(group), ensure_ascii=False) + "\n")
        out.flush()
    time.sleep(300)
