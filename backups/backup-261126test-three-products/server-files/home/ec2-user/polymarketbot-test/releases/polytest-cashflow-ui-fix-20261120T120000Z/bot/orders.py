"""Order placement via py-clob-client-v2. FOK only: fill at the listed price or fail."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_FLOOR
import math
import time
from typing import Optional

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import (
    ApiCreds,
    AssetType,
    BalanceAllowanceParams,
    MarketOrderArgsV2,
    TradeParams,
    OrderArgsV2,
    OrderType,
    PartialCreateOrderOptions,
)
from py_clob_client_v2.config import get_contract_config
from py_clob_client_v2.order_builder.constants import BUY, SELL

from bot.config import Config
from bot.order_evidence import cancellation_confirmed, order_snapshot, own_trade_legs


@dataclass(frozen=True)
class OrderResult:
    order_id: Optional[str]
    status: str
    filled_size: float
    error: Optional[str]
    submitted: bool = False
    ambiguous: bool = False
    raw: Optional[dict] = None
    avg_price: Optional[float] = None
    filled_amount: Optional[float] = None
    remaining_size: Optional[float] = None
    terminal: bool = False
    fallback_safe: bool = False


@dataclass(frozen=True)
class CollateralBalance:
    """CLOB-recognized collateral balance and allowance for a market order."""

    balance_usd: float
    allowance_usd: float
    allowance_contract: str
    raw: dict

    def spendable_usd(self, reserve_usd: float) -> float:
        return max(
            min(self.balance_usd, self.allowance_usd) - max(reserve_usd, 0.0),
            0.0,
        )


def _collateral_units_to_usd(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid collateral amount: {value!r}") from exc


def get_collateral_balance_allowance(
    client: ClobClient,
    *,
    chain_id: int,
    neg_risk: bool,
) -> CollateralBalance:
    """Read the CLOB collateral balance and relevant exchange allowance."""
    raw = dict(
        client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
    )
    if "balance" not in raw:
        raise ValueError("CLOB balance-allowance response missing balance")

    contracts = get_contract_config(chain_id)
    allowance_contract = (
        contracts.neg_risk_exchange_v2 if neg_risk else contracts.exchange_v2
    )
    allowances = raw.get("allowances") or {}
    allowance_raw = None
    for address, value in allowances.items():
        if str(address).lower() == allowance_contract.lower():
            allowance_raw = value
            break

    return CollateralBalance(
        balance_usd=_collateral_units_to_usd(raw.get("balance")),
        allowance_usd=_collateral_units_to_usd(allowance_raw),
        allowance_contract=allowance_contract,
        raw=raw,
    )


def build_client(cfg: Config) -> ClobClient:
    creds = ApiCreds(
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        api_passphrase=cfg.api_passphrase,
    )
    return ClobClient(
        cfg.clob_host,
        chain_id=cfg.chain_id,
        key=cfg.private_key,
        creds=creds,
        signature_type=cfg.signature_type,
        funder=cfg.funder_address,
        retry_on_error=True,
    )


def _is_request_exception(exc: Exception) -> bool:
    text = str(exc)
    return (
        "Request exception" in text
        or "timed out" in text.lower()
        or "timeout" in text.lower()
    )


def _response_order_id(resp: dict) -> Optional[str]:
    return resp.get("orderID") or resp.get("orderId") or resp.get("id")


def _response_filled_size(
    resp: dict,
    *,
    side: Optional[str] = None,
    max_size: Optional[float] = None,
) -> float:
    """Extract outcome-token shares from a CLOB response.

    ``makingAmount`` is the maker asset and is USDC for BUY orders.  Prefer
    explicit fill-size fields, then use the side-specific asset amount, and
    cap the result to the requested token size.
    """
    value = 0.0
    for key in ("filledSize", "filled_size", "matchedSize", "size", "filled"):
        val = resp.get(key)
        if val not in (None, ""):
            try:
                value = float(val)
                break
            except (TypeError, ValueError):
                pass
    else:
        asset_key = "takingAmount" if str(side or "").upper() == BUY else "makingAmount"
        val = resp.get(asset_key)
        if val not in (None, ""):
            try:
                value = float(val)
            except (TypeError, ValueError):
                value = 0.0
    if max_size is not None:
        value = min(value, max(float(max_size), 0.0))
    return max(value, 0.0)


def _result_from_response(
    resp: dict,
    *,
    submitted: bool = True,
    side: Optional[str] = None,
    max_size: Optional[float] = None,
) -> OrderResult:
    return OrderResult(
        order_id=_response_order_id(resp),
        status=str(resp.get("status") or "unknown"),
        filled_size=_response_filled_size(resp, side=side, max_size=max_size),
        error=resp.get("errorMsg") or None,
        submitted=submitted,
        ambiguous=False,
        raw=resp,
    )


def _pre_submit_error(exc: Exception) -> OrderResult:
    return OrderResult(
        order_id=None,
        status="pre_submit_error",
        filled_size=0.0,
        error=str(exc),
        submitted=False,
        ambiguous=False,
    )


def _post_submit_error(exc: Exception) -> OrderResult:
    ambiguous = _is_request_exception(exc)
    text = str(exc)
    if "post-only" in text.lower() and "cross" in text.lower():
        return OrderResult(
            order_id=None,
            status="post_only_rejected",
            filled_size=0.0,
            error=text,
            submitted=False,
            ambiguous=False,
            terminal=True,
            fallback_safe=True,
        )
    return OrderResult(
        order_id=None,
        status="timeout_pending_reconcile" if ambiguous else "error",
        filled_size=0.0,
        error=text,
        submitted=True,
        ambiguous=ambiguous,
    )


def _post_submit_error_with_time(exc: Exception, submitted_at: float) -> OrderResult:
    result = _post_submit_error(exc)
    if result.status == "post_only_rejected":
        return OrderResult(
            order_id=None,
            status=result.status,
            filled_size=0.0,
            error=result.error,
            submitted=False,
            ambiguous=False,
            raw={"submitted_at": submitted_at},
            terminal=result.terminal,
            fallback_safe=result.fallback_safe,
        )
    return OrderResult(
        order_id=result.order_id,
        status=result.status,
        filled_size=result.filled_size,
        error=result.error,
        submitted=result.submitted,
        ambiguous=result.ambiguous,
        raw={"submitted_at": submitted_at},
        avg_price=result.avg_price,
        filled_amount=result.filled_amount,
        remaining_size=result.remaining_size,
        terminal=result.terminal,
        fallback_safe=result.fallback_safe,
    )


def _client_trade_identity(client):
    """Use local SDK identity only; never log API owner or credentials."""
    addresses = []
    for candidate in (getattr(client, "funder", None),
                      getattr(getattr(client, "builder", None), "funder", None)):
        if candidate:
            addresses.append(candidate)
    try:
        addresses.append(client.get_address())
    except (AttributeError, TypeError):
        pass
    creds = getattr(client, "creds", None)
    owner = getattr(creds, "api_key", None)
    if owner is None and isinstance(creds, dict):
        owner = creds.get("api_key")
    return addresses, owner


def reconcile_recent_trade(
    client: ClobClient,
    *,
    condition_id: str,
    token_id: str,
    side: str,
    submitted_at: float,
    min_size: float = 0.0,
    max_age_sec: float = 45.0,
    order_id: Optional[str] = None,
) -> Optional[OrderResult]:
    """Find this account's individual fills, including nested maker orders."""
    after = max(0, int(submitted_at - 3))
    before = int(submitted_at + max_age_sec)
    params = TradeParams(market=condition_id, asset_id=token_id, after=after, before=before)
    trades = client.get_trades(params, only_first_page=True)
    addresses, owner = _client_trade_identity(client)
    matched = own_trade_legs(trades, condition_id=condition_id, token_id=token_id,
                             side=side, submitted_at=submitted_at, order_id=order_id,
                             wallet_addresses=addresses, api_owner=owner)

    if not matched:
        return None

    own_ids = {str(item["order_id"]).lower() for item in matched}
    if not order_id and len(own_ids) != 1:
        return OrderResult(order_id=None, status="reconcile_multiple_orders",
                           filled_size=0.0, error="recent fills belong to multiple own orders",
                           submitted=True, ambiguous=True,
                           raw={"trades": [item["trade"] for item in matched]})
    total_size = sum(item["size"] for item in matched)
    if min_size > 0 and not order_id and total_size < min_size * 0.50:
        return None
    total_amount = sum(item["amount"] for item in matched)
    avg_price = total_amount / total_size if total_size > 0 else None
    order_id = order_id or matched[-1]["order_id"]
    return OrderResult(
        order_id=str(order_id) if order_id else None,
        status="matched",
        filled_size=total_size,
        error="reconciled after submit timeout",
        submitted=True,
        ambiguous=False,
        raw={"trades": [item["trade"] for item in matched],
             "own_fills": [{key: value for key, value in item.items() if key != "trade"}
                           for item in matched]},
        avg_price=avg_price,
        filled_amount=total_amount,
    )


