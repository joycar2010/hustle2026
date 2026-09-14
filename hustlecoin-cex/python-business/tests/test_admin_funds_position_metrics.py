from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.admin_funds import _position_metrics
from app.db.models import Base, SubAccount
from engine.models import Position


def test_position_metrics_separates_active_notional_and_settled_pnl():
    engine = create_engine("sqlite://")
    # Only the two tables used by the aggregate are needed.  Creating them in
    # dependency order keeps this test independent from the production schema.
    SubAccount.__table__.create(engine)
    Position.__table__.create(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(SubAccount(id=10, user_id=7, note="04", email="x", api_key="k", api_secret="s"))
    db.add_all([
        Position(
            sub_account_id=10, user_id=None, symbol="FILUSDT", base_asset="FIL",
            status="BORROWED_IDLE", open_usdt_amount=Decimal("20"),
        ),
        Position(
            sub_account_id=10, user_id=None, symbol="SLPUSDT", base_asset="SLP",
            status="CLOSED", open_usdt_amount=Decimal("30"),
            realized_pnl=Decimal("-0.46"), cumulative_funding_fee=Decimal("0.02"),
            cumulative_interest=Decimal("0.01"),
        ),
        Position(
            sub_account_id=10, user_id=None, symbol="BTCUSDT", base_asset="BTC",
            status="FAILED", open_usdt_amount=Decimal("99"), realized_pnl=Decimal("9"),
        ),
    ])
    db.commit()

    per_user, totals = _position_metrics(db)

    assert per_user[7] == {
        "notional": 20.0,
        "open_positions": 1,
        "realized_net_pnl": -0.45,
        "closed_positions": 1,
    }
    assert totals == {
        "position_notional": 20.0,
        "open_positions": 1,
        "realized_net_pnl": -0.45,
        "closed_positions": 1,
        "today_pnl": 0.0,
        "today_closed": 0,
    }
    db.close()
    engine.dispose()
