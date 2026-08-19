import json
import os
import sqlite3
import time


paths = {
    "main": r"D:\QHCELL\pool\s1\inst\idempotency.db",
    "hedge": r"D:\QHCELL\pool\s3\inst\idempotency.db",
}
cutoff = time.time() - 120
result = {}
active = []
for role, path in paths.items():
    rows = []
    if os.path.exists(path):
        connection = sqlite3.connect(path, timeout=5)
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='order_requests'"
            ).fetchall()
            if tables:
                rows = connection.execute(
                    "SELECT request_id,state,updated_at FROM order_requests "
                    "WHERE state IN ('PENDING','SENDING') AND updated_at>=? ORDER BY updated_at",
                    (cutoff,),
                ).fetchall()
        finally:
            connection.close()
    result[role] = [
        {"request_id": row[0], "state": row[1], "updated_at": row[2]}
        for row in rows
    ]
    active.extend((role,) + row for row in rows)
print(json.dumps({"active": result}, separators=(",", ":")))
if active:
    raise SystemExit(3)