def place_buy_fok(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
) -> OrderResult:
    """Fill-or-kill BUY: take exactly `size` at <=`price` now, or do nothing."""
    args = OrderArgsV2(token_id=token_id, price=price, size=size, side=BUY)
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_order(args, opts)
    except Exception as e:
        return _pre_submit_error(e)
    try:
        submitted_at = time.time()
        resp = client.post_order(signed, order_type=OrderType.FOK)
    except Exception as e:
        return _post_submit_error_with_time(e, submitted_at)

    resp = dict(resp)
    resp.setdefault("submitted_at", submitted_at)
    return _result_from_response(resp, side=BUY, max_size=max(float(size), 0.0))


def place_buy_market_fok(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    amount_usd: float,
    tick_size: float,
    neg_risk: bool,
    user_usdc_balance: Optional[float] = None,
) -> OrderResult:
    """FOK BUY by dollar amount at the supplied limit price."""
    amount_usd = float(
        Decimal(str(amount_usd)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    )
    args = MarketOrderArgsV2(
        token_id=token_id,
        amount=amount_usd,
        side=BUY,
        price=price,
        order_type=OrderType.FOK,
        user_usdc_balance=(
            max(float(user_usdc_balance), 0.0)
            if user_usdc_balance is not None
            else 0.0
        ),
    )
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_market_order(args, opts)
    except Exception as e:
        return _pre_submit_error(e)
    try:
        submitted_at = time.time()
        resp = client.post_order(signed, order_type=OrderType.FOK)
    except Exception as e:
        return _post_submit_error_with_time(e, submitted_at)

    resp = dict(resp)
    resp.setdefault("submitted_at", submitted_at)
    expected_size = amount_usd / max(float(price), 1e-9)
    return _result_from_response(resp, side=BUY, max_size=expected_size * 1.02)


def place_sell_fok(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
) -> OrderResult:
    """Fill-or-kill SELL: sell held outcome shares at >=`price` now, or do nothing."""
    return _place_sell(
        client,
        token_id=token_id,
        price=price,
        size=size,
        tick_size=tick_size,
        neg_risk=neg_risk,
        order_type=OrderType.FOK,
    )


def place_sell_fak(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
) -> OrderResult:
    """Fill-and-kill SELL: sell what can fill at >=`price` now, cancel the rest."""
    return _place_sell(
        client,
        token_id=token_id,
        price=price,
        size=size,
        tick_size=tick_size,
        neg_risk=neg_risk,
        order_type=OrderType.FAK,
    )


def _maker_order_type(value: str) -> OrderType:
    """Normalize a configured maker order type without allowing a taker type."""
    normalized = str(value or "GTC").strip().upper()
    if normalized not in {"GTC", "GTD"}:
        raise ValueError(f"maker order type must be GTC or GTD, got {value!r}")
    return OrderType.GTD if normalized == "GTD" else OrderType.GTC


def _maker_execution_result(client, *, condition_id, token_id, side, submitted_at,
                            order_id, size, price, response, cancel_response=None,
                            cancel_attempted=False):
    """Combine cumulative order evidence with own fills, never adding them twice."""
    matched, snapshot = None, None
    failures = []
    if condition_id:
        try:
            matched = reconcile_recent_trade(
                client, condition_id=condition_id, token_id=token_id,
                side=side, submitted_at=submitted_at, order_id=order_id,
                max_age_sec=max(time.time() - submitted_at + 8.0, 15.0))
        except Exception as exc:
            failures.append("trades:" + type(exc).__name__)
    try:
        snapshot = order_snapshot(client.get_order(order_id), order_id=order_id,
                                  token_id=token_id, side=side, requested_size=size)
        if snapshot is None:
            failures.append("order:invalid_evidence")
    except Exception as exc:
        failures.append("order:" + type(exc).__name__)
    trade_size = matched.filled_size if matched is not None and not matched.ambiguous else 0.0
    snapshot_size = snapshot["filled_size"] if snapshot else 0.0
    filled = max(trade_size, snapshot_size)
    conflict = trade_size > size + 1e-6
    if snapshot and snapshot["terminal"] and trade_size > snapshot_size + 1e-6:
        # A stale cancelled snapshot must not authorize an extra residual order.
        conflict = True
    full = filled >= size - 1e-6 and not conflict
    terminal = full or bool(snapshot and snapshot["terminal"] and not conflict)
    remaining = max(0.0, size - filled) if terminal else None
    fallback_safe = terminal and remaining is not None and remaining > 1e-6
    trade_amount = matched.filled_amount if matched is not None else None
    if trade_amount is not None and abs(trade_size - filled) <= 1e-6:
        amount, price_source = trade_amount, "own_trades"
    else:
        # A cumulative order fill is valid inventory evidence even if the
        # separate trade index lags. Use the known maker limit until its
        # actual fills become available, rather than dropping that position.
        amount = filled * price
        price_source = "order_limit_pending_trade_index"
    raw = {"submitted_at": submitted_at, "response": response,
           "requested_size": size, "remaining_size": remaining,
           "terminal": terminal, "fallback_safe": fallback_safe,
           "cancel_attempted": cancel_attempted,
           "cancellation_confirmed": cancellation_confirmed(cancel_response, order_id),
           "cancel_response": cancel_response,
           "order_snapshot": snapshot["raw"] if snapshot else None,
           "trades": (matched.raw or {}).get("trades", []) if matched else [],
           "own_fills": (matched.raw or {}).get("own_fills", []) if matched else [],
           "filled_amount_source": price_source, "reconciliation_errors": failures}
    if full:
        status, error = "matched", None
    elif terminal and filled > 0:
        status, error = "maker_partial_cancelled", None
    elif terminal:
        status, error = "maker_timeout_cancelled", "maker remainder confirmed cancelled"
    else:
        status = "maker_pending_reconcile"
        error = "maker fill/cancellation evidence is incomplete or inconsistent; no fallback allowed"
    return OrderResult(order_id=order_id, status=status, filled_size=filled,
                       error=error, submitted=True, ambiguous=not terminal,
                       raw=raw, avg_price=amount / filled if filled > 0 else None,
                       filled_amount=amount if filled > 0 else 0.0,
                       remaining_size=remaining, terminal=terminal,
                       fallback_safe=fallback_safe)


def _place_maker(
    client: ClobClient,
    *,
    token_id: str,
    side: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
    order_type: str = "GTC",
    ttl_sec: float = 3.0,
    post_only: bool = True,
    condition_id: Optional[str] = None,
    best_bid: Optional[float] = None,
    best_ask: Optional[float] = None,
    cancel_event=None,
) -> OrderResult:
    """Submit a passive order, reconcile it, then cancel it safely on timeout.

    A maker timeout is never treated as a fill.  If cancellation is
    ambiguous, ``ambiguous=True`` prevents callers from falling through to a
    taker order while an old order may still be resting on the book.
    """
    size = math.floor(max(float(size), 0.0) * 100) / 100
    if size <= 0:
        return OrderResult(order_id=None, status="error", filled_size=0.0,
                           error="maker size <= 0 after rounding")
    if post_only:
        p = float(price)
        if str(side).upper() == BUY and best_ask is not None and p >= float(best_ask) - 1e-9:
            return OrderResult(
                order_id=None, status="post_only_rejected", filled_size=0.0,
                error=f"post-only quote {p:.4f} crosses best ask {float(best_ask):.4f}",
                remaining_size=size, terminal=True, fallback_safe=True,
            )
        if str(side).upper() == SELL and best_bid is not None and p <= float(best_bid) + 1e-9:
            return OrderResult(
                order_id=None, status="post_only_rejected", filled_size=0.0,
                error=f"post-only quote {p:.4f} crosses best bid {float(best_bid):.4f}",
                remaining_size=size, terminal=True, fallback_safe=True,
            )
    try:
        maker_type = _maker_order_type(order_type)
    except ValueError as exc:
        return _pre_submit_error(exc)
    ttl = min(max(float(ttl_sec), 0.1), 30.0)
    expiration = int(time.time() + ttl) if maker_type == OrderType.GTD else 0
    args = OrderArgsV2(
        token_id=token_id,
        price=float(price),
        size=size,
        side=side,
        expiration=expiration,
    )
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_order(args, opts)
    except Exception as exc:
        return _pre_submit_error(exc)
    submitted_at = time.time()
    try:
        resp = dict(client.post_order(signed, order_type=maker_type, post_only=bool(post_only)))
    except Exception as exc:
        result = _post_submit_error_with_time(exc, submitted_at)
        return replace(result, remaining_size=size if result.fallback_safe else None)
    resp.setdefault("submitted_at", submitted_at)
    order_id = _response_order_id(resp)
    if not order_id:
        # A successful HTTP response without an order id cannot be safely
        # reconciled or cancelled; force the caller to stop and investigate.
        return OrderResult(order_id=None, status="maker_order_id_missing",
                           filled_size=0.0, error="maker response missing order id",
                           submitted=True, ambiguous=True, raw=resp)

    # Keep the wait bounded; GTD expiry alone is not proof of zero execution.
    if cancel_event is None:
        time.sleep(ttl)
    else:
        cancel_event.wait(ttl)
    query = dict(condition_id=condition_id, token_id=token_id, side=str(side).upper(),
                 submitted_at=submitted_at, order_id=str(order_id), size=size,
                 price=float(price), response=resp)
    before_cancel = _maker_execution_result(client, **query)
    if before_cancel.terminal:
        return before_cancel
    cancel_response = None
    cancel_error = None
    try:
        cancel_response = client.cancel_orders([str(order_id)])
    except Exception as exc:
        cancel_error = type(exc).__name__
    after_cancel = _maker_execution_result(client, **query,
        cancel_response=cancel_response, cancel_attempted=True)
    # A failed cancellation can race with a completed fill. The second order
    # read may prove that completion; otherwise preserve all earlier fills.
    if before_cancel.filled_size > after_cancel.filled_size + 1e-6:
        raw = dict(after_cancel.raw or {})
        raw.update(previous_fill_size=before_cancel.filled_size,
                   previous_execution_evidence=before_cancel.raw)
        return replace(before_cancel, status="maker_pending_reconcile",
                       error="maker evidence regressed after cancellation; no fallback allowed",
                       ambiguous=True, terminal=False, fallback_safe=False,
                       remaining_size=None, raw=raw)
    if cancel_error:
        raw = dict(after_cancel.raw or {})
        raw["cancellation_error"] = cancel_error
        after_cancel = replace(after_cancel, raw=raw)
    return after_cancel


def place_buy_maker(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
    order_type: str = "GTC",
    ttl_sec: float = 3.0,
    post_only: bool = True,
    condition_id: Optional[str] = None,
    best_bid: Optional[float] = None,
    best_ask: Optional[float] = None,
    cancel_event=None,
) -> OrderResult:
    return _place_maker(
        client, token_id=token_id, side=BUY, price=price, size=size,
        tick_size=tick_size, neg_risk=neg_risk, order_type=order_type,
        ttl_sec=ttl_sec, post_only=post_only, condition_id=condition_id,
        best_bid=best_bid, best_ask=best_ask, cancel_event=cancel_event,
    )


def place_sell_maker(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
    order_type: str = "GTC",
    ttl_sec: float = 2.0,
    post_only: bool = True,
    condition_id: Optional[str] = None,
    best_bid: Optional[float] = None,
    best_ask: Optional[float] = None,
    cancel_event=None,
) -> OrderResult:
    return _place_maker(
        client, token_id=token_id, side=SELL, price=price, size=size,
        tick_size=tick_size, neg_risk=neg_risk, order_type=order_type,
        ttl_sec=ttl_sec, post_only=post_only, condition_id=condition_id,
        best_bid=best_bid, best_ask=best_ask, cancel_event=cancel_event,
    )


def _place_sell(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
    order_type: str,
) -> OrderResult:
    size = math.floor(size * 100) / 100
    if size <= 0:
        return OrderResult(order_id=None, status="error", filled_size=0.0, error="sell size <= 0 after rounding")

    args = OrderArgsV2(token_id=token_id, price=price, size=size, side=SELL)
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_order(args, opts)
    except Exception as e:
        return _pre_submit_error(e)
    try:
        submitted_at = time.time()
        resp = client.post_order(signed, order_type=order_type)
    except Exception as e:
        return _post_submit_error_with_time(e, submitted_at)

    resp = dict(resp)
    resp.setdefault("submitted_at", submitted_at)
    return _result_from_response(resp, side=SELL, max_size=size)
