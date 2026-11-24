"""Read-only accounting for isolated BTC/SOL Paper ledgers.

Net PnL is authoritative on positions.pnl_net_usd. Execution-price slippage
is a disclosure, never a second deduction. Daily realized history is assigned
to the Beijing date on which the position was settled. Open inventory is
valued at execution cost; this is a simulation ledger, not a chain valuation.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BJ = timezone(timedelta(hours=8))
SOURCE = "btc_sol_isolated_paper_ledgers"


def num(value: Any) -> float:
    try:
        number = float(value or 0.0)
        return number if math.isfinite(number) else 0.0
    except (ValueError, TypeError):
        return 0.0


def positive(value: Any) -> Optional[float]:
    number = num(value)
    return number if number > 0 else None


def day_key(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), BJ).strftime("%Y-%m-%d")


def position_net(row: dict[str, Any]) -> Optional[float]:
    if row.get("pnl_net_usd") is not None:
        return num(row["pnl_net_usd"])
    if row.get("pnl_usd") is not None:
        return num(row["pnl_usd"]) - abs(num(row.get("fee_usd")))
    return None


def public_capital(path: Path, asset: str, db_path: Path) -> tuple[Optional[float], str]:
    """Use only an exported effective config bound to the exact ledger path."""
    try:
        item = json.loads(Path(path).read_text(encoding="utf-8"))["products"][asset]
        if Path(item["db_path"]).resolve() != Path(db_path).resolve():
            return None, "ledger_config_mismatch"
        capital = positive(item.get("capital_base_usd"))
        return capital, str(item.get("source") or "verified_worker_config")
    except (OSError, ValueError, TypeError, KeyError):
        return None, "effective_paper_capital_unavailable"


def _blank(asset: str, capital: Optional[float]) -> dict[str, Any]:
    return {"asset": asset, "realized_usd": 0.0, "pnl_usd": 0.0,
        "gross_pnl_usd": 0.0, "trade_pnl_usd": 0.0, "fees_usd": 0.0,
        "fee_usd": 0.0, "net_pnl_usd": 0.0, "economic_pnl_usd": 0.0,
        "slippage_usd": 0.0, "rebate_usd": 0.0, "rebates_usd": 0.0,
        "maker_fee_usd": 0.0, "taker_fee_usd": 0.0,
        "maker_rebate_usd": 0.0, "taker_rebate_usd": 0.0,
        "wins": 0, "losses": 0, "flats": 0, "trades": 0, "settled": 0,
        "pending": 0, "capital_base_usd": capital, "return_rate": None,
        "return_pct": None, "win_rate_pct": None,
        "fees_source": "paper_position_ledger", "fee_status": "paper_model",
        "valuation": "entry_cost", "daily_basis": "beijing_settlement_date",
        "slippage_included_in_execution_price": True}


def _finish(item: dict[str, Any]) -> dict[str, Any]:
    item["realized_usd"] = item["net_pnl_usd"]
    item["economic_pnl_usd"] = item["net_pnl_usd"]
    capital = positive(item.get("capital_base_usd"))
    item["return_rate"] = item["return_pct"] = (
        item["net_pnl_usd"] / capital * 100 if capital is not None else None)
    outcomes = item["wins"] + item["losses"]
    item["win_rate_pct"] = item["wins"] / outcomes * 100 if outcomes else None
    return item


def read_product(path: Path, asset: str, capital: Optional[float],
                 now: Optional[float] = None) -> dict[str, Any]:
    """Read positions once, normalize product IDs and settled/open economics."""
    now = time.time() if now is None else now
    asset = asset.upper()
    capital = positive(capital)
    result: dict[str, Any] = {"asset": asset, "source": SOURCE, "db_path": str(path),
        "available": False, "stale": False, "error": None, "updated_at": now,
        "positions": [], "settled_positions": [], "daily_rows": [],
        "capital_base_usd": capital, "capital_complete": capital is not None,
        "open_value_usd": 0.0, "open_fees_usd": 0.0,
        "valuation": "entry_cost", "slippage_included_in_execution_price": True}
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            raw_positions = [dict(row) for row in connection.execute(
                "SELECT * FROM positions WHERE dry_run=1 ORDER BY id")]
            # Do not rescan the large decision/events table for every state
            # frame. Fill notes retain the original quoted price for older
            # Paper fills, whose slippage column sometimes stayed zero.
            fills = [dict(row) for row in connection.execute(
                "SELECT * FROM fills WHERE dry_run=1 ORDER BY id")]
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        result.update(stale=True, error=str(exc))
        raw_positions, fills = [], []
    else:
        result["available"] = True
    if not result["available"]:
        unknown = _blank(asset, capital)
        for key in list(unknown):
            if key not in {"asset", "capital_base_usd", "valuation", "daily_basis", "slippage_included_in_execution_price", "fees_source", "fee_status"}:
                unknown[key] = None
        result.update(cumulative_summary=dict(unknown), today_summary={"day": day_key(now), **unknown},
            cumulative_net_pnl_usd=None, cumulative_realized_usd=None, cumulative_fees_usd=None,
            cumulative_wins=None, cumulative_losses=None, cumulative_win_rate_pct=None,
            today_net_pnl_usd=None, today_realized_usd=None, pending=None, wins=None, losses=None,
            fees_usd=None, cash_usd=None, equity_usd=None)
        return result
    fill_by_position = defaultdict(list)
    for fill in fills:
        matches = [p for p in raw_positions if p["market_slug"] == fill["market_slug"]
            and p["token_id"] == fill["token_id"] and p["side"] == fill["side"]]
        if matches:
            p = min(matches, key=lambda p: abs(num(p["opened_ts"]) - num(fill["ts"])))
            if abs(num(p["opened_ts"]) - num(fill["ts"])) <= 5.0:
                fill_by_position[p["id"]].append(fill)
    days: dict[str, dict[str, Any]] = {}
    total = _blank(asset, capital)
    for position in raw_positions:
        p = dict(position)
        matched_fills = fill_by_position.get(p["id"], [])
        slippage = sum(abs(num(f.get("slippage_usd"))) for f in matched_fills)
        quoted_price = None
        if matched_fills:
            quoted = re.search(r"(?:UP|DOWN)@([0-9.]+)", str(matched_fills[0].get("note") or ""))
            quoted_price = num(quoted.group(1)) if quoted else None
        if not slippage and quoted_price is not None:
            slippage = abs(num(p["entry_price"]) - quoted_price) * num(p["size"])
        fee = -abs(num(p.get("fee_usd")))
        net = position_net(p)
        settled = p.get("status") == "closed" and p.get("closed_ts") is not None and net is not None
        row = {**p, "asset": asset, "product": asset + "5M",
            "record_key": f"paper:{asset.lower()}:position:{p['id']}",
            "ts": num(p["opened_ts"]), "opened_ts": num(p["opened_ts"]),
            "price": num(p["entry_price"]), "remaining_size": num(p["size"]),
            "notional_usd": num(p["size"]) * num(p["entry_price"]),
            "gross_pnl_usd": p.get("pnl_usd"), "pnl_net_usd": net, "net_pnl_usd": net,
            "fee_usd": fee, "fees_usd": fee, "slippage_usd": -slippage,
            "quoted_price": quoted_price, "settled": settled,
            "source": SOURCE, "slippage_included_in_execution_price": True}
        if not settled:
            result["positions"].append(row)
            result["open_value_usd"] += row["notional_usd"]
            result["open_fees_usd"] += abs(fee)
            continue
        result["settled_positions"].append(row)
        key = day_key(p["closed_ts"])
        daily = days.setdefault(key, {"day": key, **_blank(asset, capital)})
        gross = num(p.get("pnl_usd"))
        for item in (daily, total):
            item["pnl_usd"] += gross
            item["gross_pnl_usd"] += gross
            item["trade_pnl_usd"] += gross
            item["fees_usd"] += fee
            item["fee_usd"] += fee
            item["net_pnl_usd"] += net
            item["slippage_usd"] -= slippage
            item["maker_fee_usd" if p.get("liquidity") == "maker" else "taker_fee_usd"] += fee
            # Preserve the existing BTC dashboard outcome convention: zero
            # settled net PnL counts in the non-loss/win bucket.
            item["wins" if net >= 0 else "losses"] += 1
            item["trades"] += 1
            item["settled"] += 1
    result["positions"].sort(key=lambda row: row["opened_ts"], reverse=True)
    result["settled_positions"].sort(key=lambda row: num(row["closed_ts"]), reverse=True)
    today = day_key(now)
    total["pending"] = len(result["positions"])
    result["cumulative_summary"] = _finish(total)
    result["daily_rows"] = [_finish(row) for row in sorted(days.values(), key=lambda row: row["day"], reverse=True)]
    result["today_summary"] = next((row for row in result["daily_rows"] if row["day"] == today),
        _finish({"day": today, **_blank(asset, capital)}))
    result["today_summary"] = {**result["today_summary"], "pending": total["pending"]}
    result["cash_usd"] = capital + total["net_pnl_usd"] - result["open_value_usd"] - result["open_fees_usd"] if capital else None
    result["equity_usd"] = capital + total["net_pnl_usd"] - result["open_fees_usd"] if capital else None
    result.update(cumulative_net_pnl_usd=total["net_pnl_usd"],
        cumulative_realized_usd=total["net_pnl_usd"], cumulative_fees_usd=total["fees_usd"],
        cumulative_wins=total["wins"], cumulative_losses=total["losses"],
        cumulative_win_rate_pct=total["win_rate_pct"], today_net_pnl_usd=result["today_summary"]["net_pnl_usd"],
        today_realized_usd=result["today_summary"]["net_pnl_usd"], pending=total["pending"],
        wins=result["today_summary"]["wins"], losses=result["today_summary"]["losses"],
        fees_usd=total["fees_usd"])
    return result


ADDITIVE = ("pnl_usd", "gross_pnl_usd", "trade_pnl_usd", "fees_usd", "fee_usd", "net_pnl_usd",
    "slippage_usd", "rebate_usd", "rebates_usd", "maker_fee_usd", "taker_fee_usd", "maker_rebate_usd",
    "taker_rebate_usd", "wins", "losses", "flats", "trades", "settled", "pending")


def merge_products(products: dict[str, dict[str, Any]], now: Optional[float] = None) -> dict[str, Any]:
    """Combine independent Paper allocations, preserving per-product detail."""
    now = time.time() if now is None else now
    capitals = {key: positive(p.get("capital_base_usd")) for key, p in products.items()}
    complete = bool(capitals) and all(v is not None for v in capitals.values())
    capital = sum(v for v in capitals.values() if v is not None) if complete else None
    total = _blank("ALL", capital)
    for product in products.values():
        summary = product["cumulative_summary"]
        for key in ADDITIVE:
            total[key] += num(summary[key])
    _finish(total)
    today = day_key(now)
    keys = sorted({r["day"] for p in products.values() for r in p["daily_rows"]}, reverse=True)
    days = []
    for day in keys:
        row = {"day": day, **_blank("ALL", capital), "by_asset": {}}
        for asset, product in products.items():
            per_asset = next((r for r in product["daily_rows"] if r["day"] == day),
                _finish({"day": day, **_blank(asset, capitals[asset])}))
            row["by_asset"][asset] = per_asset
            for key in ADDITIVE:
                row[key] += per_asset[key]
        days.append(_finish(row))
    positions = sorted([row for p in products.values() for row in p["positions"]], key=lambda r: r["opened_ts"], reverse=True)
    settled = sorted([row for p in products.values() for row in p["settled_positions"]], key=lambda r: num(r["closed_ts"]), reverse=True)
    current = next((r for r in days if r["day"] == today), {"day": today, **_finish(_blank("ALL", capital))})
    current = {**current, "pending": len(positions), "by_asset": {key: p["today_summary"] for key, p in products.items()}}
    open_value = sum(p["open_value_usd"] for p in products.values())
    open_fees = sum(p["open_fees_usd"] for p in products.values())
    result = {"asset": "ALL", "source": SOURCE, "available": all(p["available"] for p in products.values()),
        "stale": any(p["stale"] for p in products.values()), "updated_at": now,
        "error": "; ".join(f"{k}: {p['error']}" for k,p in products.items() if p.get("error")) or None,
        "positions": positions, "settled_positions": settled, "capital_base_usd": capital,
        "capital_by_asset": capitals, "capital_complete": complete, "capital_basis": "sum_of_independent_configured_paper_allocations",
        "daily_basis": "beijing_settlement_date", "valuation": "entry_cost",
        "slippage_included_in_execution_price": True,
        "cumulative_summary": total, "today_summary": current, "daily_rows": days,
        "cumulative_by_asset": {key: p["cumulative_summary"] for key,p in products.items()},
        "by_asset": {key: p["today_summary"] for key,p in products.items()},
        "open_value_usd": open_value, "open_fees_usd": open_fees,
        "cash_usd": capital + total["net_pnl_usd"] - open_value - open_fees if capital else None,
        "equity_usd": capital + total["net_pnl_usd"] - open_fees if capital else None,
        "cumulative_net_pnl_usd": total["net_pnl_usd"], "cumulative_realized_usd": total["net_pnl_usd"],
        "cumulative_gross_pnl_usd": total["gross_pnl_usd"], "cumulative_fees_usd": total["fees_usd"],
        "cumulative_wins": total["wins"], "cumulative_losses": total["losses"],
        "cumulative_win_rate_pct": total["win_rate_pct"], "today_net_pnl_usd": current["net_pnl_usd"],
        "today_realized_usd": current["net_pnl_usd"], "wins": current["wins"], "losses": current["losses"],
        "pending": len(positions), "fees_usd": total["fees_usd"]}
    if not result["available"]:
        # A missing product must never be represented as zero profit or zero
        # holdings. The caller can retain a previous good snapshot instead.
        unknown_fields = (*ADDITIVE, "realized_usd", "economic_pnl_usd", "return_rate", "return_pct", "win_rate_pct")
        for row in [total, current, *days]:
            row.update({key: None for key in unknown_fields})
        for key in ("cash_usd", "equity_usd", "cumulative_net_pnl_usd", "cumulative_realized_usd",
                    "cumulative_gross_pnl_usd", "cumulative_fees_usd", "cumulative_wins", "cumulative_losses",
                    "cumulative_win_rate_pct", "today_net_pnl_usd", "today_realized_usd", "wins", "losses", "pending", "fees_usd",
                    "open_value_usd", "open_fees_usd"):
            result[key] = None
    return result
