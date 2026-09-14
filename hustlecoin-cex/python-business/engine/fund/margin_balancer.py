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
单一规则为空时按「子账户单一规则 → 用户通用资金规则 → 系统默认」继承单笔划转和风控阈值；保底额仍需子账户明确设置。所有异常吞掉(不崩 worker)。
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

_DEFAULT_TRANSFER_AMOUNT = Decimal("500")
_DEFAULT_RISK_THRESHOLD = Decimal("1.5")


def _positive(value) -> Decimal | None:
    """Return a positive decimal or None for an unset/disabled value."""
    if value is None:
        return None
    try:
        value = Decimal(str(value))
    except Exception:
        return None
    return value if value > 0 else None


def _effective_balance_policy(cfg: dict, fund_rules) -> tuple[Decimal, Decimal, Decimal]:
    """Resolve sub-account -> user common rule -> system default precedence.

    A blank sub-account transfer amount used to disable auto-balance even when
    the user-level common rule had a value.  Blank values now inherit the
    common FundRules value, then the documented system defaults.  The floor is
    intentionally opt-in per sub-account: it is a target for the child margin
    wallet, not the master's reserve.
    """
    amount = (_positive(cfg.get("chunk"))
              or _positive(getattr(fund_rules, "single_transfer_amount", None))
              or _DEFAULT_TRANSFER_AMOUNT)
    risk = (_positive(cfg.get("risk_threshold"))
            or _positive(getattr(fund_rules, "risk_value_threshold", None))
            or _DEFAULT_RISK_THRESHOLD)
    floor = _positive(cfg.get("floor")) or Decimal("0")
    return amount, risk, floor


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


async def _sweep_master_spot_to_futures(mc) -> Decimal:
    """归集主账户现货 USDT 到合约钱包，供对冲腿使用。"""
    bal = await _master_source_usdt(mc, ["spot"])
    amount = bal.get("spot", Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if amount <= 0:
        return Decimal("0")
    try:
        await mc.transfer("MAIN_UMFUTURE", "USDT", amount)
        logger.info("master spot→futures sweep: +%s USDT", amount)
        return amount
    except Exception as exc:
        logger.warning("master spot→futures sweep failed amount=%s: %s", amount, exc)
        return Decimal("0")


async def _xfer_master_to_sub(mc, amount, sources, reserve, sub_email) -> Decimal:
    """主账户(按 transfer_order 源)→ 子 MARGIN,累计补足 amount。
    护栏:总划入封顶 = min(amount, 主账户总可用 − reserve);护住主账户保留下限。返回实划总额。"""
    # Workers for one user share the master client. Serialize the balance
    # snapshot and transfers so concurrent sub-accounts cannot spend the same
    # master surplus based on stale snapshots.
    lock = getattr(mc, "_auto_transfer_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        mc._auto_transfer_lock = lock
    async with lock:
        # Always read both wallets for the sweep/gate, even if an older
        # transfer_order omitted spot or futures from its source list.
        read_sources = list(dict.fromkeys([*sources, "spot", "futures"]))
        bal = await _master_source_usdt(mc, read_sources)
        # The configured lower limit is a gate on the master's futures wallet,
        # not a target that leaves the remainder stranded in spot. Repatriate
        # transferable master spot USDT into futures first so the hedge leg can
        # use it. Then only the futures surplus above the configured limit may
        # fund child accounts.
        spot_free = bal.get("spot", Decimal("0"))
        spot_amt = spot_free.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if spot_amt > 0:
            try:
                await mc.transfer("MAIN_UMFUTURE", "USDT", spot_amt)
                logger.info("master spot→futures sweep: +%s USDT", spot_amt)
                bal = await _master_source_usdt(mc, read_sources)
            except Exception as exc:
                logger.warning("master spot→futures sweep failed amount=%s: %s", spot_amt, exc)

        futures_available = bal.get("futures", Decimal("0"))
        if futures_available < reserve:
            logger.info(
                "master->sub blocked: futures available %s is below configured reserve %s",
                futures_available, reserve,
            )
            return Decimal("0")

        # Do not consume spot/margin directly. All child funding is sourced
        # from the futures surplus after the spot sweep.
        futures_surplus = max(Decimal("0"), futures_available - reserve)
        budget = futures_surplus
        remaining = min(amount, budget).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if remaining <= 0:
            return Decimal("0")
        moved = Decimal("0")
        for src in ("futures",):
            if remaining <= 0:
                break
            available = max(Decimal("0"), bal.get(src, Decimal("0")) - reserve)
            amt = min(remaining, available).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if amt <= 0:
                continue
            try:
                if src == "futures":
                    # Binance does not support a direct USDT_FUTURE ->
                    # sub-account MARGIN universal transfer (-9000).
                    # Move the protected surplus to the master's SPOT wallet
                    # first, then use the supported SPOT -> sub MARGIN leg.
                    await mc.transfer("UMFUTURE_MAIN", "USDT", amt)
                    await mc.universal_transfer(
                        asset="USDT", amount=amt,
                        from_account_type="SPOT", to_account_type="MARGIN",
                        from_email=None, to_email=sub_email,
                    )
                else:
                    await mc.universal_transfer(
                        asset="USDT", amount=amt,
                        from_account_type=_UT[src], to_account_type="MARGIN",
                        from_email=None, to_email=sub_email,
                    )
                moved += amt
                remaining -= amt
            except Exception as exc:
                logger.warning(
                    "master->sub transfer failed source=%s amount=%s target=%s: %s",
                    src, amt, sub_email, exc,
                )
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
    chunk, risk_thr, floor = _effective_balance_policy(cfg, fund_rules)
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
    from engine.trading.master_client import get_master_futures_client
    mc = await get_master_futures_client(user_id)
    if mc is None:
        return

    # Sweep spot surplus on every balancing cycle so master hedge collateral
    # is consolidated even when no child currently needs a top-up.
    await _sweep_master_spot_to_futures(mc)
    if not (need_topup or need_floor or need_excess):
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
