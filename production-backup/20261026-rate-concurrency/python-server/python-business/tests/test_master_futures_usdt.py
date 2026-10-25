import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api import master_account


def snapshot(**overrides):
    return {"totalWalletBalance": "686", "availableBalance": "686",
            "assets": [{"asset": "USDT", "walletBalance": "580.62644022",
                        "availableBalance": "686.15608250",
                        "maxWithdrawAmount": "580.62644022", "initialMargin": "0",
                        **overrides}, {"asset": "BNB", "walletBalance": "1"}]}


def test_collateral_valuation_never_becomes_usdt_wallet_or_withdrawable():
    fields = master_account._futures_usdt_fields(snapshot())
    assert fields["futures_usdt_wallet"] == "580.62644022"
    assert fields["futures_usdt_transferable"] == "580.62644022"
    assert fields["futures_usdt_initial_margin"] == "0"
    occupied = master_account._futures_usdt_fields(snapshot(maxWithdrawAmount="480", initialMargin="100"))
    assert occupied["futures_usdt_transferable"] == "480"
    assert occupied["futures_usdt_initial_margin"] == "100"


def test_zero_withdrawable_is_not_replaced_by_wallet_and_missing_is_unknown():
    assert master_account._futures_usdt_fields(snapshot(maxWithdrawAmount="0"))["futures_usdt_transferable"] == "0"
    assert master_account._futures_usdt_fields(snapshot(walletBalance="-5"))["futures_usdt_transferable"] == "0"
    for value in [None, "bad", "NaN", "Infinity"]:
        assert master_account._futures_usdt_fields(snapshot(maxWithdrawAmount=value))["futures_usdt_transferable"] is None
    fields = master_account._futures_usdt_fields({"availableBalance": "686", "assets": []})
    assert fields["futures_usdt_wallet"] is None
    assert fields["futures_usdt_transferable"] is None


def test_master_balance_endpoint_and_account_metadata(monkeypatch):
    account = SimpleNamespace(id=1, account_name="test", api_key="fake-key",
                              api_secret="fake-secret", is_verified=True, created_at=None)
    # A previous patch placed futures balance code in this metadata function.
    assert master_account._to_response(account)["account_name"] == "test"
    class DB:
        def query(self, *args): return self
        def filter(self, *args): return self
        def first(self): return account
    class Client:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get_spot_account(self): return {"balances": []}
        async def get_margin_account(self): return {"userAssets": []}
        async def get_futures_account(self): return snapshot()
        async def get_funding_account(self): return []
        async def get_simple_earn_account(self): return {}
    monkeypatch.setattr(master_account, "get_current_user_id", lambda request: 2)
    monkeypatch.setattr("engine.trading.binance_trading.BinanceTradingClient", Client)
    result = asyncio.run(master_account.get_master_balance(None, DB()))
    assert Decimal(result["futures_usdt_wallet"]) == Decimal("580.62644022")
    assert result["futures_usdt_transferable"] == result["futures_usdt_wallet"]
    assert result["futures_total_balance"] == "686"  # Existing valuation API remains explicit.
