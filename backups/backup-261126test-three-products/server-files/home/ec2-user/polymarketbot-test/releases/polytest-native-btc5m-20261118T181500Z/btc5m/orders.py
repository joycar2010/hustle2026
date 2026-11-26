"""CLOB order helpers with side-aware fill accounting.

The CLOB response uses maker/taker asset amounts whose meaning changes with
the order side. We therefore never treat ``makingAmount`` as shares for a
BUY. If a response does not contain enough information to establish an
actual fill, the result is marked ``unknown`` and callers must reconcile the
order before retrying.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from btc5m.config import Config


@dataclass(frozen=True)
class FillReceipt:
    size: float
    price: Optional[float]
    notional_usd: Optional[float]
    trade_id: Optional[str] = None
    source: str = "response"


@dataclass(frozen=True)
class OrderResult:
    order_id: Optional[str]
    status: str
    filled_size: float
    avg_price: Optional[float]
    error: Optional[str]
    raw: Optional[dict] = None
    side: str = "BUY"
    notional_usd: Optional[float] = None
    fills: tuple[FillReceipt, ...] = ()
    fill_source: str = "none"
    fee_usd: Optional[float] = None


def build_client(cfg: Config):
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import ApiCreds

    if not cfg.private_key:
        raise RuntimeError("PRIVATE_KEY required for live trading")
    if not (cfg.api_key and cfg.api_secret and cfg.api_passphrase):
        raise RuntimeError("API_KEY/API_SECRET/API_PASSPHRASE required for live trading")
    creds = ApiCreds(api_key=cfg.api_key, api_secret=cfg.api_secret, api_passphrase=cfg.api_passphrase)
    return ClobClient(
        cfg.clob_host,
        chain_id=cfg.chain_id,
        key=cfg.private_key,
        creds=creds,
        signature_type=cfg.signature_type,
        funder=cfg.funder_address or None,
        retry_on_error=True,
    )


def _number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _order_id(resp: dict) -> Optional[str]:
    value = resp.get("orderID") or resp.get("orderId") or resp.get("id")
    return str(value) if value not in (None, "") else None


def _status(resp: dict, *, filled_size: float, requested_size: float) -> str:
    raw = str(resp.get("status") or resp.get("state") or "").strip().lower()
    if resp.get("errorMsg") or resp.get("error"):
        return "rejected"
    if raw in {"rejected", "failed", "cancelled", "canceled", "expired"}:
        return "rejected"
    if filled_size > 0 and requested_size > 0 and filled_size + 1e-9 < requested_size:
        return "partial"
    if filled_size > 0:
        return "filled"
    if raw in {"matched", "filled", "complete", "completed", "executed"}:
        # A matched status with no quantity is deliberately not a fill: it
        # must be reconciled from authenticated fills first.
        return "unknown"
    if raw in {"live", "open", "submitted", "pending"}:
        return "submitted"
    if _order_id(resp):
        return "unknown"
    return "rejected"


def _parse_response(resp: dict, *, side: str, requested_size: float) -> OrderResult:
    side = side.upper()
    # BUY: makingAmount is USDC and takingAmount is outcome shares.
    # SELL: makingAmount is outcome shares and takingAmount is USDC.
    share_keys = (
        ("filledSize", "matchedAmount", "takingAmount")
        if side == "BUY"
        else ("filledSize", "matchedAmount", "makingAmount")
    )
    share_amount = next((_number(resp.get(k)) for k in share_keys if _number(resp.get(k)) is not None), None)
    notional_amount = _number(resp.get("makingAmount" if side == "BUY" else "takingAmount"))
    explicit_price = next(
        (_number(resp.get(k)) for k in ("avgPrice", "averagePrice", "matchPrice", "price") if _number(resp.get(k)) is not None),
        None,
    )
    fee_usd = next(
        (_number(resp.get(k)) for k in ("fee", "feeUsd", "fee_usd", "feeAmount") if _number(resp.get(k)) is not None),
        None,
    )
    receipts: list[FillReceipt] = []
    raw_fills = resp.get("fills") or resp.get("matches") or []
    if isinstance(raw_fills, list):
        for item in raw_fills:
            if not isinstance(item, dict):
                continue
            fsize = next((_number(item.get(k)) for k in share_keys if _number(item.get(k)) is not None), None)
            if fsize is None or fsize <= 0:
                continue
            fprice = next((_number(item.get(k)) for k in ("price", "matchPrice", "avgPrice") if _number(item.get(k)) is not None), None)
            receipts.append(FillReceipt(
                size=fsize,
                price=fprice,
                notional_usd=None if fprice is None else fsize * fprice,
                trade_id=str(item.get("tradeId") or item.get("id")) if item.get("tradeId") or item.get("id") else None,
            ))
    if receipts:
        share_amount = sum(x.size for x in receipts)
        notional_amount = sum(x.notional_usd or 0.0 for x in receipts)
        explicit_price = (notional_amount / share_amount) if share_amount and notional_amount is not None else explicit_price
    filled = float(share_amount or 0.0)
    avg_price = explicit_price
    if avg_price is None and filled > 0 and notional_amount is not None:
        avg_price = notional_amount / filled
    return OrderResult(
        order_id=_order_id(resp),
        status=_status(resp, filled_size=filled, requested_size=requested_size),
        filled_size=filled,
        avg_price=avg_price,
        error=str(resp.get("errorMsg") or resp.get("error")) if resp.get("errorMsg") or resp.get("error") else None,
        raw=resp,
        side=side,
        notional_usd=(filled * avg_price if avg_price is not None and filled > 0 else notional_amount),
        fills=tuple(receipts),
        fill_source="authenticated_fills" if receipts else ("response_amounts" if filled > 0 else "none"),
        fee_usd=fee_usd,
    )


def _order_type(order_type_name: str):
    from py_clob_client_v2.clob_types import OrderType
    value = getattr(OrderType, order_type_name, None)
    if value is None:
        raise RuntimeError(f"CLOB client does not expose OrderType.{order_type_name}")
    return value


def _place_order(client, *, token_id: str, price: float, size: float, tick_size: float, neg_risk: bool, side_name: str, order_type_name: str) -> OrderResult:
    from py_clob_client_v2.clob_types import OrderArgsV2, PartialCreateOrderOptions
    from py_clob_client_v2.order_builder.constants import BUY, SELL
    side = BUY if side_name == "BUY" else SELL
    args = OrderArgsV2(token_id=token_id, price=price, size=size, side=side)
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_order(args, opts)
        resp = dict(client.post_order(signed, order_type=_order_type(order_type_name)))
    except Exception as exc:  # noqa: BLE001
        return OrderResult(order_id=None, status="unknown", filled_size=0.0, avg_price=None, error=str(exc), side=side_name)
    return _parse_response(resp, side=side_name, requested_size=float(size))


def place_buy_fok(client, *, token_id: str, price: float, size: float, tick_size: float, neg_risk: bool) -> OrderResult:
    return _place_order(client, token_id=token_id, price=price, size=size, tick_size=tick_size, neg_risk=neg_risk, side_name="BUY", order_type_name="FOK")


def place_sell_fok(client, *, token_id: str, price: float, size: float, tick_size: float, neg_risk: bool) -> OrderResult:
    return _place_order(client, token_id=token_id, price=price, size=size, tick_size=tick_size, neg_risk=neg_risk, side_name="SELL", order_type_name="FOK")


def place_sell_fak(client, *, token_id: str, price: float, size: float, tick_size: float, neg_risk: bool) -> OrderResult:
    return _place_order(client, token_id=token_id, price=price, size=size, tick_size=tick_size, neg_risk=neg_risk, side_name="SELL", order_type_name="FAK")


def place_sell_fok_then_fak(client, *, token_id: str, price: float, size: float, tick_size: float, neg_risk: bool) -> OrderResult:
    """Try FOK then FAK only after an explicit FOK rejection.

    An unknown/timeout response is never retried because the original order
    may have reached the exchange. The caller must reconcile it first.
    """
    result = place_sell_fok(client, token_id=token_id, price=price, size=size, tick_size=tick_size, neg_risk=neg_risk)
    # A FOK rejection is safe to retry only when the exchange gave no order
    # identity and no fill evidence.  Any id/fill/unknown response may have
    # reached the venue; reconcile it before sending another sell.
    if result.status in {"filled", "partial"} or result.status != "rejected" or result.order_id or result.fills:
        return result
    return place_sell_fak(client, token_id=token_id, price=price, size=size, tick_size=tick_size, neg_risk=neg_risk)
