"""裸空/单腿安全网:周期对账币安真实债务,发现「孤儿债务」即告警 + 自动收口。

孤儿债务 = 币安该子账户某币 borrowed+interest 名义价值 > DUST_NOTIONAL,且 DB 里该
(sub_account, symbol) 没有任何非终态 position(非 CLOSED/FAILED)。正常借币/对冲全程都有非
终态 position(PENDING_BORROW→BORROWED_IDLE→HEDGING→SPOT_SOLD→OPEN→PENDING_REPAY→
REPAYING),命中即跳过 —— 这是防误触发的命门,让 0.5s 周期也安全。只有「债务存在但状态机
已丢失追踪」(全 CLOSED/FAILED 却仍欠债)= 孤儿 = 裸空或未追踪借币。

收口统一安全:free≥debt → 直接还币(把持有的币还回);free<debt(币已卖)→ 买回缺口再还。
两路都终于 debt=0。一套机制同时覆盖「裸空收口」+「CLOSED-position 与币安债务对账」两个诉求。

根因背景见 [[coin-hedge-via-master]] / hustle-011 裸空事故(借币后现货被市价卖、合约腿未开)。
"""
import asyncio
import json
import logging
import math
from decimal import Decimal

from app.db.session import SessionLocal
from engine.models import Position
from engine.trading.binance_trading import BinanceAPIError, SPOT_BASE

logger = logging.getLogger(__name__)

# 稳定币/手续费币不计债务对账(BNB 借贷利息属正常,不视为裸空)
_STABLE = {"USDT", "BNB", "BUSD", "USDC", "FDUSD", "TUSD"}
_TERMINAL = ("CLOSED", "FAILED")
DUST_NOTIONAL = Decimal("2.0")   # 债务名义价值 < 2 USDT 视为尘埃,不处理(避免对 0.00x 残留反复动作)

# per-(account:symbol) 连续命中计数(去抖:需连续 2 次=1s 持续才动作,排除借币提交瞬间的微race)
_hit_counts: dict[str, int] = {}


def _has_active_position(sub_account_id: int, symbol: str) -> bool:
    """该 (sub_account, symbol) 是否有非终态 position(状态机仍在追踪)。"""
    db = SessionLocal()
    try:
        return db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
            Position.status.notin_(_TERMINAL),
        ).count() > 0
    finally:
        db.close()


def _asset_state(ma: dict, asset: str):
    for a in ma.get("userAssets", []):
        if a.get("asset") == asset:
            b = Decimal(str(a.get("borrowed", "0") or 0))
            i = Decimal(str(a.get("interest", "0") or 0))
            f = Decimal(str(a.get("free", "0") or 0))
            return b, i, f
    return Decimal("0"), Decimal("0"), Decimal("0")


