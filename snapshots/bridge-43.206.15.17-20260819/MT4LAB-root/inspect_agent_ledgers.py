import glob
import json
import os
import sqlite3


def rows_for(path, limit=12):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(order_requests)")
        }
        selected = [
            name
            for name in ("request_id", "state", "result", "op", "created_at", "updated_at")
            if name in columns
        ]
        rows = connection.execute(
            "SELECT " + ",".join(selected)
            + " FROM order_requests ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    output = []
    for raw in rows:
        row = dict(raw)
        request_id = row.get("request_id")
        state = row.get("state")
        result = row.get("result")
        op = row.get("op")
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        try:
            parsed = json.loads(result) if result else None
        except Exception:
            parsed = result
        output.append(
            {
                "request_id": request_id,
                "state": state,
                "op": op,
                "created_at": created_at,
                "updated_at": updated_at,
                "elapsed_ms": (
                    round((updated_at - created_at) * 1000, 1)
                    if created_at is not None and updated_at is not None
                    else None
                ),
                "result": parsed,
            }
        )
    return output


def main():
    paths = sorted(glob.glob(r"D:\MT4LAB\agent\ledger_qhcell-m[1-4].db"))
    report = {os.path.basename(path): rows_for(path) for path in paths}
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
