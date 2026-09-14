import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from engine.models import Position
from engine.trading.binance_trading import BinanceTradingClient

logger = logging.getLogger(__name__)


async def collect_funding_fees(
    client: BinanceTradingClient,
    sub_account_id: int,
    user_id: int = None,
):
    """累计资金费/利息 → funding_rate_ratio(驱动自动平仓/还币的口径)。

    口径: income 只取 startTime=opened_at 之后(修复历史持仓资金费混入)。
    hedge_account="master" 的持仓走主账户 client 取 income,且同 symbol 的主账户
    净仓由多个子账户持仓共享 —— 按各自 futures_long_qty 占比分摊(近似:按当前
    在场持仓的量比;已平仓位的历史份额不回溯)。
    """
    db: Session = SessionLocal()
    try:
        positions = db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.status == "OPEN",
        ).all()

        master_fc = None
        master_fc_tried = False

        for pos in positions:
            try:
                on_master = getattr(pos, "hedge_account", None) == "master"
                fc = client
                if on_master:
                    if not master_fc_tried:
                        master_fc_tried = True
                        from engine.trading.master_client import get_master_futures_client
                        # 用调用方传入的 user_id(SubAccount.user_id)——pos.user_id 存量行可能为 NULL
                        master_fc = await get_master_futures_client(
                            user_id if user_id is not None else pos.user_id)
                    if master_fc is None:
                        continue   # master client 不可用,跳过本轮(不写错误口径)
                    fc = master_fc

                start_ms = int(pos.opened_at.timestamp() * 1000) if pos.opened_at else None
                income = await fc.get_funding_income(pos.symbol, start_time=start_ms)
                total_funding = sum(Decimal(str(item.get("income", "0"))) for item in income)

                if on_master and pos.futures_long_qty:
                    # 主账户共仓: 按全用户同 symbol 在场 master 持仓的量比分摊
                    eff_uid = user_id if user_id is not None else pos.user_id
                    uid_cond = (Position.user_id == eff_uid) if eff_uid is not None \
                        else Position.user_id.is_(None)
                    total_qty = db.query(Position).filter(
                        uid_cond,
                        Position.symbol == pos.symbol,
                        Position.status == "OPEN",
                        Position.hedge_account == "master",
                    ).with_entities(Position.futures_long_qty).all()
                    qty_sum = sum((q[0] or Decimal("0")) for q in total_qty)
                    if qty_sum > 0:
                        total_funding = total_funding * pos.futures_long_qty / qty_sum

                hours_open = Decimal("0")
                if pos.opened_at:
                    delta = datetime.now(timezone.utc) - pos.opened_at
                    hours_open = Decimal(str(delta.total_seconds())) / Decimal("3600")

                interest_cost = Decimal("0")
                if pos.borrow_interest_rate and pos.borrow_qty and hours_open > 0:
                    interest_cost = pos.borrow_interest_rate * pos.borrow_qty * hours_open / Decimal("24")

                pos.cumulative_funding_fee = total_funding
                pos.cumulative_interest = interest_cost

                if interest_cost > 0:
                    pos.funding_rate_ratio = abs(total_funding) / interest_cost

            except Exception as e:
                logger.warning(f"Funding collection failed for {pos.symbol}: {e}")

        db.commit()
    except Exception as e:
        logger.warning(f"Funding collector error: {e}")
    finally:
        db.close()
