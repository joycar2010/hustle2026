"""OKX 原生借币执行器(coin ①b-2)——卖借+同所永续对冲合一,直达 OPEN。

⚠️与币安两相(borrow-idle→hedge)根本不同(①b-1 canary 实证):OKX 借币=cross 卖单
(卖不持有的币自动借入做空),对冲=同所永续多,平仓=买回现货(抵债)+平永续。故 OKX
仓位跳过 BORROWED_IDLE,PENDING_BORROW→OPEN 一步到位,标记 hedge_account="okx"。

账户隔离:用独立子账户 joycar002(env OKX_BORROW_*,与币安子账户/dualperp 全隔离)。
安全铁律:①卖单成交=已裸空,对冲失败**立即买回回滚**(开仓期裸空自愈);②所有下单穿价/
市价确保成交;③httpx client 与主循环共享(事件循环安全);④未配 key=OKX 分支静默禁用。

门控(worker 侧):borrow_venues 含 okx + symbol∈OKX_ARM_SYMBOLS(默认空=零生产影响)。
"""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from coincore.db import SessionLocal
from engine.models import Position
from engine.trading.okx_borrow import OkxBorrow

logger = logging.getLogger(__name__)

_OKX_CFG = {
    "key": os.environ.get("OKX_BORROW_KEY", ""),
    "secret": os.environ.get("OKX_BORROW_SECRET", ""),
    "passphrase": os.environ.get("OKX_BORROW_PASSPHRASE", ""),
}
OKX_ARM_SYMBOLS = {
    x.strip().upper() for x in os.environ.get("OKX_ARM_SYMBOLS", "").split(",") if x.strip()
}
CROSS_BPS = Decimal(os.environ.get("OKX_CROSS_BPS", "30"))  # 穿价幅度(现货买回)

_okx: OkxBorrow | None = None


def okx_available() -> bool:
    return bool(_OKX_CFG["key"] and _OKX_CFG["secret"] and _OKX_CFG["passphrase"])


def okx_eligible(symbol: str, borrow_venues: list[str]) -> bool:
    """OKX 分支门控:key 齐 + borrow_venues 含 okx + 该币显式武装。默认空武装=永不触发。"""
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return (okx_available() and "okx" in (borrow_venues or [])
            and symbol.upper() in OKX_ARM_SYMBOLS)


def _client() -> OkxBorrow:
    global _okx
    if _okx is None:
        _okx = OkxBorrow(_OKX_CFG)
    return _okx


