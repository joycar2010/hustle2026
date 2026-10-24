import json, os, sqlite3, time
from datetime import datetime, timezone
root = "/home/ec2-user/paper-ab/20261022T020933Z"
end = time.time() + 48 * 3600
path = os.path.join(root, "metrics-abc.jsonl")
def snap(group):
    db = os.path.join(root, group, "ab.db")
    try:
        c = sqlite3.connect(db, timeout=5)
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "group": group,
            "orders": c.execute("select status,side,count(1),coalesce(sum(size),0),coalesce(sum(filled_size),0) from orders group by status,side").fetchall(),
            "actions": c.execute("select action,count(1) from decisions group by action").fetchall(),
            "db_bytes": os.path.getsize(db),
        }
    except Exception as exc:
        return {"ts": datetime.now(timezone.utc).isoformat(), "group": group, "error": repr(exc)}
while time.time() < end:
    with open(path, "a", encoding="utf-8") as out:
        for group in ("A", "B", "C"):
            out.write(json.dumps(snap(group), ensure_ascii=False) + "\n")
        out.flush()
    time.sleep(300)
