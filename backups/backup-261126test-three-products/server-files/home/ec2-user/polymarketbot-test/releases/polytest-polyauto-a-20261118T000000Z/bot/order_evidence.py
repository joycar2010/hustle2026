"""Pure CLOB execution evidence normalization, independent of the SDK.

An authenticated trade describes the taker's direction. A maker must be
identified through its own order leg; the aggregate trade size is never its
individual fill size.
"""
from __future__ import annotations

import math


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _id(value):
    return str(value or "").lower()


def iter_account_trade_fills(trades, *, owner_addresses=(), api_owner=None,
                             order_id=None, token_id=None, condition_id=None,
                             side=None, submitted_at=0):
    """Return deduplicated own fills, never all makers of an aggregate trade.

    A known signed order id is the strongest identity. Without it, an
    authenticated TAKER role or a matching maker wallet/API owner is required.
    For binary contracts the same-token maker has the opposite direction;
    complementary-token makers have the same direction as the taker.
    """
    wanted_order = _id(order_id)
    wanted_token = str(token_id) if token_id is not None else None
    wanted_side = str(side).upper() if side is not None else None
    wallets = {_id(value) for value in owner_addresses if value}
    own_owner = str(api_owner or "")
    fills = {}
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        if str(trade.get("status") or "").upper() not in {"MATCHED", "MINED", "CONFIRMED"}:
            continue
        market = str(trade.get("market") or trade.get("condition_id") or "")
        if not market or (condition_id is not None and _id(market) != _id(condition_id)):
            continue
        ts = number(trade.get("match_time") or trade.get("last_update"))
        if ts is None or ts < submitted_at - 3:
            continue
        top_token = str(trade.get("asset_id") or trade.get("token_id") or "")
        top_side = str(trade.get("side") or "").upper()
        role = str(trade.get("trader_side") or "").upper()
        taker_id = trade.get("taker_order_id") or trade.get("order_id")
        candidates = []
        if ((wanted_order and _id(taker_id) == wanted_order)
                or (not wanted_order and role == "TAKER")):
            candidates.append((taker_id, top_token, top_side,
                               number(trade.get("size")), number(trade.get("price")), "TAKER"))
        for maker in trade.get("maker_orders") or []:
            if not isinstance(maker, dict):
                continue
            maker_id = maker.get("order_id")
            if wanted_order:
                if _id(maker_id) != wanted_order:
                    continue
            elif not ((_id(maker.get("maker_address")) in wallets)
                      or (own_owner and str(maker.get("owner") or "") == own_owner)):
                continue
            maker_token = str(maker.get("asset_id") or maker.get("token_id") or top_token)
            maker_side = str(maker.get("side") or "").upper()
            if not maker_side:
                if wanted_order and wanted_side:
                    # The caller created this exact order with this direction.
                    maker_side = wanted_side
                elif maker_token == top_token and top_side in {"BUY", "SELL"}:
                    maker_side = "SELL" if top_side == "BUY" else "BUY"
                elif maker_token and top_token and top_side in {"BUY", "SELL"}:
                    maker_side = top_side
            candidates.append((maker_id, maker_token, maker_side,
                               number(maker.get("matched_amount")),
                               number(maker.get("price")), "MAKER"))
        for own_id, token, own_side, size, price, own_role in candidates:
            if (not own_id or not token or own_side not in {"BUY", "SELL"}
                    or (wanted_token is not None and token != wanted_token)
                    or (wanted_side is not None and own_side != wanted_side)):
                continue
            if size is None or size <= 0 or price is None or not 0 < price <= 1:
                continue
            trade_key = trade.get("id") or trade.get("trade_id")
            if not trade_key:
                trade_key = (trade.get("transaction_hash") or trade.get("transactionHash"), ts, size, price)
            key = (str(trade_key), _id(own_id), token, own_side)
            value = {"order_id": str(own_id), "token_id": token, "side": own_side,
                     "size": size, "price": price, "amount": size * price,
                     "ts": ts, "liquidity_role": own_role, "trade": trade,
                     "condition_id": market, "trade_id": str(trade_key),
                     "status": str(trade.get("status")).upper()}
            prior = fills.get(key)
            if prior is None or size > prior["size"]:
                fills[key] = value
    return sorted(fills.values(), key=lambda fill: fill["ts"])


def own_trade_legs(trades, *, condition_id, token_id, side, submitted_at,
                   order_id=None, wallet_addresses=(), api_owner=None):
    """Filter account fills to a submitted order's token and direction."""
    return iter_account_trade_fills(trades, condition_id=condition_id,
        token_id=token_id, side=side, submitted_at=submitted_at, order_id=order_id,
        owner_addresses=wallet_addresses, api_owner=api_owner)


def order_snapshot(raw, *, order_id, token_id, side, requested_size):
    """Validate the order endpoint's cumulative fill and cancellation state."""
    if not isinstance(raw, dict):
        return None
    response_id = raw.get("id") or raw.get("orderID") or raw.get("order_id")
    if not response_id or _id(response_id) != _id(order_id):
        return None
    token = raw.get("asset_id") or raw.get("token_id")
    if token is not None and str(token) != str(token_id):
        return None
    response_side = str(raw.get("side") or "").upper()
    if response_side and response_side != str(side).upper():
        return None
    original = number(raw.get("original_size"))
    filled = number(raw.get("size_matched"))
    if filled is None or filled < 0 or filled > requested_size + 1e-6:
        return None
    if original is not None and abs(original - requested_size) > 1e-6:
        return None
    status = str(raw.get("status") or "").upper()
    full = filled >= requested_size - 1e-6
    terminal = full or status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}
    return {"filled_size": min(filled, requested_size), "terminal": terminal,
            "status": status, "price": number(raw.get("price")), "raw": raw}


def cancellation_confirmed(raw, order_id):
    """An HTTP 200 alone is not evidence that an order was cancelled."""
    if not isinstance(raw, dict):
        return False
    wanted = _id(order_id)
    not_cancelled = raw.get("not_canceled") or raw.get("not_cancelled") or {}
    if isinstance(not_cancelled, dict):
        denied = {_id(key) for key in not_cancelled}
    elif isinstance(not_cancelled, list):
        denied = {_id(value) for value in not_cancelled}
    else:
        return False
    canceled = raw.get("canceled", raw.get("cancelled", []))
    return isinstance(canceled, list) and wanted in {_id(value) for value in canceled} and wanted not in denied