async def execute_okx_open(sub_account_id: int, symbol: str, notional_usdt: float,
                           account_note: str, user_id: int = None) -> int | None:
    """OKX 原生开仓:卖借现货(借入做空)+ 同所永续多对冲 → OPEN。
    对冲失败立即买回回滚(开仓期裸空自愈)。返回 pos_id 或 None。"""
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    okx = _client()
    db = SessionLocal()
    position = Position(sub_account_id=sub_account_id, symbol=symbol, base_asset=base,
                        status="PENDING_BORROW", user_id=user_id, hedge_account="okx")
    db.add(position)
    db.commit()
    db.refresh(position)
    pos_id = position.id

    async with httpx.AsyncClient(timeout=15) as cli:
        try:
            # 可借性 + 现价 + 数量
            max_loan = await okx.max_borrowable(cli, base)
            price = await okx.ticker(cli, base)
            if max_loan <= 0 or price <= 0:
                position.status = "FAILED"
                position.error_message = f"OKX 无券或无价 (maxLoan={max_loan} px={price})"
                db.commit(); db.close()
                return None
            min_sz, lot_sz = await okx.spot_lot(cli, base)
            qty = float(Decimal(str(notional_usdt)) / Decimal(str(price)))
            # 对齐 lot(向下),且不超过可借
            if lot_sz > 0:
                qty = (qty // lot_sz) * lot_sz
            qty = min(qty, max_loan * 0.95)  # 留 5% 抵押冗余
            if qty <= 0 or (min_sz > 0 and qty < min_sz) or qty * price < 1:
                position.status = "FAILED"
                position.error_message = f"OKX qty 太小/超券 (qty={qty} min={min_sz})"
                db.commit(); db.close()
                return None

            # ① 卖借:cross 市价卖 → 借入 base 做空(成交即裸空,下一步必须对冲)
            ok, res = await okx.borrow_by_sell(cli, base, qty)
            if not ok:
                position.status = "FAILED"
                position.error_message = f"OKX 卖借失败: {res.get('err')}"
                db.commit(); db.close()
                return None
            logger.info(f"OKX borrow-by-sell {symbol} qty={qty} @~{price}")

            # ② 对冲:同所永续多。失败→立即买回回滚(裸空自愈)
            ok2, res2 = await okx.hedge_perp(cli, base, qty, "buy")
            if not ok2:
                logger.error(f"OKX hedge FAILED {symbol}: {res2.get('err')} → 立即买回回滚")
                await okx.repay_by_buy(cli, base, qty, price)  # 买回抵债,平掉裸空
                position.status = "FAILED"
                position.error_message = f"OKX 对冲失败已回滚: {res2.get('err')}"
                db.commit(); db.close()
                return None

            # ③ delta 中性,落 OPEN
            position.status = "OPEN"
            position.borrow_qty = Decimal(str(qty))
            position.spot_sell_qty = Decimal(str(qty))
            position.spot_sell_price = Decimal(str(price))
            position.futures_long_qty = Decimal(str(qty))
            position.futures_long_price = Decimal(str(price))
            position.open_usdt_amount = Decimal(str(round(qty * price, 4)))
            position.opened_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"OKX OPEN {symbol} qty={qty} 张={res2.get('contracts')} (卖借+永续对冲)")
            try:
                await __import__("engine.trading.order_executor", fromlist=["_publish_position_update"])._publish_position_update(position, user_id, account_note)
            except Exception:
                pass
            return pos_id
        except Exception as e:
            logger.exception(f"OKX open crashed {symbol}")
            position.status = "FAILED"
            position.error_message = f"OKX open 异常: {e!r}"
            db.commit()
            db.close()
            return None
        finally:
            if db.is_active:
                db.close()


async def execute_okx_close(position: Position, account_note: str) -> bool:
    """OKX 原生平仓:平永续 + 买回现货(抵债)→ CLOSED。残债/残仓即告警。"""
    base = position.symbol[:-4] if position.symbol.endswith("USDT") else position.symbol
    okx = _client()
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status not in ("OPEN", "CLOSING_FUTURES"):
        db.close()
        return False
    pos.status = "CLOSING_FUTURES"
    db.commit()
    async with httpx.AsyncClient(timeout=15) as cli:
        try:
            qty = float(pos.borrow_qty or 0)
            price = await okx.ticker(cli, base)
            # ① 平永续(reduceOnly 反向)
            contracts = await okx.perp_position(cli, base)
            if contracts > 0:
                await okx.close_perp(cli, base, contracts, "sell")
            # ② 买回现货抵债(穿价限价,ref=现价)
            debt = await okx.debt(cli, base)
            buyback = max(qty, debt)  # 债务可能含微利息,按较大者买回
            if buyback > 0 and price > 0:
                await okx.repay_by_buy(cli, base, buyback, price)
            # ③ 复核
            import asyncio as _a
            await _a.sleep(2)
            resid_debt = await okx.debt(cli, base)
            resid_pos = await okx.perp_position(cli, base)
            if resid_debt > (qty * 0.02) or abs(resid_pos) > 0:
                logger.error(f"OKX close 残留 {base}: debt={resid_debt} perp={resid_pos} 张")
                pos.error_message = f"OKX 平仓残留 debt={resid_debt} perp={resid_pos},需人工核"
                db.commit(); db.close()
                return False
            pos.status = "CLOSED"
            pos.closed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"OKX CLOSED {position.symbol} (平永续+买回抵债)")
            return True
        except Exception as e:
            logger.exception(f"OKX close crashed {position.symbol}")
            pos.error_message = f"OKX close 异常: {e!r}"
            db.commit()
            db.close()
            return False
        finally:
            if db.is_active:
                db.close()
