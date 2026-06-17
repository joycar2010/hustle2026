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


def aggregate_balances(balances: list[dict]) -> dict:
    equity = available = borrowed = unrealized = bnb = 0.0
    margin_levels: list[float] = []
    for b in balances or []:
        spot = _f(b.get("spot_usdt_free"))
        m_free = _f(b.get("margin_usdt_free"))
        m_borrowed = _f(b.get("margin_usdt_borrowed"))
        m_net = _f(b.get("margin_net_usdt"))
        f_total = _f(b.get("futures_total"))
        f_avail = _f(b.get("futures_available"))
        f_upnl = _f(b.get("futures_unrealized_pnl"))
        m_level = _f(b.get("margin_level"))

        equity += spot + m_net + f_total + f_upnl
        available += spot + m_free + f_avail
        borrowed += m_borrowed
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
        "bnb": bnb,
        "margin_level_min": min(margin_levels) if margin_levels else None,
        "account_count": len(balances or []),
    }
