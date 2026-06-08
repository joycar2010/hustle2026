from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from engine.config_loader import FundRulesSnapshot
from engine.fund.bnb_manager import run_bnb_check
from engine.fund.debt_repayer import run_usdt_debt_check
from engine.fund.transfer_manager import ensure_margin_balance


def _fund_rules(**kw):
    defaults = dict(
        bnb_min_quantity=Decimal("0.15"),
        bnb_buy_trigger_pct=Decimal("50"),
        bnb_buy_amount=Decimal("0.1"),
        bnb_debt_auto_repay=True,
        bnb_debt_threshold=Decimal("0.1"),
        usdt_debt_auto_repay=True,
        usdt_debt_threshold=Decimal("20"),
        single_transfer_amount=Decimal("500"),
        transfer_order="futures,spot,margin",
    )
    defaults.update(kw)
    return FundRulesSnapshot(**defaults)


def _notifier():
    n = AsyncMock()
    n.send = AsyncMock()
    return n


# --- BNB manager tests ---

@pytest.mark.asyncio
async def test_bnb_buy_triggered_when_low():
    client = AsyncMock()
    client.get_bnb_balance.return_value = {"margin": Decimal("0.05")}
    client.get_margin_account.return_value = {
        "userAssets": [{"asset": "BNB", "free": "0.05", "borrowed": "0", "interest": "0"}],
    }
    notifier = _notifier()
    rules = _fund_rules()

    await run_bnb_check(client, rules, notifier, "test")

    # trigger = 0.15 * 50/100 = 0.075; balance 0.05 <= 0.075 → buy
    client.spot_market_buy_qty.assert_called_once_with("BNBUSDT", Decimal("0.1"))
    notifier.send.assert_called_once()


@pytest.mark.asyncio
async def test_bnb_no_buy_when_sufficient():
    client = AsyncMock()
    client.get_bnb_balance.return_value = {"margin": Decimal("0.20")}
    notifier = _notifier()
    rules = _fund_rules()

    await run_bnb_check(client, rules, notifier, "test")

    client.spot_market_buy_qty.assert_not_called()


# --- USDT debt repayer tests ---

@pytest.mark.asyncio
async def test_usdt_debt_repay_triggered():
    client = AsyncMock()
    client.get_margin_account.return_value = {
        "userAssets": [
            {"asset": "USDT", "free": "100", "borrowed": "50", "interest": "0.5"},
        ],
    }
    notifier = _notifier()
    rules = _fund_rules()

    await run_usdt_debt_check(client, rules, notifier, "test")

    # borrowed 50 > threshold 20 → repay min(50, 100) = 50
    client.margin_repay.assert_called_once_with("USDT", Decimal("50"))


@pytest.mark.asyncio
async def test_usdt_debt_skip_when_disabled():
    client = AsyncMock()
    notifier = _notifier()
    rules = _fund_rules(usdt_debt_auto_repay=False)

    await run_usdt_debt_check(client, rules, notifier, "test")

    client.get_margin_account.assert_not_called()


# --- Transfer manager tests ---

@pytest.mark.asyncio
async def test_transfer_skips_when_balance_sufficient():
    client = AsyncMock()
    client.get_margin_account.return_value = {
        "userAssets": [{"asset": "USDT", "free": "1000", "borrowed": "0", "interest": "0"}],
    }
    rules = _fund_rules()

    result = await ensure_margin_balance(client, rules, Decimal("500"))

    assert result is True
    client.transfer.assert_not_called()


@pytest.mark.asyncio
async def test_transfer_tries_priority_order():
    client = AsyncMock()
    client.get_margin_account.return_value = {
        "userAssets": [{"asset": "USDT", "free": "100", "borrowed": "0", "interest": "0"}],
    }
    client.transfer.side_effect = [Exception("futures failed"), None]
    rules = _fund_rules(transfer_order="futures,spot,margin")

    result = await ensure_margin_balance(client, rules, Decimal("500"))

    assert result is True
    assert client.transfer.call_count == 2
    # First call: futures→margin failed, second: spot→margin succeeded
    calls = client.transfer.call_args_list
    assert calls[0][0][0] == "UMFUTURE_MARGIN"
    assert calls[1][0][0] == "MAIN_MARGIN"


@pytest.mark.asyncio
async def test_transfer_all_fail_returns_false():
    client = AsyncMock()
    client.get_margin_account.return_value = {
        "userAssets": [{"asset": "USDT", "free": "100", "borrowed": "0", "interest": "0"}],
    }
    client.transfer.side_effect = Exception("all failed")
    rules = _fund_rules(transfer_order="futures,spot")

    result = await ensure_margin_balance(client, rules, Decimal("500"))

    assert result is False
