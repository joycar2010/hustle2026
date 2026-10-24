"""In-place patch #15: sports/weather paper persistence + editable paper
capital + daily PnL history API.

- Sports: simulated orders from SportsPaperService now land in the REAL
  ledger (orders, dry_run=1, asset='SPORTS'), deduped per market, so the
  existing resolver/by-asset/PnL pipeline covers them.
- Weather: when weather markets exist, a minimal edge rule (|model - price|
  >= 0.10) books $1 paper entries (asset='WEATHER'), env-gated by
  WEATHER_PAPER_TRADING (default on).  Dormant while no markets match.
- PUT /api/settings/risk gains paper_equity_usd (the simulated capital base).
- GET /api/pnl/daily?lane&offset&limit -- per-UTC-day settled entry PnL.

Anchored, uniqueness-checked, idempotent.
Usage:  python3 patch_dashboard15.py <path>
"""
from __future__ import annotations

import sys

HELPERS = '''from bot import store


def _paper_entry_logged(condition_id: str) -> bool:
    try:
        return store.has_executed_order(condition_id, True)
    except Exception:
        return True  # fail closed: never double-log


def _persist_sports_paper(snapshot) -> None:
    """Copy the sports service's simulated orders into the real paper ledger
    so resolution/PnL/by-asset all treat them like any other dry-run entry."""
    try:
        get = lambda o, k, d=None: o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)
        markets = {get(m, "market_key"): m for m in (get(snapshot, "markets", []) or [])}
        for o in (get(snapshot, "orders", []) or []):
            cid = str(get(o, "market_key") or "")
            token = str(get(o, "token_id") or "")
            price = float(get(o, "price") or 0)
            size = float(get(o, "size") or 0)
            slug = str(get(o, "slug") or "")
            if not cid or not token or not (0 < price < 1) or size <= 0:
                continue
            if _paper_entry_logged(cid):
                continue
            m = markets.get(cid)
            tokens = list(get(m, "clob_token_ids", []) or []) if m is not None else []
            side = "UP" if (tokens and str(tokens[0]) == token) else "DOWN"
            store.log_order(asset="SPORTS", market_slug=slug, condition_id=cid,
                            token_id=token, side=side, size=size, price=price,
                            order_id=None, status="dry_run", filled_size=0.0,
                            entry_rule="sports_paper", dry_run=True)
            store.log_decision(asset="SPORTS", market_slug=slug, condition_id=cid,
                               token_id=token, side=side, t_remaining=0.0,
                               ask_price=price, ask_size=None, action="BUY",
                               reason=f"sports paper {get(o, 'outcome', '')} "
                                      f"edge entry @ {price}", dry_run=True)
    except Exception:
        pass  # persistence must never break the sports poller


_WEATHER_PAPER_ENABLED = os.environ.get(
    "WEATHER_PAPER_TRADING", "true").strip().lower() in ("1", "true", "yes", "on")
_WEATHER_PAPER_MIN_EDGE = 0.10


def _maybe_weather_paper_entry(market, signal) -> None:
    """Book a $1 paper entry when the ensemble model disagrees with the
    market by >= 10 cents.  Runs inside the weather snapshot loop; dormant
    while no weather markets match."""
    if not _WEATHER_PAPER_ENABLED:
        return
    try:
        model_yes = float(getattr(signal, "model_yes_probability", None) or 0.0)
        yes_price = float(getattr(market, "yes_price", 0) or 0)
        no_price = float(getattr(market, "no_price", 0) or 0)
        cid = str(getattr(market, "condition_id", "") or "")
        slug = str(getattr(market, "slug", "") or "")
        if not cid or _paper_entry_logged(cid):
            return
        pick = None
        if 0.02 < yes_price < 0.95 and model_yes - yes_price >= _WEATHER_PAPER_MIN_EDGE:
            pick = ("UP", str(getattr(market, "yes_token", "")), yes_price, model_yes - yes_price)
        elif 0.02 < no_price < 0.95 and (1.0 - model_yes) - no_price >= _WEATHER_PAPER_MIN_EDGE:
            pick = ("DOWN", str(getattr(market, "no_token", "")), no_price, (1.0 - model_yes) - no_price)
        if pick is None:
            return
        side, token, price, edge = pick
        if not token:
            return
        size = round(1.0 / price, 4)  # $1 notional
        store.log_order(asset="WEATHER", market_slug=slug, condition_id=cid,
                        token_id=token, side=side, size=size, price=price,
                        order_id=None, status="dry_run", filled_size=0.0,
                        entry_rule="weather_paper", dry_run=True)
        store.log_decision(asset="WEATHER", market_slug=slug, condition_id=cid,
                           token_id=token, side=side, t_remaining=0.0,
                           ask_price=price, ask_size=None, action="BUY",
                           reason=f"weather ensemble edge {edge:+.2f} @ {price}",
                           dry_run=True)
    except Exception:
        pass


@app.get("/api/pnl/daily")
def pnl_daily(lane: str = "paper", offset: int = 0, limit: int = 14):
    """Per-UTC-day settled ENTRY PnL for one lane, newest day first."""
    lane = lane if lane in ("paper", "live") else "paper"
    offset = max(0, min(int(offset), 3650))
    limit = max(1, min(int(limit), 60))
    dry = 1 if lane == "paper" else 0
    statuses = "('dry_run')" if dry else "('filled','matched')"
    base_where = (
        f"o.dry_run={dry} AND o.status IN {statuses} "
        "AND o.side IN ('UP','DOWN') AND o.price>0 AND o.price<1"
    )
    shares = ("(CASE WHEN o.dry_run=0 THEN COALESCE(o.filled_size, o.size*o.price)/o.price "
              "ELSE o.size END)")
    stake = ("(CASE WHEN o.dry_run=0 THEN COALESCE(o.filled_size, o.size*o.price) "
             "ELSE o.size*o.price END)")
    rows_out: list[dict[str, Any]] = []
    total_days = 0
    try:
        with db() as c:
            total_days = int(c.execute(
                "SELECT COUNT(DISTINCT date(r.resolved_ts,'unixepoch')) "
                "FROM orders o JOIN resolutions r ON r.condition_id=o.condition_id "
                f"WHERE {base_where}").fetchone()[0])
            for r in c.execute(
                "SELECT date(r.resolved_ts,'unixepoch') AS day, "
                f"SUM(CASE WHEN o.token_id=r.winning_token THEN {shares}*(1-o.price) "
                f"ELSE -{stake} END) AS pnl, "
                "SUM(o.token_id=r.winning_token) AS wins, "
                "SUM(o.token_id!=r.winning_token) AS losses "
                "FROM orders o JOIN resolutions r ON r.condition_id=o.condition_id "
                f"WHERE {base_where} GROUP BY day ORDER BY day DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ):
                rows_out.append({"day": r[0], "pnl_usd": round(r[1] or 0.0, 4),
                                 "wins": int(r[2] or 0), "losses": int(r[3] or 0)})
    except Exception:
        pass
    if lane == "paper":
        capital = float(getattr(cfg, "paper_equity_usd", 100.0))
    else:
        capital = float(_state.get("balance_pusd") or 0.0)
    return {"lane": lane, "rows": rows_out, "total_days": total_days,
            "offset": offset, "limit": limit,
            "capital_base_usd": round(capital, 4)}


@app.get("/api/orders")'''

E = [
    ('@app.get("/api/orders")', HELPERS),
    ('            _state["sports_meta"] = snapshot',
     '            _state["sports_meta"] = snapshot\n'
     '            _persist_sports_paper(snapshot)'),
    ('            signal = build_signal(cfg, market, forecast)',
     '            signal = build_signal(cfg, market, forecast)\n'
     '            _maybe_weather_paper_entry(market, signal)'),
    ('    if not changes:',
     '    if body.get("paper_equity_usd") is not None:\n'
     '        equity = max(10.0, min(100000.0, float(body["paper_equity_usd"])))\n'
     '        changes["PAPER_EQUITY_USD"] = f"{equity:g}"\n'
     '        try:\n'
     '            cfg.paper_equity_usd = equity\n'
     '        except Exception:\n'
     '            object.__setattr__(cfg, "paper_equity_usd", equity)\n'
     '        note.append(f"模拟本金=${equity:g}")\n'
     '    if not changes:'),
]


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_persist_sports_paper" in src:
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
