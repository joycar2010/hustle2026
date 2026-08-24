#!/usr/bin/env python3
"""Read-only logical comparison of legacy and account-scoped MT5 WALs."""

import hashlib
import json
import sqlite3
from pathlib import Path


INSTANCES = {
    "s1": Path(r"D:\QHCELL\pool\s1\inst"),
    "s3": Path(r"D:\QHCELL\pool\s3\inst"),
}
EXECUTION_ROOT = Path(r"D:\QHCELL\execution")
ACTIVE_STATES = {"ADMITTED", "PENDING", "CLAIMED", "SENDING"}
CORE_COLUMNS = (
    "request_id",
    "state",
    "result",
    "created_at",
    "updated_at",
    "op",
    "intent_hash",
    "payload",
    "admitted_at_ns",
    "claimed_at_ns",
    "started_at_ns",
    "completed_at_ns",
)


def load_env(path):
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        values[name] = value.strip().strip("'").strip('"')
    return values


def database_snapshot(path):
    uri = "file:%s?mode=ro" % path.resolve().as_posix()
    connection = sqlite3.connect(uri, uri=True)
    try:
        present = {
            row[1] for row in connection.execute("PRAGMA table_info(order_requests)")
        }
        selected = [name for name in CORE_COLUMNS if name in present]
        query = "SELECT %s FROM order_requests ORDER BY request_id" % ",".join(
            selected
        )
        rows = []
        for values in connection.execute(query):
            raw = dict(zip(selected, values))
            rows.append({name: raw.get(name) for name in CORE_COLUMNS})
    finally:
        connection.close()
    encoded = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    states = {}
    for row in rows:
        state = row.get("state")
        states[state] = states.get(state, 0) + 1
    summary = {
        "path": str(path),
        "rows": len(rows),
        "active": [
            row["request_id"]
            for row in rows
            if row.get("state") in ACTIVE_STATES
        ],
        "states": states,
        "digest": hashlib.sha256(encoded).hexdigest(),
    }
    return summary, {row["request_id"]: row for row in rows}


def compare_rows(source_rows, target_rows):
    source_ids = set(source_rows)
    target_ids = set(target_rows)
    changed_fields = {}
    examples = []
    for request_id in sorted(source_ids & target_ids):
        source = source_rows[request_id]
        target = target_rows[request_id]
        fields = sorted(
            name
            for name in set(source) | set(target)
            if source.get(name) != target.get(name)
        )
        if not fields:
            continue
        for name in fields:
            changed_fields[name] = changed_fields.get(name, 0) + 1
        if len(examples) < 20:
            examples.append(
                {
                    "request_id": request_id,
                    "state": source.get("state"),
                    "fields": fields,
                }
            )
    return {
        "source_only": sorted(source_ids - target_ids)[:20],
        "target_only": sorted(target_ids - source_ids)[:20],
        "changed_rows": sum(changed_fields.values()) and len(
            [
                request_id
                for request_id in source_ids & target_ids
                if source_rows[request_id] != target_rows[request_id]
            ]
        ),
        "changed_fields": changed_fields,
        "examples": examples,
    }


def main():
    output = []
    safe = True
    for name, root in INSTANCES.items():
        environment = load_env(root / ".env")
        identity = "%s|%s" % (
            environment["MT5_SERVER"].strip().lower(),
            environment["MT5_LOGIN"].strip(),
        )
        fence_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        source = Path(environment.get("IDEMPOTENCY_DB") or root / "idempotency.db")
        target = EXECUTION_ROOT / (fence_key + ".db")
        source_summary, source_rows = database_snapshot(source)
        target_summary, target_rows = database_snapshot(target)
        equal = source_summary["digest"] == target_summary["digest"]
        row = {
            "name": name,
            "equal": equal,
            "source": source_summary,
            "target": target_summary,
            "difference": compare_rows(source_rows, target_rows),
        }
        output.append(row)
        safe = (
            safe
            and equal
            and not source_summary["active"]
            and not target_summary["active"]
        )
    print(json.dumps({"safe_to_reuse": safe, "instances": output}, sort_keys=True))
    raise SystemExit(0 if safe else 3)


if __name__ == "__main__":
    main()
