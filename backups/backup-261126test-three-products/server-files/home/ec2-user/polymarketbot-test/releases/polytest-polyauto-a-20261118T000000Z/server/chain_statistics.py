"""Pure projections of Polymarket financial snapshots and confirmed activity."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math

BEIJING = timezone(timedelta(hours=8))
ACTIVITY_TYPES = {"TRADE", "REDEEM", "MERGE", "SPLIT"}


def read_account_pages(get, endpoint, params, timeout=8, max_pages=50):
    """Only publish complete keyset walks, including nested v2 cursors."""
    records, seen = [], set()
    params = dict(params)
    for _ in range(max_pages):
        response = get(endpoint, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise ValueError("invalid account page")
        records.extend(batch)
        pagination = payload.get("pagination") or {}
        if not isinstance(pagination, dict):
            raise ValueError("invalid account pagination")
        next_cursor = payload.get("next_cursor") or pagination.get("next_cursor")
        has_more = payload.get("has_more", pagination.get("has_more"))
        if has_more is False or (not has_more and not next_cursor):
            return records
        if not batch or not next_cursor or next_cursor in seen:
            raise ValueError("incomplete account pagination")
        seen.add(next_cursor)
        params["cursor"] = next_cursor
    raise ValueError("account history exceeds pagination bound")


def number(row, *keys):
    for key in keys:
        raw = row.get(key)
        if raw is None or raw == "" or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None


def day_of(ts):
    return datetime.fromtimestamp(ts, BEIJING).strftime("%Y-%m-%d")


def confirmed_activity(rows):
    """Discard intents and duplicate cursor-page records, preserving real fills."""
    seen = set()
    result = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").upper()
        ts = number(raw, "timestamp", "ts")
        if kind not in ACTIVITY_TYPES or ts is None or ts <= 0 or raw.get("error"):
            continue
        status = str(raw.get("status") or "").upper()
        if any(word in status for word in ("ERROR", "FAIL", "CANCEL", "REJECT", "PENDING", "UNCONFIRMED")):
            continue
        tx = raw.get("transaction_hash") or raw.get("transactionHash") or raw.get("tx")
        # Include the full payload so distinct fills sharing a transaction survive.
        key = json.dumps(raw, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        item = dict(raw, type=kind, timestamp=ts, transaction_hash=tx)
        item["condition_id"] = raw.get("condition_id") or raw.get("conditionId") or raw.get("slug") or ""
        item["token_id"] = raw.get("token_id") or raw.get("tokenId") or ""
        item["usdc_size"] = number(raw, "usdc_size", "usdcSize", "amount_usd", "amount")
        result.append(item)
    return sorted(result, key=lambda row: row["timestamp"], reverse=True)


def cashflow(row):
    amount = number(row, "usdc_size", "usdcSize", "amount_usd", "amount")
    if amount is None:
        return None
    kind = row["type"]
    if kind in ("REDEEM", "MERGE"):
        return amount
    if kind == "SPLIT":
        return -amount
    side = str(row.get("side") or "").upper()
    return amount if side == "SELL" else -amount if side == "BUY" else None


def position_outcomes(positions, activity):
    """Count one official, fee-inclusive CLOSED result per market.

    The positions API handles fee-denominated share dust. Activity alone
    cannot distinguish that dust from an open holding or value a losing
    token which was never redeemed. Do not invent results when it is absent.
    """
    if positions is None:
        return None
    groups, tokens = {}, {}
    for row in positions:
        condition, token = row.get("condition_id"), str(row.get("token_id") or "")
        ts, pnl = number(row, "last_event_at"), number(row, "total_pnl")
        if str(row.get("status")).upper() != "CLOSED" or not condition or not token or not ts or pnl is None:
            continue
        key = (condition, token)
        if key not in tokens or ts > number(tokens[key], "last_event_at"):
            tokens[key] = row
    for (condition, token), row in tokens.items():
        group = groups.setdefault(condition, {"condition_id": condition, "cash": 0., "ts": 0., "complete": True})
        group["cash"] += number(row, "total_pnl")
        group["ts"] = max(group["ts"], number(row, "last_event_at"))
    for row in confirmed_activity(activity):
        condition = row["condition_id"]
        if condition not in groups:
            continue
        position = tokens.get((condition, str(row["token_id"])))
        # A newer buy/exit means the position index has not caught up. A
        # partial market (one closed side, another still open) is excluded.
        if row["type"] == "TRADE" and (position is None or row["timestamp"] > number(position, "last_event_at")):
            groups[condition]["complete"] = False
    return [group for group in groups.values() if group["complete"]]


def coherent_points(points, stats):
    """Use the newest source block, even when a forward-filled hour is later."""
    ordered = sorted([dict(p) for p in points if isinstance(p, dict) and (number(p, "timestamp") or 0) > 0], key=lambda p: p["timestamp"])
    latest = ordered[-1] if ordered else {}
    stats = stats if isinstance(stats, dict) else {}
    if number(stats, "economic_pnl") is None or not number(stats, "timestamp"):
        return ordered, "user-pnl"
    stats_block = number(stats, "source_block")
    last_block = number(latest, "source_block")
    use_stats = not latest or ((stats_block >= last_block) if stats_block and last_block
                              else stats["timestamp"] >= latest["timestamp"])
    if use_stats:
        # An interpolated later timestamp must not override a newer chain block.
        ordered = [p for p in ordered if p["timestamp"] < stats["timestamp"]]
        ordered.append(dict(stats))
        return ordered, "user-stats"
    return ordered, "user-pnl"


def rebate_total(point):
    values = [number(point, key) for key in ("maker_rebate", "taker_rebate", "fees_refunded")]
    return sum(value for value in values if value is not None) if any(value is not None for value in values) else None


def financial_source_timestamp(point, points):
    """Expose the first observed time of an identical source block/value.

    The official history can forward-fill an unchanged source block to later
    hourly timestamps. Those labels are not evidence of a new chain sample.
    """
    if not point:
        return None
    stamp = number(point, "timestamp")
    fields = ("source_block", "economic_pnl", "trade_pnl", "fees", "fees_paid", "maker_rebate", "taker_rebate", "fees_refunded")
    identity = tuple(number(point, key) for key in fields)
    return min((number(candidate, "timestamp") for candidate in points
                if number(candidate, "timestamp") is not None and number(candidate, "timestamp") <= stamp
                and tuple(number(candidate, key) for key in fields) == identity), default=stamp)


def daily_financials(points, activity, now, markets=None, initial_baseline_known=False):
    """Keep financial deltas separate from the faster confirmed activity counts."""
    activity = confirmed_activity(activity)
    outcomes = defaultdict(lambda: {"wins": 0, "losses": 0, "trades": 0, "redemptions": 0, "trade_cashflow_usd": 0.})
    for group in markets or []:
        bucket = outcomes[day_of(group["ts"])]
        if group["cash"] > 0.0000005:
            bucket["wins"] += 1
        elif group["cash"] < -0.0000005:
            bucket["losses"] += 1
    for event in activity:
        bucket = outcomes[day_of(event["timestamp"])]
        if event["type"] == "TRADE":
            bucket["trades"] += 1
        elif event["type"] in ("REDEEM", "MERGE"):
            bucket["redemptions"] += 1
        bucket["trade_cashflow_usd"] += cashflow(event) or 0.
    ordered = sorted((point for point in points if number(point, "timestamp") is not None),
                     key=lambda point: point["timestamp"])
    last_by_day = {}
    for point in ordered:
        last_by_day[day_of(point["timestamp"])] = point
    days = sorted(set(last_by_day) | set(outcomes) | {day_of(now)})
    result = []
    for day in days:
        start = datetime.fromisoformat(day).replace(tzinfo=BEIJING).timestamp()
        end_ts = min(start + 86400., now)
        current = next((point for point in reversed(ordered) if start <= point["timestamp"] <= end_ts), None)
        previous = next((point for point in reversed(ordered) if point["timestamp"] <= start), None)
        # The earliest returned cumulative point may already contain years of
        # activity. Nonempty history is not evidence of a zero opening balance.
        explicit_zero = previous is None and initial_baseline_known
        baseline_ts = number(previous or {}, "timestamp")
        as_of = number(current or {}, "timestamp")
        baseline_source_ts = financial_source_timestamp(previous, ordered)
        data_source_ts = financial_source_timestamp(current, ordered)
        coverage = ("complete" if baseline_ts == start and as_of == end_ts
                    and baseline_source_ts == start and data_source_ts == end_ts
                    else "partial" if previous is not None or explicit_zero else "unavailable")
        item = dict(outcomes[day])
        if markets is None:
            item.update(wins=None, losses=None)

        def delta(*keys, total=None):
            getter = total or (lambda obj: number(obj, *keys))
            value = getter(current) if current else None
            old = getter(previous) if previous else 0. if initial_baseline_known else None
            return round(value - old, 6) if value is not None and old is not None else None

        trade = delta("trade_pnl")
        economic = delta("economic_pnl")
        fees = delta("fees", "fees_paid")
        rebates = delta(total=rebate_total)
        item.update(day=day, trade_pnl_usd=trade, economic_pnl_usd=economic, net_pnl_usd=economic,
                    fees_usd=fees, maker_fee_usd=delta("maker_fee"), taker_fee_usd=delta("taker_fee"),
                    maker_rebate_usd=delta("maker_rebate"), taker_rebate_usd=delta("taker_rebate"),
                    fees_refunded_usd=delta("fees_refunded"), rebates_usd=rebates,
                    data_as_of=number(current or {}, "timestamp"),
                    period_start_ts=start, period_end_ts=end_ts,
                    baseline_ts=baseline_ts, baseline_source_block=number(previous or {}, "source_block"),
                    data_source_block=number(current or {}, "source_block"),
                    baseline_source_ts=baseline_source_ts, data_source_ts=data_source_ts,
                    baseline_kind="explicit_zero" if explicit_zero else "official_snapshot" if previous else "unknown",
                    coverage=coverage, baseline_exact=baseline_ts == start,
                    source="data_api_v2_user_pnl", fee_status="official_signed_fee_total",
                    other_income_usd=round(economic - trade - fees - (rebates or 0.), 6)
                    if all(value is not None for value in (economic, trade, fees)) else None)
        item["trade_cashflow_usd"] = round(item["trade_cashflow_usd"], 6)
        result.append(item)
    return list(reversed(result))


def live_statistics(points, stats, activity, now, source_fidelity=None, positions=None, activity_available=True):
    points, selected = coherent_points(points, stats)
    latest = points[-1] if points else {}
    markets = position_outcomes(positions, activity)
    daily = daily_financials(points, activity, now, markets=markets, initial_baseline_known=False)
    if not activity_available:
        for row in daily:
            row.update(trades=None, redemptions=None, trade_cashflow_usd=None)
    today = next((row for row in daily if row["day"] == day_of(now)), {})
    today_markets = [item for item in markets or [] if day_of(item["ts"]) == day_of(now)]
    economic = number(latest, "economic_pnl")
    fees = number(latest, "fees", "fees_paid")
    as_of = number(latest, "timestamp")
    activities = confirmed_activity(activity)
    activity_ts = max((row["timestamp"] for row in activities), default=None)
    result = {
        "available": economic is not None, "source": "data_api_v2_user_pnl_activity",
        "financial_source": "v2/" + selected, "source_fidelity": source_fidelity,
        "realized_usd": economic, "economic_usd": economic, "trade_pnl_usd": number(latest, "trade_pnl"),
        "fees_usd": fees, "fees_source": "v2/" + selected,
        "maker_rebate_usd": number(latest, "maker_rebate"), "taker_rebate_usd": number(latest, "taker_rebate"),
        "today_realized_usd": today.get("economic_pnl_usd"),
        "today_economic_pnl_usd": today.get("economic_pnl_usd"),
        "today_trade_pnl_usd": today.get("trade_pnl_usd"),
        "today_fees_usd": today.get("fees_usd"), "today_rebates_usd": today.get("rebates_usd"),
        "wins": sum(item["cash"] > 0.0000005 for item in markets) if markets is not None else None,
        "losses": sum(item["cash"] < -0.0000005 for item in markets) if markets is not None else None,
        "today_wins": sum(item["cash"] > 0.0000005 for item in today_markets) if markets is not None else None,
        "today_losses": sum(item["cash"] < -0.0000005 for item in today_markets) if markets is not None else None,
        "markets": len(markets) if markets is not None else None,
        "today_markets": len(today_markets) if markets is not None else None,
        "outcomes_source": "v2/positions?status=CLOSED", "outcomes_available": markets is not None,
        "trade_count": int(number(latest, "trade_count") or 0),
        "activity_count": len(activities) if activity_available else None, "activity_as_of": activity_ts,
        "today_activity_count": sum(day_of(row["timestamp"]) == day_of(now) for row in activities) if activity_available else None,
        "activity_ahead_of_pnl": bool(activity_ts and as_of and activity_ts > as_of),
        "data_as_of": as_of, "last_update_ts": as_of,
        "stats_updated_ts": number(stats or {}, "timestamp"), "data_age_sec": max(0., now - as_of) if as_of else None,
        "updated_at": now, "stale": economic is None or bool(as_of and now - as_of > 7200),
        "daily_rows": daily,
        "fee_breakdown": {
            "total_usd": fees, "maker_fee_usd": number(latest, "maker_fee"), "taker_fee_usd": number(latest, "taker_fee"),
            "maker_rebate_usd": number(latest, "maker_rebate"), "taker_rebate_usd": number(latest, "taker_rebate"),
            "fees_refunded_usd": number(latest, "fees_refunded"), "rebates_usd": rebate_total(latest),
            "classification": "upstream_roles_unavailable",
        },
        "rolling_24h_usd": None, "rolling_24h_base_ts": None, "rolling_24h_updated_ts": as_of,
    }
    if as_of and economic is not None:
        baseline = next((p for p in reversed(points) if p["timestamp"] <= as_of - 86400), None)
        if baseline and number(baseline, "economic_pnl") is not None:
            result["rolling_24h_usd"] = round(economic - number(baseline, "economic_pnl"), 6)
            result["rolling_24h_base_ts"] = baseline["timestamp"]
    return result


def summarize_activity_period(rows, start_ts=None, end_ts=None, positions=None, points=None, now=None):
    """Project one requested interval, never a pagination window.

    ``rows`` must be the complete, confirmed account activity after fee
    enrichment. Activity cash amounts already include trading fees. Fees are
    disclosed separately and MUST NOT be subtracted from cashflow again.
    ``positions`` is an optional full official CLOSED-position snapshot;
    its market lifetime results are grouped by their closing timestamp.
    Official financial deltas retain both boundary timestamps so a stale or
    missing financial baseline cannot masquerade as a complete live result.
    """
    now = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    requested_start = float(start_ts) if start_ts is not None else None
    requested_end = float(end_ts) if end_ts is not None else None
    effective_end = min(requested_end, now) if requested_end is not None else now
    if requested_start is not None and requested_end is not None and requested_start >= requested_end:
        raise ValueError("start_ts must precede end_ts")
    confirmed = confirmed_activity(rows)
    # Preserve enrichment by a stable event key instead of assuming the input
    # sequence has already been filtered or is in any particular page order.
    enriched = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("transaction_hash") or row.get("transactionHash") or ""),
               number(row, "timestamp", "ts"), str(row.get("token_id") or row.get("tokenId") or ""),
               str(row.get("side") or "").upper(), number(row, "size"),
               str(row.get("activity_type") or row.get("type") or "").upper())
        enriched[key] = row
    selected = []
    for row in confirmed:
        if requested_start is not None and row["timestamp"] < requested_start:
            continue
        if row["timestamp"] >= effective_end:
            continue
        key = (str(row.get("transaction_hash") or ""), row["timestamp"], row["token_id"],
               str(row.get("side") or "").upper(), number(row, "size"), row["type"])
        selected.append({**row, **enriched.get(key, {})})
    start = requested_start if requested_start is not None else min((row["timestamp"] for row in selected), default=None)
    trades = [row for row in selected if str(row.get("activity_type") or row.get("type")).upper() == "TRADE"]
    fees = [number(row, "fee_usd") for row in trades if row.get("fee_status") == "confirmed"
            and number(row, "fee_usd") is not None]
    missing_fees = len(trades) - len(fees)
    cash = [number(row, "cashflow_usd") if number(row, "cashflow_usd") is not None else cashflow(row)
            for row in selected]
    result = {
        "start_ts": start, "end_ts": effective_end,
        "requested_start_ts": requested_start, "requested_end_ts": requested_end,
        "timezone": "Asia/Shanghai", "records": len(selected), "trades": len(trades),
        "redemptions": sum(row["type"] in ("REDEEM", "MERGE") for row in selected),
        "buy_cash_paid_usd": round(sum(-(value or 0.) for row, value in zip(selected, cash)
                                        if row["type"] == "TRADE" and str(row.get("side")).upper() == "BUY"), 6),
        "sell_cash_received_usd": round(sum(value or 0. for row, value in zip(selected, cash)
                                             if row["type"] == "TRADE" and str(row.get("side")).upper() == "SELL"), 6),
        "redeem_cash_received_usd": round(sum(value or 0. for row, value in zip(selected, cash)
                                               if row["type"] in ("REDEEM", "MERGE")), 6),
        "net_cashflow_usd": round(sum(value or 0. for value in cash), 6),
        "cashflow_fee_inclusive": True, "fees_usd": round(sum(fees), 6) if fees or not trades else None,
        "fee_confirmed": len(fees), "fee_total_trades": len(trades), "fee_pending": missing_fees,
        "fees_complete": missing_fees == 0,
        "activity_as_of": max((row["timestamp"] for row in selected), default=None),
        "updated_at": now, "quick_closed_pnl_usd": None, "quick_closed_markets": None,
        "quick_closed_as_of": None, "quick_closed_scope": "market_lifetime_grouped_by_close_time",
        "official_economic_pnl_usd": None, "official_trade_pnl_usd": None, "official_fees_usd": None,
        "official_rebates_usd": None, "official_baseline_ts": None, "official_baseline_source_block": None,
        "official_data_as_of": None, "official_data_source_block": None, "official_coverage": "unavailable",
        "official_baseline_source_ts": None, "official_data_source_ts": None,
    }
    groups = position_outcomes(positions, rows)
    if groups is not None:
        closed = [group for group in groups if (start is None or group["ts"] >= start) and group["ts"] < effective_end]
        result.update(quick_closed_pnl_usd=round(sum(group["cash"] for group in closed), 6),
                      quick_closed_markets=len(closed), quick_closed_as_of=max((group["ts"] for group in closed), default=None))
    ordered = sorted((point for point in points or [] if number(point, "timestamp") is not None),
                     key=lambda point: point["timestamp"])
    baseline = next((point for point in reversed(ordered) if start is not None and point["timestamp"] <= start), None)
    current = next((point for point in reversed(ordered) if point["timestamp"] <= effective_end), None)
    if current:
        result.update(official_data_as_of=number(current, "timestamp"),
                      official_data_source_block=number(current, "source_block"),
                      official_data_source_ts=financial_source_timestamp(current, ordered))
    if baseline:
        result.update(official_baseline_ts=number(baseline, "timestamp"),
                      official_baseline_source_block=number(baseline, "source_block"),
                      official_baseline_source_ts=financial_source_timestamp(baseline, ordered))
    if baseline and current and start is not None and current["timestamp"] >= start:
        for field, keys in (("official_economic_pnl_usd", ("economic_pnl",)),
                            ("official_trade_pnl_usd", ("trade_pnl",)),
                            ("official_fees_usd", ("fees", "fees_paid"))):
            old, new = number(baseline, *keys), number(current, *keys)
            if old is not None and new is not None:
                result[field] = round(new - old, 6)
        old, new = rebate_total(baseline), rebate_total(current)
        if old is not None and new is not None:
            result["official_rebates_usd"] = round(new - old, 6)
        result["official_coverage"] = ("complete" if baseline["timestamp"] == start and current["timestamp"] == effective_end
                                       and result["official_baseline_source_ts"] == start
                                       and result["official_data_source_ts"] == effective_end
                                       else "partial")
    return result
