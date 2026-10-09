"""In-place patch #7: exit-netted paper positions + ledger totals.

Root cause fixed here: patch #6's paper-position queries counted ENTRY rows
without subtracting paper EXITS, resurrecting long-closed positions as
"stale pending" ghosts.  The store's own semantics (remaining = size -
exit_size > 0.02) are now replicated, so the modal, the open value and the
headline pending agree again -- no ledger rows are deleted.

Also adds `decisions_total` / `orders_total` (MAX(id), 2s cache) so the
bottom bar can show real ledger totals instead of the response-window caps.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard7.py <path>
"""
from __future__ import annotations

import sys

OLD_OPEN_SQL = (
    '                    "SELECT COUNT(*), COALESCE(SUM(COALESCE(size,0)*COALESCE(price,0)),0) "\n'
    '                    "FROM orders o WHERE o.dry_run=1 AND o.status=\'dry_run\' "\n'
    '                    "AND o.side IN (\'UP\',\'DOWN\') AND NOT EXISTS "\n'
    '                    "(SELECT 1 FROM resolutions r WHERE r.condition_id=o.condition_id)"'
)
NEW_OPEN_SQL = (
    '                    "SELECT COUNT(*), COALESCE(SUM((o.size-COALESCE(x.exit_size,0))*o.price),0) "\n'
    '                    "FROM orders o LEFT JOIN (SELECT condition_id, token_id, dry_run, "\n'
    '                    "SUM(size) AS exit_size FROM orders WHERE status=\'exit_dry_run\' "\n'
    '                    "GROUP BY condition_id, token_id, dry_run) x "\n'
    '                    "ON x.condition_id=o.condition_id AND x.token_id=o.token_id AND x.dry_run=o.dry_run "\n'
    '                    "WHERE o.dry_run=1 AND o.status=\'dry_run\' AND o.side IN (\'UP\',\'DOWN\') "\n'
    '                    "AND NOT EXISTS (SELECT 1 FROM resolutions r WHERE r.condition_id=o.condition_id) "\n'
    '                    "AND o.size-COALESCE(x.exit_size,0) > 0.02"'
)

OLD_ROWS_SQL = (
    '                    "SELECT ts, market_slug, COALESCE(asset,\'BTC\') AS asset, side, "\n'
    '                    "size, price FROM orders o WHERE o.dry_run=1 AND o.status=\'dry_run\' "\n'
    '                    "AND o.side IN (\'UP\',\'DOWN\') AND NOT EXISTS "\n'
    '                    "(SELECT 1 FROM resolutions r WHERE r.condition_id=o.condition_id) "\n'
    '                    "ORDER BY ts DESC LIMIT 50"'
)
NEW_ROWS_SQL = (
    '                    "SELECT o.ts, o.market_slug, COALESCE(o.asset,\'BTC\') AS asset, o.side, "\n'
    '                    "o.size-COALESCE(x.exit_size,0) AS size, o.price FROM orders o "\n'
    '                    "LEFT JOIN (SELECT condition_id, token_id, dry_run, SUM(size) AS exit_size "\n'
    '                    "FROM orders WHERE status=\'exit_dry_run\' GROUP BY condition_id, token_id, dry_run) x "\n'
    '                    "ON x.condition_id=o.condition_id AND x.token_id=o.token_id AND x.dry_run=o.dry_run "\n'
    '                    "WHERE o.dry_run=1 AND o.status=\'dry_run\' AND o.side IN (\'UP\',\'DOWN\') "\n'
    '                    "AND NOT EXISTS (SELECT 1 FROM resolutions r WHERE r.condition_id=o.condition_id) "\n'
    '                    "AND o.size-COALESCE(x.exit_size,0) > 0.02 ORDER BY o.ts DESC LIMIT 50"'
)

TOTALS_HELPER = '''

_ledger_totals_cache: dict[str, Any] = {"ts": 0.0, "decisions": 0, "orders": 0}


def _ledger_totals() -> dict[str, int]:
    """Real ledger totals (MAX id) for the bottom bar, 2s cached."""
    now = time.time()
    if now - _ledger_totals_cache["ts"] > 2.0:
        try:
            with db() as c:
                d = c.execute("SELECT COALESCE(MAX(id),0) FROM decisions").fetchone()[0]
                o = c.execute("SELECT COALESCE(MAX(id),0) FROM orders").fetchone()[0]
            _ledger_totals_cache.update(ts=now, decisions=int(d), orders=int(o))
        except Exception:
            _ledger_totals_cache["ts"] = now
    return {"decisions": _ledger_totals_cache["decisions"],
            "orders": _ledger_totals_cache["orders"]}
'''

E = [
    (OLD_OPEN_SQL, NEW_OPEN_SQL),
    (OLD_ROWS_SQL, NEW_ROWS_SQL),
    ('    return _paper_open_cache["n"], _paper_open_cache["usd"]',
     '    return _paper_open_cache["n"], _paper_open_cache["usd"]' + TOTALS_HELPER),
    ('        "paper_positions": _paper_positions(),',
     '        "paper_positions": _paper_positions(),\n'
     '        "decisions_total": _ledger_totals()["decisions"],\n'
     '        "orders_total": _ledger_totals()["orders"],'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_ledger_totals" in src:
        print("already patched; nothing to do")
        return 0
    for i, (old, _new) in enumerate(E):
        if src.count(old) != 1:
            print(f"ABORT: anchor #{i} count={src.count(old)} (need 1)")
            return 2
    for old, new in E:
        src = src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
