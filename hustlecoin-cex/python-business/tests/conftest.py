import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from engine.config_loader import GlobalRulesSnapshot, FundRulesSnapshot


@pytest.fixture(scope="session")
def db_engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def mock_binance_client():
    client = AsyncMock()
    client.get_margin_account.return_value = {
        "marginLevel": "2.5",
        "userAssets": [
            {"asset": "USDT", "free": "1000", "borrowed": "0", "interest": "0"},
            {"asset": "BNB", "free": "0.2", "borrowed": "0", "interest": "0"},
        ],
    }
    client.get_futures_account.return_value = {
        "totalWalletBalance": "5000",
        "availableBalance": "3000",
        "totalUnrealizedProfit": "50",
    }
    client.margin_borrow.return_value = {"tranId": 123}
    client.margin_repay.return_value = {"tranId": 124}
    client.spot_market_sell.return_value = {
        "orderId": "S001", "executedQty": "5.0",
        "fills": [{"price": "100.0", "qty": "5.0"}],
    }
    client.spot_market_buy_qty.return_value = {
        "orderId": "S002", "executedQty": "5.0",
        "fills": [{"price": "100.5", "qty": "5.0"}],
    }
    client.futures_market_long.return_value = {
        "orderId": "F001", "executedQty": "5.0",
        "avgPrice": "100.1",
    }
    client.futures_market_close.return_value = {
        "orderId": "F002",
        "avgPrice": "100.8",
    }
    client.get_lot_size.return_value = {
        "stepSize": "0.001",
        "minQty": "0.001",
        "maxQty": "999999",
    }
    client.get_margin_interest_rate.return_value = Decimal("0.001")
    client.get_funding_rate.return_value = Decimal("0.0005")
    client.transfer.return_value = {"tranId": 200}
    client.get_bnb_balance.return_value = {"margin": Decimal("0.2")}
    return client


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.notify_position_opened = AsyncMock()
    notifier.notify_position_closed = AsyncMock()
    notifier.notify_error = AsyncMock()
    notifier.notify_risk = AsyncMock()
    notifier.send = AsyncMock()
    return notifier


@pytest.fixture
def sample_global_rules():
    return GlobalRulesSnapshot(
        auto_push_spread=Decimal("0.8"),
        remove_spread=Decimal("0.5"),
        open_spread=Decimal("0.8"),
        close_spread=Decimal("0.2"),
        order_amount=Decimal("500"),
        close_funding_ratio=Decimal("1.2"),
        repay_funding_ratio=Decimal("1.2"),
        borrow_delay_sec=0,
        confirm_delay_sec=0,
        confirm_skip_spread=Decimal("2.0"),
        repay_ban_minutes=30,
        interest_filter=Decimal("1.0"),
    )


@pytest.fixture
def sample_fund_rules():
    return FundRulesSnapshot(
        bnb_min_quantity=Decimal("0.15"),
        bnb_buy_trigger_pct=Decimal("50"),
        bnb_buy_amount=Decimal("0.1"),
        bnb_debt_auto_repay=True,
        bnb_debt_threshold=Decimal("0.1"),
        usdt_debt_auto_repay=True,
        usdt_debt_threshold=Decimal("20"),
        usdt_debt_interval_sec=3600,
        bnb_convert_interval_sec=3600,
        debt_convert_interval_sec=21600,
        risk_value_threshold=Decimal("1.5"),
        single_transfer_amount=Decimal("500"),
        base_margin_amount=Decimal("500"),
        transfer_order="futures,spot,margin",
    )


@pytest.fixture
def api_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.db.session import get_db
    from app.api.sub_account import router as sub_router
    from app.api.global_rules import router as rules_router
    from app.api.fund_rules import router as fund_rules_router
    from app.api.blacklist import router as blacklist_router
    from app.api.engine_api import router as engine_router
    from app.api.symbol_rules import router as symbol_rules_router

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    TestSession = sessionmaker(bind=eng)

    test_app = FastAPI()
    test_app.include_router(sub_router)
    test_app.include_router(rules_router)
    test_app.include_router(fund_rules_router)
    test_app.include_router(blacklist_router)
    test_app.include_router(engine_router)
    test_app.include_router(symbol_rules_router)

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as client:
        yield client