async def run_naked_short_guard(client, redis, sub_account_id, user_id, notifier,
                                account_note, *, auto_remediate=True):
    """对账本子账户币安真实债务,孤儿债务即告警 + (可选)自动收口。每周期由 worker 调一次。"""
    ma = await client.get_margin_account()
    for a in ma.get("userAssets", []):
        asset = a.get("asset")
        if not asset or asset in _STABLE:
            continue
        borrowed = Decimal(str(a.get("borrowed", "0") or 0))
        interest = Decimal(str(a.get("interest", "0") or 0))
        free = Decimal(str(a.get("free", "0") or 0))
        debt = borrowed + interest
        if debt <= 0:
            continue
        symbol = f"{asset}USDT"
        key = f"{sub_account_id}:{symbol}"

        # 命门:有非终态 position → 状态机在管(含正常对冲中间窗口),跳过 + 清去抖计数
        if await asyncio.to_thread(_has_active_position, sub_account_id, symbol):
            _hit_counts.pop(key, None)
            continue

        # 孤儿候选:取现价算名义价值(只对孤儿打 ticker,正常态不打)
        try:
            tk = await client._request("GET", f"{SPOT_BASE}/api/v3/ticker/price",
                                       {"symbol": symbol}, signed=False)
            price = Decimal(str(tk.get("price", "0") or 0))
        except Exception:
            price = Decimal("0")
        if price <= 0 or debt * price < DUST_NOTIONAL:
            _hit_counts.pop(key, None)
            continue

        # 去抖:需连续 2 次命中才动作
        _hit_counts[key] = _hit_counts.get(key, 0) + 1
        if _hit_counts[key] < 2:
            continue

        # Redis 冷却:收口/告警后 5min 内不重复(防结算期反复触发)
        cd_key = f"engine:nakedfix:{sub_account_id}:{symbol}"
        try:
            if await redis.get(cd_key):
                continue
        except Exception:
            pass
        _hit_counts.pop(key, None)

        # 主账户合约持仓量(仅作告警上下文,不参与判定)
        fut_qty = None
        try:
            raw = await redis.get(f"balance:latest:{user_id}")
            if raw:
                fut_qty = (json.loads(raw).get("master_futures_positions") or {}).get(symbol)
        except Exception:
            pass

        logger.warning(
            f"NAKED SHORT (orphan debt) acct{sub_account_id} {symbol}: "
            f"borrowed={borrowed} interest={interest} free={free} fut={fut_qty} notional≈{debt*price:.2f}U"
        )
        try:
            await notifier.notify_naked_short(account_note, symbol, debt, free, fut_qty)
        except Exception as e:
            logger.warning(f"notify_naked_short failed: {e}")

        # 占冷却(无论是否自动收口,都防 5min 内刷屏/重复动作)
        try:
            await redis.set(cd_key, "1", ex=300)
        except Exception:
            pass

        if not auto_remediate:
            continue

        try:
            await _remediate(client, symbol, asset, debt, free, price, ma,
                             sub_account_id, notifier, account_note)
        except Exception as e:
            logger.error(f"naked short remediate failed acct{sub_account_id} {symbol}: {e}")
            try:
                await notifier.notify_error(account_note, f"裸空收口失败 {symbol}", str(e))
            except Exception:
                pass


async def _remediate(client, symbol, asset, debt, free, price, ma,
                     sub_account_id, notifier, account_note):
    """收口:free<debt 时用 USDT 买回缺口(NO_SIDE_EFFECT)→ 还币。USDT 不足则只告警人工干预。"""
    _, _, usdt_free = (Decimal("0"), Decimal("0"),
                       Decimal(str(next((x.get("free", "0") for x in ma.get("userAssets", [])
                                         if x.get("asset") == "USDT"), "0") or 0)))
    need = debt - free
    if need > 0:
        flt = await client._get_spot_filters(symbol)
        step = flt["step"]
        buy_qty = (Decimal(math.ceil(need / step)) + 2) * step   # 取整 + 2 档缓冲(覆盖利息累积/精度)
        cost = buy_qty * price * Decimal("1.01")
        if cost > usdt_free:
            logger.warning(f"naked short remediate acct{sub_account_id} {symbol}: USDT 不足 "
                           f"(需≈{cost:.2f} 仅{usdt_free:.2f}),需人工干预")
            await notifier.notify_error(
                account_note, f"裸空收口需人工干预 {symbol}",
                f"需买回 {need} {asset}(≈{(need*price):.2f}U),USDT 仅 {usdt_free:.2f},不足以买回",
            )
            return
        await client.spot_market_buy_qty(symbol, buy_qty, is_margin=True)
        await asyncio.sleep(4)   # 容忍杠杆户秒级读-写结算延迟(买回后 free 不会立即可见)

    # 还币:重读权威债务+free,按 min 全额还,-3041 退避重试
    ma2 = await client.get_margin_account()
    b2, i2, f2 = _asset_state(ma2, asset)
    repay = min(b2 + i2, f2)
    if repay > 0:
        for attempt in range(5):
            try:
                await client.margin_repay(asset, repay)
                break
            except BinanceAPIError as e:
                if getattr(e, "api_code", None) == -3041 and attempt < 4:
                    repay *= Decimal("0.999")
                    continue
                raise
    await asyncio.sleep(3)
    ma3 = await client.get_margin_account()
    b3, i3, _ = _asset_state(ma3, asset)
    final_debt = b3 + i3
    logger.info(f"naked short remediated acct{sub_account_id} {symbol}: debt {debt} -> {final_debt}")
    try:
        await notifier.notify_naked_short(account_note, symbol, final_debt, Decimal("0"), None, remediated=True)
    except Exception:
        pass
