"""Read product-tagged Paper fills, strategy decisions and signals from the execution ledgers."""
import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

from server.paper_product_accounting import fill_direction, match_position_fills, position_net

BJ = timezone(timedelta(hours=8))
_counts = {}
_count_lock = threading.Lock()


def decision_counts(p):
    today = datetime.now(BJ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    try:
        with _count_lock, closing(connection(p)) as c:
            c.execute("BEGIN")
            latest = c.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            previous_id, total, daily, day = _counts.get(p.key, (0, 0, 0, today))
            if day != today or previous_id > latest:
                previous_id, total, daily = 0, 0, 0
            if previous_id < latest:
                n, n_today = c.execute("SELECT COUNT(*), COUNT(CASE WHEN ts>=? THEN 1 END) "
                                       "FROM events WHERE id>? AND kind='decision'", (today, previous_id)).fetchone()
                total += n
                daily += n_today
            _counts[p.key] = latest, total, daily, today
            return total, daily
    except (sqlite3.Error, OSError):
        return None, None


def connection(product):
    c = sqlite3.connect(f"file:{product.ledger}?mode=ro", uri=True, timeout=1.5)
    c.row_factory = sqlite3.Row
    return c


def fills(products, offset, limit, start=None, end=None):
    # Merge each ledger's first offset+limit rows, then page the globally sorted list.
    rows = []
    missing = []
    totals = today_total = 0
    midnight = datetime.now(BJ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    for p in products:
        clause = " WHERE dry_run=1"
        args = []
        for value, term in ((start, "ts>=?"), (end, "ts<?")):
            if value is not None:
                clause += " AND " + term
                args.append(value)
        try:
            with closing(connection(p)) as c:
                c.execute("BEGIN")
                total, today = c.execute("SELECT COUNT(*), COUNT(CASE WHEN ts>=? THEN 1 END) FROM fills" + clause,
                                         [midnight, *args]).fetchone()
                totals += total
                today_total += today
                selected = list(c.execute("SELECT * FROM fills" + clause + " ORDER BY ts DESC,id DESC LIMIT ?", [*args, offset+limit]))
                # Attribute the realized outcome once per closed position. Search all fills
                # of its market even when pagination or date filtering separates buy/sell.
                selected_markets = list({r["market_slug"] for r in selected})
                realized, settled_ids = {}, set()
                for index in range(0, len(selected_markets), 400):
                    markets = selected_markets[index:index+400]
                    market_filter = " WHERE dry_run=1 AND market_slug IN (" + ",".join("?" for _ in markets) + ")"
                    peers = [dict(r) for r in c.execute("SELECT * FROM fills"+market_filter, markets)]
                    positions = [dict(r) for r in c.execute("SELECT * FROM positions"+market_filter, markets)]
                    matched = match_position_fills(positions, peers)
                    for pos in positions:
                        group = matched.get(pos["id"])
                        if not group or pos["closed_ts"] is None or pos["status"] != "closed":
                            continue
                        settled_ids.update(f["id"] for f in group)
                        last = max(group, key=lambda f:(fill_direction(f) == "SELL", f["ts"], f["id"]))
                        realized[last["id"]] = pos
                for item in selected:
                    row = dict(item)
                    pos = realized.get(row["id"])
                    settled = row["id"] in settled_ids
                    net = position_net(pos) if pos else None
                    fee = -abs(row["fee_usd"] or 0)
                    order_side = fill_direction(row)
                    rows.append({**row, **p.meta, "record_key": f"paper:{p.key}:fill:{row['id']}",
                                 "source_id": row["id"], "source": f"{p.key}-paper-ledger", "status": "filled",
                                 "cashflow_usd": abs(row["notional_usd"] or 0) * (1 if order_side == "SELL" else -1),
                                 "filled_size": row["size"], "fee_usd": fee, "fees_usd": fee,
                                 "execution_side": order_side, "entry_rule": row.get("strategy"), "error": None,
                                 "result": ("HIT" if net >= 0 else "MISS") if net is not None else ("NONE" if settled else "PENDING"),
                                 "settled": settled, "resolved_ts": pos["closed_ts"] if pos else None,
                                 "realization": ("exit" if order_side == "SELL" else "settlement") if pos else None,
                                 "gross_pnl_usd": pos["pnl_usd"] if pos else None, "pnl_usd": pos["pnl_usd"] if pos else None,
                                 "net_pnl_usd": net, "pnl_net_usd": net})
        except (sqlite3.Error, OSError):
            missing.append(p.key)
    rows.sort(key=lambda x: (x["ts"], x["product_key"], x["id"]), reverse=True)
    return {"rows": rows[offset:offset+limit], "offset": offset, "limit": limit, "total": totals,
            "today_total": today_total, "available": not missing, "unavailable_products": missing, "lane": "paper",
            "source": "product_paper_ledgers"}


def decisions(p, limit=16):
    try:
        with closing(connection(p)) as c:
            events = c.execute("SELECT id,ts,market_slug,payload FROM events WHERE kind='decision' ORDER BY id DESC LIMIT ?",
                               (limit,)).fetchall()
    except (OSError, sqlite3.Error):
        return []
    result = []
    for event in events:
        try:
            payload = json.loads(event["payload"])
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        data = {k: payload.get(k) for k in ("side", "action", "reason", "signal", "up_ask", "down_ask",
                                             "edge", "probability", "model_review")}
        result.append({**data, **p.meta, "ts": event["ts"], "id": event["id"], "market_slug": event["market_slug"],
                       "record_key": f"paper:{p.key}:decision:{event['id']}", "dry_run": 1,
                       "ask_price": payload.get("price"), "ask_size": payload.get("size"),
                       "t_remaining": payload.get("t_left")})
    return result


def signal(decision):
    probability = {"available": False, "value": None, "side": None, "ts": None, "source": None}
    review = {"available": False, "primary": None, "secondary": None, "ts": None, "source": None}
    if not decision:
        return probability, review
    # Native engine publishes its calibrated probability for the leading side as hold=...%.
    text = str(decision.get("signal") or "")
    m = re.search(r"\bhold=(\d+(?:\.\d+)?)%", text)
    direction = re.search(r"\bside=(UP|DOWN)\b", text)
    if m and direction and 0 <= float(m.group(1)) <= 100:
        probability.update(available=True, value=float(m.group(1))/100, side=direction.group(1),
                           ts=decision["ts"], source="native_lead_hold_probability")
    explicit = decision.get("probability")
    if isinstance(explicit, (float, int)) and 0 <= explicit <= 1 and decision.get("side"):
        probability.update(available=True, value=explicit, side=decision["side"],
                           ts=decision["ts"], source="native_strategy_decision")
    record = decision.get("model_review")
    if isinstance(record, dict) and ("primary" in record or "secondary" in record):
        review.update(available=True, primary=record.get("primary"), secondary=record.get("secondary"),
                      ts=decision["ts"], source="native_model_review")
    return probability, review


def details(p, account, status, orders):
    rows = decisions(p)
    probability, review = signal(rows[0] if rows else None)
    cfg = status["effective"]
    loss = cfg.get("daily_loss_limit_usd")
    target = cfg.get("daily_profit_limit_usd")
    pnl = account["today_net_pnl_usd"]
    risk_state = "UNAVAILABLE"
    if pnl is not None and status["configuration_verified"]:
        risk_state = "ACTIVE"
        if loss and pnl <= -loss:
            risk_state = "DAILY_LOSS_LIMIT"
        elif target and pnl >= target:
            risk_state = "DAILY_PROFIT_LIMIT"
    risk = {"state": risk_state, "available": risk_state != "UNAVAILABLE", "daily_loss_limit_usd": loss,
            "daily_profit_limit_usd": target, "today_net_pnl_usd": pnl, "open_value_usd": account["open_value_usd"],
            "max_open_positions": cfg.get("max_open_positions"), "pending": account["pending"]}
    # The full history is available through the paginated ledger endpoints.
    compact = {k:v for k,v in account.items() if k not in {"settled_positions", "daily_rows", "db_path"}}
    total_decisions, daily_decisions = decision_counts(p)
    return {**status, "account": compact, "config": cfg, "risk": risk, "decisions": rows,
            "probability": probability, "model_review": review, "orders": orders["rows"],
            "order_count": orders["total"], "today_order_count": orders["today_total"],
            "decision_count": total_decisions, "today_decision_count": daily_decisions}
