#!/usr/bin/env python3
"""Read-only P2 audit for production BTC Paper and the P1 Paper A/B lanes."""
from __future__ import annotations
import bisect, datetime as dt, hashlib, importlib.util, json, os, sqlite3, statistics, time, urllib.request
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/home/ec2-user/polymarketbot-auto')
BASE = Path('/home/ec2-user/paper-ab/20261026T110000Z')
OUT = BASE / 'audit'
OUT.mkdir(parents=True, exist_ok=True)
TZ = ZoneInfo('Asia/Shanghai')
UTC = dt.timezone.utc
PROD_DB = ROOT / 'trades-auto.db'


def ro_context(path: Path):
    @contextmanager
    def cm():
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        try:
            yield conn
        finally:
            conn.close()
    return cm


def store_for(db_path: Path):
    code = BASE / 'A' / 'bot' / 'store.py'
    spec = importlib.util.spec_from_file_location('p2_store_' + hashlib.sha1(str(db_path).encode()).hexdigest()[:10], code)
    if spec is None or spec.loader is None:
        raise RuntimeError('store module unavailable')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH = db_path
    mod.db = ro_context(db_path)
    return mod


def manifest_for(db_path: Path) -> dict:
    p = db_path.parent / 'runtime-manifest.json'
    try:
        x = json.loads(p.read_text(encoding='utf-8'))
        return {k: x.get(k) for k in ('profile','started_at','config_hash','paper_run_id','paper_variant','timezone')}
    except (OSError, ValueError):
        return {}


