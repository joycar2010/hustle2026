import glob
import json
import sqlite3
import time


now = time.time()
output = {}
for path in sorted(glob.glob(r"D:\MT4LAB\agent\ledger_qh*.db")):
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            """
            SELECT request_id,state,created_at,updated_at,op
            FROM order_requests WHERE state='SENDING' ORDER BY created_at
            """
        ).fetchall()
        output[path] = [
            {
                "request_id": row[0],
                "state": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "op": row[4],
                "age_sec": round(now - row[3], 1),
            }
            for row in rows
        ]
    finally:
        connection.close()

print(json.dumps({"now": now, "sending": output}, indent=2, sort_keys=True))
