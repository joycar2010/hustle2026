"""账户净值聚合 —— 单一真源。

admin_funds(读 Redis 快照)与 balance_pusher(落 balance_snapshot)都调本函数,
确保「净值/可用/已借/未实现」口径完全一致,不会两处各算一套导致对不上账。

输入 balances = balance:latest:{uid} payload 里的 balances 列表(每项一个子账户),
字段:spot_usdt_free / margin_usdt_free / margin_usdt_borrowed / margin_net_usdt /
margin_level / futures_total / futures_available / futures_unrealized_pnl / bnb_free。

口径:账户净值 equity = 现货USDT + 全仓净资产(已扣负债) + 合约权益 + 合约未实现盈亏。
"""
from __future__ import annotations


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _amount(v: float) -> float:
    """Normalize display/accounting amounts without changing their unit.

    Binance returns decimal strings, while JSON/Python floats can expose a
    binary rounding tail (for example ``0.1 + 0.2``).  Keep twelve decimal
    places, well below the precision needed for the displayed BNB balance,
    so aggregate payloads remain stable for clients and snapshots.
    """
    return round(float(v), 12)


def aggregate_balances(balances: list[dict]) -> dict:
    equity = available = borrowed = unrealized = bnb = 0.0
    margin_levels: list[float] = []
    for b in balances or []:
        spot = _f(b.get("spot_usdt_free"))
        m_free = _f(b.get("margin_usdt_free"))
        m_borrowed = _f(b.get("margin_usdt_borrowed"))
        # ``margin_usdt_borrowed`` is only the USDT row returned by Binance.
        # Coin debt (FIL/SLP/...) is reported in ``symbol_margin`` and is
        # converted by balance_pusher using the current spot bid.  Consume the
        # explicit total when available while retaining the legacy USDT-only
        # behaviour for old snapshots.
        borrowed_value = (
            _f(b.get("margin_borrowed_usdt"))
            if "margin_borrowed_usdt" in b
            else m_borrowed
        )
        m_net = _f(b.get("margin_net_usdt"))
        f_total = _f(b.get("futures_total"))
        f_avail = _f(b.get("futures_available"))
        f_upnl = _f(b.get("futures_unrealized_pnl"))
        m_level = _f(b.get("margin_level"))

        equity += spot + m_net + f_total + f_upnl
        available += spot + m_free + f_avail
        borrowed += borrowed_value
        unrealized += f_upnl
        bnb += _f(b.get("bnb_free"))
        # 币安无负债时 marginLevel=999(安全);只取有借贷(0<lv<100)的账户算"最差"
        if 0 < m_level < 100:
            margin_levels.append(m_level)

    return {
        "equity": equity,
        "available": available,
        "borrowed": borrowed,
        "unrealized_pnl": unrealized,
        "bnb": _amount(bnb),
        "margin_level_min": min(margin_levels) if margin_levels else None,
        "account_count": len(balances or []),
    }


def normalize_master_balance(
    spot: dict | None,
    margin: dict | None,
    futures: dict | None,
    *,
    btc_price: float = 0.0,
    account_name: str | None = None,
    snapshot_at_ms: int | None = None,
) -> dict:
    """Normalize a main-account wallet response into the balance-stream shape.

    The dashboard and admin funds page must not each invent a different
    definition of "main-account balance".  This helper is deliberately pure:
    it accepts already-fetched Binance responses and never performs an API
    call.  Secrets and raw account responses are never retained in the
    resulting payload.
    """
    spot = spot if isinstance(spot, dict) else {}
    margin = margin if isinstance(margin, dict) else {}
    futures = futures if isinstance(futures, dict) else {}

    spot_usdt_free = spot_usdt_locked = spot_bnb_free = 0.0
    for row in spot.get("balances", []) or []:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset") or "").upper()
        if asset == "USDT":
            spot_usdt_free = _f(row.get("free"))
            spot_usdt_locked = _f(row.get("locked"))
        elif asset == "BNB":
            spot_bnb_free = _f(row.get("free"))

    margin_free = margin_borrowed = margin_interest = margin_bnb_free = 0.0
    margin_net_btc = _f(margin.get("totalNetAssetOfBtc"))
    for row in margin.get("userAssets", []) or []:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset") or "").upper()
        if asset == "USDT":
            margin_free = _f(row.get("free"))
            margin_borrowed = _f(row.get("borrowed"))
            margin_interest = _f(row.get("interest"))
        elif asset == "BNB":
            margin_bnb_free = _f(row.get("free"))

    price = _f(btc_price)
    margin_net_usdt = margin_net_btc * price if price > 0 else 0.0
    futures_total = _f(futures.get("totalWalletBalance"))
    futures_available = _f(futures.get("availableBalance"))
    futures_upnl = _f(futures.get("totalUnrealizedProfit"))
    margin_level = _f(margin.get("marginLevel"))
    borrowed = margin_borrowed + margin_interest
    equity = spot_usdt_free + margin_net_usdt + futures_total + futures_upnl
    available = spot_usdt_free + margin_free + futures_available
    return {
        "configured": True,
        "account_name": account_name,
        "spot_usdt_free": spot_usdt_free,
        "spot_usdt_locked": spot_usdt_locked,
        "margin_net_usdt": margin_net_usdt,
        "margin_usdt_free": margin_free,
        "margin_usdt_borrowed": margin_borrowed,
        # Main-account responses currently expose margin debt per USDT row;
        # keep an explicit total field so the admin contract is identical to
        # sub-account snapshots and can be extended to non-USDT debt later.
        "margin_borrowed_usdt": borrowed,
        "margin_interest": margin_interest,
        "margin_level": margin_level,
        "futures_total": futures_total,
        "futures_available": futures_available,
        "futures_unrealized_pnl": futures_upnl,
        "bnb_free": _amount(spot_bnb_free + margin_bnb_free),
        "equity": equity,
        "available": available,
        "borrowed": borrowed,
        "unrealized_pnl": futures_upnl,
        "snapshot_at_ms": snapshot_at_ms,
        "snapshot_stale": False,
    }


def aggregate_user_funds(
    balances: list[dict],
    master_balance: dict | None = None,
) -> dict:
    """Aggregate sub-account balances plus one tenant-owned main account."""
    sub = aggregate_balances(balances)
    master = master_balance if isinstance(master_balance, dict) else None
    if not master or not master.get("configured"):
        return {**sub, "master": None, "master_equity": 0.0}

    def value(key: str) -> float:
        return _f(master.get(key))

    return {
        **sub,
        "equity": sub["equity"] + value("equity"),
        "available": sub["available"] + value("available"),
        "borrowed": sub["borrowed"] + value("borrowed"),
        "unrealized_pnl": sub["unrealized_pnl"] + value("unrealized_pnl"),
        "bnb": _amount(sub["bnb"] + value("bnb_free")),
        "master": master,
        "master_equity": value("equity"),
    }
