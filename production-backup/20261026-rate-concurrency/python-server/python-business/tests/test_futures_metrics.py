from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.futures_metrics import count_confirmed_futures_orders, dedupe_confirmed_futures_orders


def row(**values):
    defaults = dict(action="FUTURES_LONG", status="SUCCESS", quantity="1", order_id="1",
                    symbol="FILUSDT", sub_account_id=1, hedge_account="master")
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_counts_open_close_and_append_orders_once_per_real_account_symbol_order():
    rows = [
        row(order_id="1001"),
        row(order_id="1001", sub_account_id=2),  # shared master hedge duplicate
        row(action="FUTURES_LIMIT_FILL", order_id="1002", quantity="0.5"),
        row(action="FUTURES_MARKET_FALLBACK", order_id="1002", quantity="0.5"),
        row(action="FUTURES_CLOSE", order_id="1003"),
        row(action="FUTURES_CLOSE", order_id="1004", hedge_account="sub", sub_account_id=1),
    ]
    assert dedupe_confirmed_futures_orders(rows) == 4


def test_rejects_failed_zero_missing_and_non_execution_rows():
    rows = [
        row(status="FAILED", order_id="1005"),
        row(quantity="0", order_id="1006"),
        row(quantity="NaN", order_id="1007"),
        row(order_id="", quantity="1"),
        row(order_id=None, quantity="1"),
        row(action="BORROW", order_id="1008"),
    ]
    assert dedupe_confirmed_futures_orders(rows) == 0


def test_user_subaccounts_are_isolated_when_order_id_repeats():
    rows = [
        row(order_id="1009", hedge_account="sub", sub_account_id=1),
        row(order_id="1009", hedge_account="sub", sub_account_id=2),
        row(order_id="1009", hedge_account="master", sub_account_id=1),
        row(order_id="1009", hedge_account="master", sub_account_id=2),
        row(order_id="1009", hedge_account="master", sub_account_id=2, symbol="CVCUSDT"),
    ]
    assert dedupe_confirmed_futures_orders(rows) == 4


def test_sqlalchemy_query_is_user_scoped_and_dedupes_limit_summary():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # Load the compatibility Base module first; importing engine.models alone
    # would recurse through app.db.models' legacy re-export.
    from app.db.models import Base  # noqa: F401
    from engine.models import Position, TradeLog

    engine = create_engine("sqlite:///:memory:")
    Position.__table__.create(engine)
    TradeLog.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add_all([
        Position(id=1, user_id=7, sub_account_id=1, symbol="FILUSDT", base_asset="FIL", status="OPEN", hedge_account="master"),
        Position(id=2, user_id=8, sub_account_id=2, symbol="FILUSDT", base_asset="FIL", status="OPEN", hedge_account="master"),
    ])
    db.add_all([
        TradeLog(user_id=7, position_id=1, sub_account_id=1, action="FUTURES_LIMIT_FILL", symbol="FILUSDT", quantity="1", order_id="2001", status="SUCCESS"),
        TradeLog(user_id=7, position_id=1, sub_account_id=1, action="FUTURES_LONG", symbol="FILUSDT", quantity="1", order_id="limit", status="SUCCESS"),
        TradeLog(user_id=7, position_id=1, sub_account_id=1, action="FUTURES_CLOSE", symbol="FILUSDT", quantity="1", order_id="2002", status="SUCCESS"),
        TradeLog(user_id=8, position_id=2, sub_account_id=2, action="FUTURES_LONG", symbol="FILUSDT", quantity="1", order_id="2001", status="SUCCESS"),
        TradeLog(user_id=7, position_id=1, sub_account_id=1, action="FUTURES_LONG", symbol="FILUSDT", quantity="1", order_id="2003", status="FAILED"),
    ])
    db.commit()
    assert count_confirmed_futures_orders(db, 7) == 2
    assert count_confirmed_futures_orders(db, 8) == 1
