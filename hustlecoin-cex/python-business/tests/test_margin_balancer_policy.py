from decimal import Decimal
from types import SimpleNamespace
import asyncio

from engine.fund.margin_balancer import _effective_balance_policy
import engine.fund.margin_balancer as margin_balancer


def test_sub_account_values_override_common_rules():
    policy = _effective_balance_policy(
        {"chunk": "120", "risk_threshold": "2.4", "floor": "30"},
        SimpleNamespace(single_transfer_amount=500, risk_value_threshold=1.5),
    )
    assert policy == (Decimal("120"), Decimal("2.4"), Decimal("30"))


def test_blank_sub_account_values_inherit_common_rules():
    policy = _effective_balance_policy(
        {"chunk": None, "risk_threshold": None, "floor": None},
        SimpleNamespace(single_transfer_amount=300, risk_value_threshold=1.8),
    )
    assert policy == (Decimal("300"), Decimal("1.8"), Decimal("0"))


def test_missing_common_rules_use_system_defaults():
    policy = _effective_balance_policy(
        {"chunk": None, "risk_threshold": None, "floor": None},
        SimpleNamespace(single_transfer_amount=None, risk_value_threshold=None),
    )
    assert policy == (Decimal("500"), Decimal("1.5"), Decimal("0"))


def test_master_transfer_preserves_futures_reserve(monkeypatch):
    class Client:
        def __init__(self):
            self.transfers = []

        async def universal_transfer(self, **kwargs):
            self.transfers.append(kwargs)

    client = Client()
    monkeypatch.setattr(
        margin_balancer,
        "_master_source_usdt",
        lambda _client, _sources: asyncio.sleep(0, result={"futures": Decimal("600"), "spot": Decimal("900")}),
    )
    moved = asyncio.run(
        margin_balancer._xfer_master_to_sub(
            client, Decimal("700"), ["futures", "spot"], Decimal("500"), "sub@example.com"
        )
    )
    assert moved == Decimal("700")
    assert client.transfers[0]["from_account_type"] == "USDT_FUTURE"
    assert client.transfers[0]["amount"] == Decimal("100")
    assert client.transfers[1]["from_account_type"] == "SPOT"
    assert client.transfers[1]["amount"] == Decimal("600")
