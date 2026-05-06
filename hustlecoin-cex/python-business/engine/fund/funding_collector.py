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
):
    db: Session = SessionLocal()
    try:
        positions = db.query(Position).filter(
            Position.sub_account_id == sub_account_id,
            Position.status == "OPEN",
        ).all()

        for pos in positions:
            try:
                income = await client.get_funding_income(pos.symbol)
                total_funding = sum(Decimal(str(item.get("income", "0"))) for item in income)

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