def day_bounds(days: int = 7):
    now = dt.datetime.now(TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for n in range(days):
        start = today - dt.timedelta(days=n)
        yield start.timestamp(), (start + dt.timedelta(days=1)).timestamp(), start.date().isoformat()


def binance_5m():
    cache = OUT / 'binance-5m-cache.json'
    try:
        cached = json.loads(cache.read_text(encoding='utf-8'))
        if time.time() - float(cached.get('fetched_at', 0)) < 240 and cached.get('klines'):
            return cached['klines'], 'cache'
    except (OSError, ValueError, TypeError):
        pass
    end = int(time.time() * 1000)
    start = end - 1500 * 300000
    url = f'https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&startTime={start}&endTime={end}&limit=1500'
    with urllib.request.urlopen(url, timeout=15) as response:
        rows = json.load(response)
    cache.write_text(json.dumps({'fetched_at': time.time(), 'klines': rows}, separators=(',', ':')), encoding='utf-8')
    return rows, 'live'


def forward_alignment(conn, cutoff: float, end: float, candles):
    if not candles:
        return {'orders': 0, 'available': 0}
    opens = [int(r[0]) for r in candles]
    out = []
    rows = conn.execute("SELECT ts, side FROM orders WHERE dry_run=1 AND asset='BTC' AND status='dry_run' AND side IN ('UP','DOWN') AND ts>=? AND ts<?", (cutoff, end)).fetchall()
    for row in rows:
        i = bisect.bisect_right(opens, int(float(row['ts']) * 1000)) - 1
        if i < 0:
            continue
        vals = []
        for offset in (1, 3, 6):
            j = i + offset
            vals.append(float(candles[j][4]) / float(candles[i][4]) - 1.0 if j < len(candles) else None)
        out.append((str(row['side']), vals))
    metrics = {'orders': len(rows), 'available': len(out)}
    for label, idx in (('5m', 0), ('15m', 1), ('30m', 2)):
        q = [(side, vals[idx]) for side, vals in out if vals[idx] is not None]
        if not q:
            metrics[label] = {'count': 0}
            continue
        favorable = sum(1 for side, value in q if (side == 'UP' and value > 0) or (side == 'DOWN' and value < 0))
        metrics[label] = {'count': len(q), 'favorable_pct': round(favorable / len(q) * 100.0, 2), 'avg_forward_pct': round(statistics.mean(v for _, v in q) * 100.0, 4)}
    return metrics


def audit_lane(label: str, db_path: Path, candles):
    result = {'lane': label, 'db_path': str(db_path), 'manifest': manifest_for(db_path), 'days': [], 'integrity': None}
    try:
        with ro_context(db_path)() as conn:
            result['integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
            store = store_for(db_path)
            manifest = result['manifest']
            run_started = float(manifest.get('started_at') or 0) if manifest.get('started_at') else 0.0
            if label in ('paper_a', 'paper_b'):
                try:
                    raw_start = json.loads((BASE / 'P1_WINDOW.json').read_text(encoding='utf-8')).get('started_at', run_started)
                    run_started = dt.datetime.fromisoformat(str(raw_start).replace('Z', '+00:00')).timestamp() if isinstance(raw_start, str) else float(raw_start)
                except (OSError, ValueError, TypeError):
                    pass
            for start, end, day in day_bounds(7):
                measurement_start = max(start, run_started) if day == dt.datetime.now(TZ).date().isoformat() and run_started else start
                summary = store.realized_pnl_summary_today(True, cutoff=measurement_start, end=end, asset='BTC')
                params = ('BTC', measurement_start, end)
                buys = int(conn.execute("SELECT COUNT(*) FROM orders WHERE dry_run=1 AND asset=? AND status='dry_run' AND side IN ('UP','DOWN') AND ts>=? AND ts<?", params).fetchone()[0])
                exits = int(conn.execute("SELECT COUNT(*) FROM orders WHERE dry_run=1 AND asset=? AND side LIKE 'SELL_%' AND ts>=? AND ts<?", params).fetchone()[0])
                stops = int(conn.execute("SELECT COUNT(*) FROM orders WHERE dry_run=1 AND asset=? AND side LIKE 'SELL_%' AND ts>=? AND ts<? AND (status LIKE 'exit_%' OR error LIKE '%held-side exit%')", params).fetchone()[0])
                decisions = int(conn.execute("SELECT COUNT(*) FROM decisions WHERE asset=? AND ts>=? AND ts<?", params).fetchone()[0])
                skips = int(conn.execute("SELECT COUNT(*) FROM decisions WHERE asset=? AND action LIKE 'SKIP_RISK%' AND ts>=? AND ts<?", params).fetchone()[0])
                stale = int(conn.execute("SELECT COUNT(*) FROM decisions WHERE asset=? AND ts>=? AND ts<? AND (reason LIKE '%stale%' OR reason LIKE '%过期%')", params).fetchone()[0])
                avg_t = conn.execute("SELECT AVG(t_remaining) FROM decisions WHERE asset=? AND action='BUY' AND ts>=? AND ts<?", params).fetchone()[0]
                if not (buys or exits or decisions or abs(float(summary.get('realized_usd') or 0.0)) > 1e-9):
                    continue
                result['days'].append({'day': day, 'measurement_start_ts': measurement_start, 'pnl_usd': round(float(summary.get('realized_usd') or 0.0), 4), 'wins': int(summary.get('wins') or 0), 'losses': int(summary.get('losses') or 0), 'pending': int(summary.get('pending') or 0), 'buy_count': buys, 'exit_count': exits, 'stop_exit_count': stops, 'decision_count': decisions, 'skip_risk_count': skips, 'stale_signal_count': stale, 'avg_entry_t_remaining_sec': round(float(avg_t), 2) if avg_t is not None else None, 'binance_proxy': forward_alignment(conn, measurement_start, end, candles)})
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    return result


def main():
    try:
        candles, source = binance_5m()
    except Exception as exc:
        candles, source = [], f'error:{type(exc).__name__}'
    lanes = {'production': PROD_DB, 'paper_a': BASE / 'A' / 'ab.db', 'paper_b': BASE / 'B' / 'ab.db'}
    report = {'schema_version': 'p2-paper-ab-audit-v1', 'generated_at': dt.datetime.now(UTC).isoformat(), 'timezone': 'Asia/Shanghai', 'mode': 'paper', 'live_enabled': False, 'binance_source': source, 'lanes': {}}
    for name, path in lanes.items():
        if path.is_file():
            report['lanes'][name] = audit_lane(name, path, candles)
    report['p2_metrics'] = ['net_pnl_usd', 'win_loss', 'stop_exit_rate', 'avg_entry_t_remaining_sec', 'skip_risk_count', 'stale_signal_count', 'binance_proxy_forward_5m_15m_30m', 'config_hash', 'db_integrity']
    tmp = OUT / 'audit-latest.json.tmp'
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, OUT / 'audit-latest.json')
    history = OUT / 'history'; history.mkdir(exist_ok=True)
    stamp = dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    (history / f'{stamp}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(OUT / 'audit-latest.json'), 'lanes': list(report['lanes']), 'binance_source': source}, ensure_ascii=False))

if __name__ == '__main__': main()