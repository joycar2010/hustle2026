"""O1 现金流优化器(V4.0 §3.2/§7.3)—— leg-aware 现金流评价,不拥有仓位、不产生独立 PnL。
铁律:
- **禁止 abs(funding)**:按腿方向算带符号现金流(多腿付正费率/收负费率,空腿反之);
- earn 只有现货腿真实可存入 + 赎回满足退出 SLA + 账单可核对才计入(默认不计,须显式 eligible);
- 数据不新鲜(funding ts>1800s)不计,如实标 stale,绝不用旧帧算。
输出 = EV_H 里 SignedCashflowSchedule 的日现金流分解,供经济评价/顾问消费。
"""
import time

from . import datasources as ds

FUNDING_STALE_SEC = 1800


async def _funding_daily(venue: str, symbol: str):
    """读归一化日化资金费(带符号,%/天);缺失或超龄返回 (None, reason)。"""
    r = ds.rds()
    if r is None:
        return None, "no-redis"
    try:
        raw = await r.hget(f"dcm:feed:funding:{venue}", symbol)
    except Exception:  # noqa: BLE001
        return None, "read-err"
    if not raw:
        return None, "missing"
    import json
    d = json.loads(raw)
    ts = float(d.get("ts") or 0)
    if time.time() - ts > FUNDING_STALE_SEC:
        return None, f"stale({int(time.time()-ts)}s)"
    return float(d.get("daily_pct")), None


async def evaluate(legs: list[dict]) -> dict:
    """给定腿集,算逐腿 + 汇总的带符号日现金流。
    leg = {venue, symbol, side, notional_usdt, [earn_apr], [borrow_apr], [earn_eligible]}
    side: perp_long | perp_short | spot_long | borrow
    """
    out_legs = []
    net_daily = 0.0
    warnings = []
    for i, leg in enumerate(legs or []):
        venue = str(leg.get("venue") or "")
        sym = str(leg.get("symbol") or "")
        side = str(leg.get("side") or "")
        notional = float(leg.get("notional_usdt") or 0)
        item = {"idx": i, "venue": venue, "symbol": sym, "side": side,
                "notional_usdt": notional, "funding_daily_usdt": 0.0,
                "earn_daily_usdt": 0.0, "borrow_daily_usdt": 0.0}

        if side in ("perp_long", "perp_short"):
            fd, reason = await _funding_daily(venue, sym)
            if fd is None:
                warnings.append(f"leg{i} {venue}:{sym} funding {reason},资金费计 0")
                item["funding_note"] = reason
            else:
                # 带符号:多腿在正费率是付出(负现金流),空腿在正费率是收入(正现金流)
                sign = -1.0 if side == "perp_long" else 1.0
                cf = sign * (fd / 100.0) * notional
                item["funding_daily_usdt"] = round(cf, 6)
                item["funding_daily_pct"] = fd

        # earn:仅现货腿 + 显式 eligible(真实可存入+退出 SLA+账单可核对)才计
        if side == "spot_long":
            apr = float(leg.get("earn_apr") or 0)
            if apr > 0:
                if leg.get("earn_eligible") is True:
                    item["earn_daily_usdt"] = round(apr / 365.0 * notional, 6)
                else:
                    warnings.append(f"leg{i} {sym} earn_apr={apr} 未标 eligible(真实可存入/SLA/可核对),不计入")

        # borrow:借息为成本(负)
        if side == "borrow":
            bapr = float(leg.get("borrow_apr") or 0)
            item["borrow_daily_usdt"] = round(-bapr / 365.0 * notional, 6)

        leg_net = item["funding_daily_usdt"] + item["earn_daily_usdt"] + item["borrow_daily_usdt"]
        item["leg_net_daily_usdt"] = round(leg_net, 6)
        net_daily += leg_net
        out_legs.append(item)

    gross_notional = sum(abs(float(l.get("notional_usdt") or 0)) for l in (legs or [])) or 1.0
    return {
        "legs": out_legs,
        "net_daily_usdt": round(net_daily, 6),
        "net_daily_pct_on_notional": round(net_daily / gross_notional * 100, 6),
        "warnings": warnings,
        "note": "带符号现金流(非abs);earn须eligible;stale腿计0。这是EV_H的SignedCashflowSchedule日项",
    }
