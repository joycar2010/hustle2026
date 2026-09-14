"""残留负债清理(全仓负债转换间隔 debt_convert_interval_sec)。

清掉子账户里「无对应持仓的小额非 USDT 币种欠款」——即开/平/还过程中残留的尾单债
(如外部平仓/部分成交后欠一点点币)。每个 base 资产:
  · 仅当该 base **无任何进行中持仓**(排除尾单=合法持仓债)才处理;
  · 若 margin 已持有该币 free ≥ 欠款 → 直接 margin_repay(纯还债,无交易,零风险);
  · 否则缺口很小(名义 < 阈值)时,用现有 USDT 现货买回缺口再还(限小额);USDT 不足则跳过。

安全:只清小额、只清无持仓、不自动借 USDT;所有异常吞掉(不崩 worker)。
价格取 spread_feed(spot_ask);无行情的币跳过(无法估值/买回,留人工)。
"""
from __future__ import annotations

import logging
from decimal import Decimal

from app.db.session import SessionLocal
from engine.models import Position

logger = logging.getLogger(__name__)

_ACTIVE_STATUS = ("PENDING_BORROW", "BORROWED_IDLE", "HEDGING", "SPOT_SOLD", "OPEN", "PENDING_REPAY")
_SKIP_ASSETS = {"USDT", "BNB"}
_MAX_DUST_USDT = Decimal("50")   # 单币残留债清理名义上限(超过视为非尾单,不自动动)


def _bases_with_active_position(sub_id: int) -> set[str]:
    db = SessionLocal()
    try:
        rows = db.query(Position.base_asset).filter(
            Position.sub_account_id == sub_id,
            Position.status.in_(_ACTIVE_STATUS),
        ).distinct().all()
        return {r[0] for r in rows if r[0]}
    finally:
        db.close()


async def run_debt_convert(client, sub_id, spread_feed, notifier, account_note) -> None:
    try:
        mi = await client.get_margin_account()
    except Exception as e:
        logger.debug(f"debt_convert {account_note}: get_margin_account failed: {e}")
        return
    busy = await _safe_bases(sub_id)

    for a in mi.get("userAssets", []):
        asset = a.get("asset")
        if asset in _SKIP_ASSETS:
            continue
        borrowed = Decimal(str(a.get("borrowed", "0"))) + Decimal(str(a.get("interest", "0")))
        if borrowed <= 0:
            continue
        if asset in busy:
            continue  # 有进行中持仓 = 合法借币债,不动

        symbol = f"{asset}USDT"
        sp = spread_feed.get_symbol(symbol) if spread_feed else None
        price = Decimal(str(sp.spot_ask)) if (sp and getattr(sp, "spot_ask", 0)) else None
        if price is None or price <= 0:
            continue  # 无行情,无法估值/买回 → 留人工

        notional = borrowed * price
        if notional > _MAX_DUST_USDT:
            continue  # 超小额上限,不自动清(防误清大额债)

        free_coin = Decimal(str(a.get("free", "0")))
        try:
            if free_coin >= borrowed:
                # 已持有足额 → 直接还(纯还债,无交易)
                await client.margin_repay(asset, borrowed)
                await notifier.send("残留负债清理",
                                    f"账户: {account_note}\n{asset} 残留欠款 {borrowed} 已用持有币直接还清",
                                    throttle_key=f"debtconv:{account_note}:{asset}")
                logger.info(f"debt_convert {account_note}: repaid {asset} {borrowed} from held balance")
                continue
            # 缺口小额 → 用现有 USDT 买回缺口再还
            shortfall = borrowed - free_coin
            usdt_free = next((Decimal(str(x.get("free", "0"))) for x in mi.get("userAssets", [])
                              if x.get("asset") == "USDT"), Decimal("0"))
            if shortfall * price > usdt_free:
                continue  # USDT 不足,不自动借,跳过(留人工/下轮)
            await client.spot_market_buy_qty(symbol, shortfall)
            await client.margin_repay(asset, borrowed)
            await notifier.send("残留负债清理",
                                f"账户: {account_note}\n{asset} 残留欠款 {borrowed}(名义≈{notional:.2f}U)买回补足并还清",
                                throttle_key=f"debtconv:{account_note}:{asset}")
            logger.info(f"debt_convert {account_note}: bought {shortfall} {asset} + repaid {borrowed}")
        except Exception as e:
            logger.debug(f"debt_convert {account_note}: clear {asset} failed: {e}")


async def _safe_bases(sub_id: int):
    import asyncio
    return await asyncio.to_thread(_bases_with_active_position, sub_id)
