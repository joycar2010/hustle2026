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
            self.internal = []

        async def transfer(self, transfer_type, asset, amount):
            self.internal.append((transfer_type, asset, amount))

        async def universal_transfer(self, **kwargs):
            self.transfers.append(kwargs)

    client = Client()
    snapshots = iter([
        {"futures": Decimal("600"), "spot": Decimal("900")},
        {"futures": Decimal("1500"), "spot": Decimal("0")},
    ])
    async def read(_client, _sources):
        return next(snapshots)
    monkeypatch.setattr(margin_balancer, "_master_source_usdt", read)
    moved = asyncio.run(
        margin_balancer._xfer_master_to_sub(
            client, Decimal("700"), ["futures", "spot"], Decimal("500"), "sub@example.com"
        )
    )
    assert moved == Decimal("700")
    assert client.internal == [
        ("MAIN_UMFUTURE", "USDT", Decimal("900")),
        ("UMFUTURE_MAIN", "USDT", Decimal("700")),
    ]
    assert client.transfers[0]["from_account_type"] == "SPOT"
    assert client.transfers[0]["amount"] == Decimal("700")


def test_futures_source_uses_supported_two_leg_transfer(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        async def transfer(self, transfer_type, asset, amount):
            self.calls.append(("internal", transfer_type, asset, amount))

        async def universal_transfer(self, **kwargs):
            self.calls.append(("universal", kwargs))

    client = Client()
    monkeypatch.setattr(
        margin_balancer,
        "_master_source_usdt",
        lambda _client, _sources: asyncio.sleep(0, result={"futures": Decimal("900"), "spot": Decimal("0")}),
    )
    moved = asyncio.run(
        margin_balancer._xfer_master_to_sub(
            client, Decimal("100"), ["futures"], Decimal("500"), "sub@example.com"
        )
    )
    assert moved == Decimal("100")
    assert client.calls == [
        ("internal", "UMFUTURE_MAIN", "USDT", Decimal("100")),
        ("universal", {
            "asset": "USDT", "amount": Decimal("100"),
            "from_account_type": "SPOT", "to_account_type": "MARGIN",
            "from_email": None, "to_email": "sub@example.com",
        }),
    ]


def test_master_reserve_is_a_gate_when_futures_are_below_floor(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        async def transfer(self, *args):
            self.calls.append(("internal", *args))

        async def universal_transfer(self, **kwargs):
            self.calls.append(("universal", kwargs))

    client = Client()
    monkeypatch.setattr(
        margin_balancer,
        "_master_source_usdt",
        lambda _client, _sources: asyncio.sleep(
            0, result={"futures": Decimal("499.99"), "spot": Decimal("0")}
        ),
    )
    moved = asyncio.run(
        margin_balancer._xfer_master_to_sub(
            client, Decimal("100"), ["futures", "spot"], Decimal("500"), "sub@example.com"
        )
    )
    assert moved == Decimal("0")
    assert client.calls == []


def test_spot_is_swept_before_child_topup(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        async def transfer(self, *args):
            self.calls.append(("internal", *args))

        async def universal_transfer(self, **kwargs):
            self.calls.append(("universal", kwargs))

    client = Client()
    snapshots = iter([
        {"futures": Decimal("500"), "spot": Decimal("300")},
        {"futures": Decimal("800"), "spot": Decimal("0")},
    ])
    async def read(_client, _sources):
        return next(snapshots)
    monkeypatch.setattr(margin_balancer, "_master_source_usdt", read)
    moved = asyncio.run(
        margin_balancer._xfer_master_to_sub(
            client, Decimal("100"), ["futures", "spot"], Decimal("500"), "sub@example.com"
        )
    )
    assert moved == Decimal("100")
    assert client.calls[0] == ("internal", "MAIN_UMFUTURE", "USDT", Decimal("300"))
    assert client.calls[1][0] == "internal"
    assert client.calls[1][1:] == ("UMFUTURE_MAIN", "USDT", Decimal("100"))
