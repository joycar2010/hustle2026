#!/usr/bin/env python3
"""Bridge native btc5m Paper records into the legacy polytest Paper ledger.

The native engine owns execution and settlement.  This process only mirrors
read-only Paper facts into the old dashboard schema, so the live service and
its database are never opened or modified.
"""
from __future__ import annotations
import json, os, sqlite3, time
from pathlib import Path

NATIVE_DB = Path(os.environ.get("NATIVE_DB", "/home/ec2-user/polymarketbot-test/state/paper-native-a/data/paper.db"))
LEGACY_DB = Path(os.environ.get("LEGACY_DB", "/home/ec2-user/polymarketbot-test/state/paper-a/trades.db"))
STATE = Path(os.environ.get("BRIDGE_STATE", "/home/ec2-user/polymarketbot-test/state/paper-native-a/bridge-state.json"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT, market_slug TEXT,
 condition_id TEXT, token_id TEXT, side TEXT, t_remaining REAL, ask_price REAL,
 ask_size REAL, action TEXT, reason TEXT, dry_run INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT, market_slug TEXT,
 condition_id TEXT, token_id TEXT, side TEXT, size REAL, price REAL, order_id TEXT,
 status TEXT, filled_size REAL, error TEXT, entry_rule TEXT, dry_run INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS resolutions (
 condition_id TEXT PRIMARY KEY, winning_token TEXT, resolved_ts REAL);
CREATE TABLE IF NOT EXISTS execution_audits (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, asset TEXT, market_slug TEXT,
 condition_id TEXT, token_id TEXT, lane TEXT, event TEXT NOT NULL,
 payload_json TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0);
"""

def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"event": 0, "fill": 0, "position": 0}

def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, sort_keys=True))
    os.replace(tmp, STATE)

def native_conn():
    # Read-only URI prevents this sidecar from ever changing native state.
    return sqlite3.connect(f"file:{NATIVE_DB}?mode=ro", uri=True, timeout=5)

def run_once():
    if not NATIVE_DB.exists():
        return 0
    st = load_state()
    n = native_conn(); n.row_factory = sqlite3.Row
    l = sqlite3.connect(LEGACY_DB, timeout=10); l.row_factory = sqlite3.Row
    l.execute("PRAGMA busy_timeout=10000"); l.executescript(SCHEMA)
    # Keep old deployments readable while exposing native execution economics.
    for name, typ in (("fee_usd", "REAL"), ("slippage_usd", "REAL"),
                      ("liquidity", "TEXT"), ("net_pnl_usd", "REAL"),
                      ("native_position_id", "INTEGER")):
        try: l.execute(f"ALTER TABLE orders ADD COLUMN {name} {typ}")
        except sqlite3.OperationalError: pass
    count = 0
    # Repair rows written by older bridge versions (which used filled_size=0)
    # without touching the native execution database.
    for row in n.execute("SELECT id,size,fee_usd,slippage_usd,liquidity FROM fills WHERE dry_run=1"):
        l.execute("UPDATE orders SET filled_size=?, fee_usd=?, slippage_usd=?, liquidity=? WHERE order_id=?",
                  (float(row['size']), float(row['fee_usd'] or 0.0), float(row['slippage_usd'] or 0.0), row['liquidity'] or 'taker', f"native-fill:{row['id']}"))
    # Decisions are copied for the existing dashboard decision stream.
    for row in n.execute("SELECT id,ts,market_slug,payload FROM events WHERE kind='decision' AND id>? ORDER BY id", (int(st.get('event',0)),)):
        try: p = json.loads(row['payload'])
        except Exception: p = {}
        side = p.get('side') or ''
        price = p.get('price')
        if price is None:
            price = p.get('up_ask') if side == 'UP' else p.get('down_ask') if side == 'DOWN' else None
        # Find token/condition from a native fill for this market where possible.
        ref = n.execute("SELECT condition_id,token_id FROM fills WHERE market_slug=? ORDER BY id LIMIT 1", (row['market_slug'],)).fetchone()
        cond = ref['condition_id'] if ref else ''
        token = ref['token_id'] if ref else ''
        marker = f"native-event:{row['id']}"
        exists = l.execute("SELECT 1 FROM decisions WHERE reason LIKE ? LIMIT 1", (marker+'%',)).fetchone()
        if not exists:
            l.execute("INSERT INTO decisions(ts,asset,market_slug,condition_id,token_id,side,t_remaining,ask_price,ask_size,action,reason,dry_run) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                      (float(row['ts']), 'BTC', row['market_slug'], cond, token, side, p.get('t_left'), price, p.get('size'), p.get('action') or 'SKIP', marker+' '+str(p.get('reason') or 'native decision')))
            count += 1
        st['event'] = max(int(st.get('event',0)), int(row['id']))
    # Native fills are authoritative Paper entries.
    for row in n.execute("SELECT * FROM fills WHERE dry_run=1 AND id>? ORDER BY id", (int(st.get('fill',0)),)):
        oid = f"native-fill:{row['id']}"
        exists = l.execute("SELECT 1 FROM orders WHERE order_id=? LIMIT 1", (oid,)).fetchone()
        if not exists:
            l.execute("INSERT INTO orders(ts,asset,market_slug,condition_id,token_id,side,size,price,order_id,status,filled_size,error,entry_rule,dry_run,fee_usd,slippage_usd,liquidity) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                      (float(row['ts']), 'BTC', row['market_slug'], row['condition_id'], row['token_id'], row['side'], float(row['size']), float(row['price']), oid, 'dry_run', float(row['size']), None, row['note'] or 'native btc5m Paper', float(row['fee_usd'] or 0.0), float(row['slippage_usd'] or 0.0), row['liquidity'] or 'taker'))
            count += 1
        else:
            l.execute("UPDATE orders SET filled_size=?, fee_usd=?, slippage_usd=?, liquidity=? WHERE order_id=?",
                      (float(row['size']), float(row['fee_usd'] or 0.0), float(row['slippage_usd'] or 0.0), row['liquidity'] or 'taker', oid))
        st['fill'] = max(int(st.get('fill',0)), int(row['id']))
    # Closed native positions produce the legacy resolution marker.
    known_closed = set()
    for existing in l.execute("SELECT payload_json FROM execution_audits WHERE event='native_resolution' AND dry_run=1"):
        try: known_closed.add(int(json.loads(existing['payload_json'])['position_id']))
        except (ValueError, TypeError, KeyError): pass
    for row in n.execute("SELECT * FROM positions WHERE dry_run=1 AND status='closed' AND closed_ts IS NOT NULL ORDER BY id"):
        winner = row['token_id'] if float(row['exit_price'] or 0) >= 0.999 else f"__native_other__:{row['condition_id']}"
        l.execute("INSERT OR REPLACE INTO resolutions(condition_id,winning_token,resolved_ts) VALUES(?,?,?)", (row['condition_id'], winner, float(row['closed_ts'])))
        if int(row['id']) not in known_closed:
            l.execute("INSERT INTO execution_audits(ts,asset,market_slug,condition_id,token_id,lane,event,payload_json,dry_run) VALUES(?,?,?,?,?,?,?,?,1)",
                      (float(row['closed_ts']), 'BTC', row['market_slug'], row['condition_id'], row['token_id'], 'paper', 'native_resolution', json.dumps({'position_id':row['id'],'winner':winner,'pnl_net_usd':row['pnl_net_usd'],'fee_usd':row['fee_usd']})))
            count += 1
        fill = n.execute("SELECT id FROM fills WHERE dry_run=1 AND market_slug=? AND token_id=? AND ABS(ts-?)<=5 ORDER BY ABS(ts-?) LIMIT 1",
                         (row['market_slug'], row['token_id'], row['opened_ts'], row['opened_ts'])).fetchone()
        if fill:
            l.execute("UPDATE orders SET net_pnl_usd=?, native_position_id=? WHERE order_id=? AND dry_run=1",
                      (row['pnl_net_usd'], row['id'], f"native-fill:{fill['id']}"))
        st['position'] = max(int(st.get('position',0)), int(row['id']))
    l.commit(); l.close(); n.close(); save_state(st)
    return count

def main():
    while True:
        try:
            c = run_once()
            if c: print(f"bridged {c} native Paper rows", flush=True)
        except Exception as exc:
            print(f"bridge error: {exc!r}", flush=True)
        time.sleep(float(os.environ.get('BRIDGE_INTERVAL_SEC','3')))

if __name__ == '__main__': main()
