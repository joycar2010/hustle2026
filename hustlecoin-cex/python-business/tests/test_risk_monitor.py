from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from engine.fund.risk_monitor import check_margin_risk
from engine.config_loader import FundRulesSnapshot


@pytest.fixture
def rules():
    return FundRulesSnapshot(risk_value_threshold=Decimal("1.5"))


@pytest.fixture
def notifier():
    n = AsyncMock()
    n.notify_risk = AsyncMock()
    return n


def _client_with_margin_level(level: str):
    c = AsyncMock()
    c.get_margin_account.return_value = {"marginLevel": level}
    return c


@pytest.mark.asyncio
async def test_critical_level_returns_false(rules, notifier):
    client = _client_with_margin_level("1.2")
    result = await check_margin_risk(client, rules, notifier, "test")
    assert result is False
    notifier.notify_risk.assert_called_once()


@pytest.mark.asyncio
async def test_warning_level_returns_false(rules, notifier):
    client = _client_with_margin_level("1.4")
    result = await check_margin_risk(client, rules, notifier, "test")
    assert result is False
    notifier.notify_risk.assert_called_once()


@pytest.mark.asyncio
async def test_safe_level_returns_true(rules, notifier):
    client = _client_with_margin_level("2.5")
    result = await check_margin_risk(client, rules, notifier, "test")
    assert result is True
    notifier.notify_risk.assert_not_called()


@pytest.mark.asyncio
async def test_api_error_returns_true(rules, notifier):
    client = AsyncMock()
    client.get_margin_account.side_effect = Exception("API timeout")
    result = await check_margin_risk(client, rules, notifier, "test")
    assert result is True
