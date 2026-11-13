"""Live order placement via py-clob-client-v2 (FOK buys)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from btc5m.config import Config


@dataclass(frozen=True)
class OrderResult:
    order_id: Optional[str]
    status: str
    filled_size: float
    avg_price: Optional[float]
    error: Optional[str]
    raw: Optional[dict] = None


def build_client(cfg: Config):
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import ApiCreds

    if not cfg.private_key:
        raise RuntimeError("PRIVATE_KEY required for live trading")
    if not (cfg.api_key and cfg.api_secret and cfg.api_passphrase):
        raise RuntimeError("API_KEY/API_SECRET/API_PASSPHRASE required for live trading")

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
        funder=cfg.funder_address or None,
        retry_on_error=True,
    )


def place_buy_fok(
    client,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
) -> OrderResult:
    from py_clob_client_v2.clob_types import (
        OrderArgsV2,
        OrderType,
        PartialCreateOrderOptions,
    )
    from py_clob_client_v2.order_builder.constants import BUY

    args = OrderArgsV2(token_id=token_id, price=price, size=size, side=BUY)
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_order(args, opts)
        resp = dict(client.post_order(signed, order_type=OrderType.FOK))
    except Exception as exc:  # noqa: BLE001
        return OrderResult(
            order_id=None,
            status="error",
            filled_size=0.0,
            avg_price=None,
            error=str(exc),
        )

    order_id = resp.get("orderID") or resp.get("orderId") or resp.get("id")
    filled = 0.0
    for key in ("makingAmount", "filled", "size"):
        if resp.get(key) not in (None, ""):
            try:
                filled = float(resp[key])
                break
            except (TypeError, ValueError):
                pass
    return OrderResult(
        order_id=str(order_id) if order_id else None,
        status=str(resp.get("status") or "unknown"),
        filled_size=filled,
        avg_price=price if filled > 0 else None,
        error=resp.get("errorMsg") or None,
        raw=resp,
    )
