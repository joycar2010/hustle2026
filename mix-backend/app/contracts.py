"""执行内核契约(V4.0 §6.3)—— owner_key / leg_lock 的规范构造,决策面/执行面/账本面共用。
纪律:owner_key 取代 decision UNIQUE(symbol) 弱锁——不同结算币/到期/账户共享 symbol 由此精确区分。
每个 Intent 必须拥有 owner_key + 全部实际腿的 leg_lock;所有权切换 generation+1;
B 在订单发送前最后校验 generation/TTL/RiskReservation/运行模式。
"""


def owner_key(portfolio: str, book: str, canonical_underlying: str, settlement_bucket: str = "perp") -> str:
    """portfolio:book:canonical_underlying:settlement_bucket。
    settlement_bucket: perp / 2026Q3 / 2026Q4 ...(交割按到期桶分,永续统一 perp)。"""
    return ":".join(str(x).strip() for x in (portfolio, book, canonical_underlying, settlement_bucket))


def leg_lock(venue: str, account: str, canonical_instrument: str, position_mode: str = "oneway") -> str:
    """venue:account:canonical_instrument:position_mode —— 单腿资源锁。"""
    return ":".join(str(x).strip() for x in (venue, account, canonical_instrument, position_mode))


def settlement_bucket_of(expiry_iso: str | None) -> str:
    """由到期日归一成结算桶:无到期=perp;有到期=YYYYQn。"""
    if not expiry_iso:
        return "perp"
    try:
        import datetime as dt
        d = dt.datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
        return f"{d.year}Q{(d.month - 1) // 3 + 1}"
    except Exception:  # noqa: BLE001
        return "perp"


# 三个执行模板(§6.1):产品 → 复用模板,不为每个产品新建 engine
EXECUTION_TEMPLATES = {
    "SPOT_LONG_DERIVATIVE_SHORT": ["C1", "C4"],
    "DERIVATIVE_LONG_DERIVATIVE_SHORT": ["C2", "C5", "C6"],   # 含 HL 路由
    "BORROW_SPOT_SHORT_DERIVATIVE_LONG": ["C3.S", "C3.R"],
}


def template_for(product_id: str) -> str | None:
    base = product_id.split(".")[0]
    for tmpl, prods in EXECUTION_TEMPLATES.items():
        if product_id in prods or base in [p.split(".")[0] for p in prods]:
            return tmpl
    return None
