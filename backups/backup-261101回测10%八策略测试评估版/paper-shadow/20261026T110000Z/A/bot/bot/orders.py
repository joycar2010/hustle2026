"""Order placement via py-clob-client-v2. FOK only: fill at the listed price or fail."""
from __future__ import annotations

from dataclasses import dataclass
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


def _response_filled_size(resp: dict) -> float:
    for key in ("makingAmount", "filled", "size"):
        val = resp.get(key)
        if val not in (None, ""):
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.0


def _result_from_response(resp: dict, *, submitted: bool = True) -> OrderResult:
    return OrderResult(
        order_id=_response_order_id(resp),
        status=str(resp.get("status") or "unknown"),
        filled_size=_response_filled_size(resp),
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
    return OrderResult(
        order_id=None,
        status="timeout_pending_reconcile" if ambiguous else "error",
        filled_size=0.0,
        error=str(exc),
        submitted=True,
        ambiguous=ambiguous,
    )


def _post_submit_error_with_time(exc: Exception, submitted_at: float) -> OrderResult:
    result = _post_submit_error(exc)
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
    )


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
    """Find recent account trades that match a submitted order."""
    after = max(0, int(submitted_at - 3))
    before = int(submitted_at + max_age_sec)
    params = TradeParams(market=condition_id, asset_id=token_id, after=after, before=before)
    trades = client.get_trades(params, only_first_page=True)
    wanted_side = side.upper()
    matched = []
    for trade in trades:
        trade_order_ids = {
            str(v)
            for v in (
                trade.get("taker_order_id"),
                trade.get("maker_order_id"),
                trade.get("order_id"),
                trade.get("id"),
            )
            if v
        }
        if order_id and str(order_id) not in trade_order_ids:
            continue
        if str(trade.get("asset_id") or "") != str(token_id):
            continue
        if str(trade.get("market") or "").lower() != str(condition_id).lower():
            continue
        if str(trade.get("side") or "").upper() != wanted_side:
            continue
        if str(trade.get("status") or "").upper() == "FAILED":
            continue
        try:
            match_time = float(trade.get("match_time") or trade.get("last_update") or 0.0)
        except (TypeError, ValueError):
            match_time = 0.0
        if match_time and match_time < submitted_at - 3:
            continue
        try:
            size = float(trade.get("size") or 0.0)
        except (TypeError, ValueError):
            size = 0.0
        try:
            price = float(trade.get("price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        if size <= 0:
            continue
        matched.append((match_time, size, price, trade))

    if not matched:
        return None

    matched.sort(key=lambda item: item[0], reverse=True)
    total_size = sum(size for _, size, _, _ in matched)
    if min_size > 0 and not order_id and total_size < min_size * 0.50:
        return None
    total_amount = sum(size * price for _, size, price, _ in matched)
    avg_price = total_amount / total_size if total_size > 0 else None
    _, _, _, trade = matched[0]
    order_id = (
        trade.get("taker_order_id")
        or trade.get("maker_order_id")
        or trade.get("order_id")
        or trade.get("id")
    )
    return OrderResult(
        order_id=str(order_id) if order_id else None,
        status="matched",
        filled_size=total_size,
        error="reconciled after submit timeout",
        submitted=True,
        ambiguous=False,
        raw={"trades": [item[3] for item in matched]},
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
    return _result_from_response(resp)


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
    return _result_from_response(resp)


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
    return _result_from_response(resp)
