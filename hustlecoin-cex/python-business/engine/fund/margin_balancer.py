"""主账户 → 子账户 保证金自动平衡(hedge_via_master 多账户模式)。

子账户借币卖现货需 margin(全仓杠杆)钱包有 USDT 抵押;本模块按子账户的
风控阈/单笔划/保底额(SubAccount.risk_threshold / single_transfer_amount / min_balance)
维持其 margin 风险水平,资金从主账户按 FundRules.transfer_order 划入:

  1) 风险值(marginLevel) < risk_threshold(子无则回退全局 risk_value_threshold)
     → 从主账户划 single_transfer_amount 进子 margin(每周期一笔)。
  2) 子 margin USDT < min_balance(保底额) → 补足差额。
  3) 无持仓 且 子 margin USDT > min_balance 且风险值健康(>2) → 多余划回主账户。

**两道护栏(主账户资金保护)**:
  · 主账户保留下限 = FundRules.base_margin_amount —— 主账户(spot+margin+futures可用)USDT 总额
    须保留此值不被自动平衡动用,护住对冲保证金不被抽干;
  · 按可用封顶 —— 每次划入额 = min(请求额, 主账户总可用 − 保留下限),余额不足则部分划入/不划,
    不再全失败,也绝不抽穿保留下限。

划转用主账户 key 的 universal_transfer(主=None、子=SubAccount.email)。
安全默认:single_transfer_amount 为空/0 → 该子账户自动平衡禁用。所有异常吞掉(不崩 worker)。
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, ROUND_DOWN

from app.db.models import SubAccount
from app.db.session import SessionLocal
from engine.trading.binance_trading import BinanceTradingClient

logger = logging.getLogger(__name__)

_UT = {"spot": "SPOT", "futures": "USDT_FUTURE", "margin": "MARGIN"}


def _load_sub_cfg(sub_id: int) -> dict | None:
    db = SessionLocal()
    try:
        sa = db.query(SubAccount).get(sub_id)
        if not sa or not sa.email:
            return None
        return {
            "email": sa.email,
            "risk_threshold": sa.risk_threshold,
            "chunk": sa.single_transfer_amount,
            "floor": sa.min_balance,
        }
    finally:
        db.close()


async def _master_source_usdt(mc: BinanceTradingClient, sources: list[str]) -> dict:
    """主账户各源钱包可用 USDT(futures 取 availableBalance=未占用保证金)。异常源记 0。"""
    bal: dict[str, Decimal] = {}
    for src in sources:
        try:
            if src == "spot":
                acct = await mc.get_spot_account()
                bal[src] = next((Decimal(str(b.get("free", "0"))) for b in acct.get("balances", [])
                                 if b.get("asset") == "USDT"), Decimal("0"))
            elif src == "margin":
                acct = await mc.get_margin_account()
                bal[src] = next((Decimal(str(a.get("free", "0"))) for a in acct.get("userAssets", [])
                                 if a.get("asset") == "USDT"), Decimal("0"))
            elif src == "futures":
                acct = await mc.get_futures_account()
                bal[src] = Decimal(str(acct.get("availableBalance", "0")))
        except Exception:
            bal[src] = Decimal("0")
    return bal


async def _xfer_master_to_sub(mc, amount, sources, reserve, sub_email) -> Decimal:
    """主账户(按 transfer_order 源)→ 子 MARGIN,累计补足 amount。
    护栏:总划入封顶 = min(amount, 主账户总可用 − reserve);护住主账户保留下限。返回实划总额。"""
    bal = await _master_source_usdt(mc, sources)
    total = sum(bal.values())
    budget = max(Decimal("0"), total - reserve)   # 可供自动平衡动用的总额(护住保留下限)
    remaining = min(amount, budget).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if remaining <= 0:
        return Decimal("0")
    moved = Decimal("0")
    for src in sources:
        if remaining <= 0:
            break
        amt = min(remaining, bal.get(src, Decimal("0"))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if amt <= 0:
            continue
        try:
            await mc.universal_transfer(
                asset="USDT", amount=amt,
                from_account_type=_UT[src], to_account_type="MARGIN",
                from_email=None, to_email=sub_email,
            )
            moved += amt
            remaining -= amt
        except Exception:
            continue
    return moved


async def _xfer_sub_to_master(mc, amount, sources, sub_email) -> bool:
    """子 margin → 主账户(目标取 transfer_order[0])。划回主账户无需保留下限护栏。"""
    amt = amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if amt <= 0:
        return False
    dest = sources[0] if sources else "futures"
    try:
        await mc.universal_transfer(
            asset="USDT", amount=amt,
            from_account_type="MARGIN", to_account_type=_UT[dest],
            from_email=sub_email, to_email=None,
        )
        return True
    except Exception:
        return False


async def auto_balance_margin(sub_client, sub_id, user_id, fund_rules,
                              notifier, account_note, has_open_position) -> None:
    cfg = await asyncio.to_thread(_load_sub_cfg, sub_id)
    if not cfg:
        return
    chunk = cfg["chunk"]
    if chunk is None or Decimal(str(chunk)) <= 0:
        return  # 未设单笔划 = 该子账户自动平衡禁用(安全默认)
    chunk = Decimal(str(chunk))
    floor = Decimal(str(cfg["floor"])) if cfg["floor"] is not None else Decimal("0")
    risk_thr = (Decimal(str(cfg["risk_threshold"])) if cfg["risk_threshold"] is not None
                else Decimal(str(fund_rules.risk_value_threshold)))
    reserve = Decimal(str(getattr(fund_rules, "base_margin_amount", 0) or 0))   # 主账户保留下限
    sub_email = cfg["email"]

    try:
        mi = await sub_client.get_margin_account()
    except Exception as e:
        logger.debug(f"auto_balance {account_note}: get_margin_account failed: {e}")
        return
    level = Decimal(str(mi.get("marginLevel", "999")))
    free = Decimal("0")
    for a in mi.get("userAssets", []):
        if a.get("asset") == "USDT":
            free = Decimal(str(a.get("free", "0")))
            break

    sources = [s.strip() for s in (fund_rules.transfer_order or "futures,spot,margin").split(",")
               if s.strip() in _UT]
    if not sources:
        sources = ["futures", "spot", "margin"]

    # 是否需要动作?(避免无谓查主账户余额)
    need_topup = level < risk_thr
    need_floor = (not need_topup) and floor > 0 and free < floor
    need_excess = (not need_topup and not need_floor and not has_open_position
                   and floor > 0 and free > floor and level > Decimal("2"))
    if not (need_topup or need_floor or need_excess):
        return

    from engine.trading.master_client import get_master_futures_client
    mc = await get_master_futures_client(user_id)
    if mc is None:
        return

    if need_topup:
        moved = await _xfer_master_to_sub(mc, chunk, sources, reserve, sub_email)
        if moved > 0:
            logger.info(f"auto_balance {account_note}: level {level} < {risk_thr}, +{moved} USDT master→sub")
            await notifier.send(
                "自动补保证金",
                f"账户: {account_note}\n风险值 {level} < {risk_thr},从主账户补入 {moved} USDT",
                throttle_key=f"autobal:{account_note}",
            )
    elif need_floor:
        moved = await _xfer_master_to_sub(mc, floor - free, sources, reserve, sub_email)
        if moved > 0:
            logger.info(f"auto_balance {account_note}: free {free} < floor {floor}, +{moved} master→sub")
            await notifier.send(
                "自动补保证金",
                f"账户: {account_note}\nmargin USDT {free} < 保底 {floor},从主账户补入 {moved} USDT",
                throttle_key=f"autobal:{account_note}",
            )
    elif need_excess:
        excess = free - floor
        if excess > Decimal("10") and await _xfer_sub_to_master(mc, excess, sources, sub_email):
            logger.info(f"auto_balance {account_note}: no position, return excess {excess} sub→master")
            await notifier.send(
                "保证金划出",
                f"账户: {account_note}\n无持仓,富余 {excess} USDT 划回主账户(保底留 {floor})",
                throttle_key=f"autobalout:{account_note}",
            )
