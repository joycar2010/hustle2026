"""Read-only daily FIFO PnL projection for dashboard history.

The trading store remains the accounting authority. This batches its exit and
remaining-settlement lot rules into one snapshot instead of replaying all
orders separately for each displayed day.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import threading
import time

_cache: dict[tuple, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _project_rows(buys, exits, resolutions, *, today: float, offset_hours: float) -> list[dict]:
    lots = {}
    queues = defaultdict(list)
    for row in buys:
        lot = dict(row)
        lot['remaining'] = float(lot['size'] or 0.)
        lot['price'] = float(lot['price'] or 0.)
        lot['asset'] = str(lot['asset'] or 'BTC')
        lots[lot['id']] = lot
        queues[(lot['condition_id'], lot['token_id'], lot['side'])].append(lot)
    # Per-lot, per-day sums are essential: two partial exits on the same day
    # count as one result, while a later settlement belongs to its own day.
    amounts = defaultdict(dict)
    shift = offset_hours * 3600.
    oldest = today - 364 * 86400.

    def record(ts: float, lot, pnl: float):
        if not oldest < ts <= today + 86400.:
            return
        # Match the existing store's (cutoff, end] boundary exactly, including
        # an event timestamped precisely at Beijing midnight.
        start = (math.ceil((ts + shift) / 86400.) - 1) * 86400. - shift
        bucket = amounts[start]
        bucket[lot['id']] = bucket.get(lot['id'], 0.) + pnl

    cursors = defaultdict(int)
    for row in exits:
        key = (row['condition_id'], row['token_id'], str(row['side'] or '').removeprefix('SELL_'))
        queue = queues.get(key, [])
        cursor = cursors[key]
        remaining = float(row['size'] or 0.)
        price = float(row['price'] or 0.)
        while remaining > 0 and cursor < len(queue):
            lot = queue[cursor]
            allocated = min(lot['remaining'], remaining)
            lot['remaining'] -= allocated
            remaining -= allocated
            if allocated > 0:
                record(float(row['ts'] or 0.), lot, allocated * (price - lot['price']))
            if lot['remaining'] <= 0:
                cursor += 1
        cursors[key] = cursor
    for lot in lots.values():
        resolution = resolutions.get(lot['condition_id'])
        if lot['remaining'] <= .02 or resolution is None:
            continue
        payoff = 1. if lot['token_id'] == resolution['winning_token'] else 0.
        record(float(resolution['resolved_ts'] or 0.), lot, lot['remaining'] * (payoff - lot['price']))
    result = []
    for start in sorted(amounts, reverse=True):
        lot_pnl = amounts[start]
        assets = {}
        for lot_id, pnl in lot_pnl.items():
            asset = lots[lot_id]['asset']
            bucket = assets.setdefault(asset, {'pnl_usd': 0., 'wins': 0, 'losses': 0})
            bucket['pnl_usd'] += pnl
            bucket['wins' if pnl >= 0 else 'losses'] += 1
        for bucket in assets.values():
            bucket['pnl_usd'] = round(bucket['pnl_usd'], 4)
        result.append({'day': time.strftime('%Y-%m-%d', time.gmtime(start + shift)),
                       'pnl_usd': round(sum(lot_pnl.values()), 4),
                       'wins': sum(pnl >= 0 for pnl in lot_pnl.values()),
                       'losses': sum(pnl < 0 for pnl in lot_pnl.values()),
                       'by_asset': assets})
    return result


def daily_rows(db_path: Path, dry_run: bool, *, offset_hours: float = 8., now: float | None = None) -> list[dict]:
    """Return up to 365 Beijing days; refresh even settled days after 2s.

    Late resolutions or corrections invalidate naturally. Use one read-only
    transaction so concurrent fills cannot produce a mixed accounting frame.
    """
    path = Path(db_path).resolve()
    asof = time.time() if now is None else now
    today = ((asof + offset_hours * 3600.) // 86400.) * 86400. - offset_hours * 3600.
    key = (str(path), bool(dry_run), offset_hours, today)
    with _lock:
        tick = time.monotonic()
        cached = _cache.get(key)
        if cached and tick - cached[0] < 2.:
            return cached[1]
        statuses = ('dry_run',) if dry_run else ('filled', 'matched')
        exit_statuses = ('exit_dry_run',) if dry_run else ('exit_filled', 'exit_matched', 'exit_partial')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2.)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN')
            buys = conn.execute(
                'SELECT id,ts,condition_id,token_id,side,size,price,COALESCE(asset,\'BTC\') AS asset FROM orders '
                f'WHERE status IN ({",".join("?" for _ in statuses)}) AND side IN (\'UP\',\'DOWN\') AND dry_run=? '
                'ORDER BY condition_id,token_id,ts,id', (*statuses, int(dry_run))).fetchall()
            exits = conn.execute(
                'SELECT ts,condition_id,token_id,side,size,price FROM orders '
                f'WHERE status IN ({",".join("?" for _ in exit_statuses)}) AND side LIKE \'SELL_%\' AND dry_run=? '
                'ORDER BY condition_id,token_id,ts,id', (*exit_statuses, int(dry_run))).fetchall()
            resolutions = {row['condition_id']: row for row in conn.execute(
                'SELECT condition_id,winning_token,resolved_ts FROM resolutions').fetchall()}
        result = _project_rows(buys, exits, resolutions, today=today, offset_hours=offset_hours)
        if len(_cache) >= 8:
            _cache.clear()
        _cache[key] = (time.monotonic(), result)
        return result
