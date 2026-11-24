from __future__ import annotations

from bot.orders import (
    OrderResult,
    _post_submit_error,
    get_collateral_balance_allowance,
    place_buy_market_fok,
    reconcile_recent_trade,
)


class FakeClient:
    def __init__(self, trades):
        self.trades = trades

    def get_trades(self, params, only_first_page=False):
        self.params = params
        self.only_first_page = only_first_page
        return self.trades


class FakeBalanceClient:
    def __init__(self, response):
        self.response = response

    def get_balance_allowance(self, params):
        self.params = params
        return self.response


class FakeBuyClient:
    def create_market_order(self, args, options):
        self.args = args
        self.options = options
        return {"signed": True}

    def post_order(self, signed, order_type):
        return {"status": "matched", "makingAmount": "12.34"}


def test_post_timeout_is_ambiguous_pending_reconcile():
    result = _post_submit_error(Exception("PolyApiException[status_code=None, error_message=Request exception!]"))

    assert isinstance(result, OrderResult)
    assert result.submitted is True
    assert result.ambiguous is True
    assert result.status == "timeout_pending_reconcile"
    assert result.filled_size == 0.0


def test_reconcile_recent_trade_matches_market_asset_side_and_time():
    client = FakeClient(
        [
            {
                "id": "trade-1",
                "taker_order_id": "order-1",
                "market": "0xmarket",
                "asset_id": "token-1",
                "side": "BUY",
                "status": "CONFIRMED",
                "match_time": "1002",
                "size": "1.23",
                "price": "0.42",
            }
        ]
    )

    result = reconcile_recent_trade(
        client,
        condition_id="0xmarket",
        token_id="token-1",
        side="BUY",
        submitted_at=1000.0,
        min_size=1.0,
    )

    assert result is not None
    assert result.status == "matched"
    assert result.order_id == "order-1"
    assert result.filled_size == 1.23
    assert result.avg_price == 0.42
    assert result.filled_amount == 0.5166


def test_reconcile_recent_trade_aggregates_exact_order_fills():
    client = FakeClient(
        [
            {
                "id": "trade-1",
                "taker_order_id": "order-1",
                "market": "0xmarket",
                "asset_id": "token-1",
                "side": "SELL",
                "status": "CONFIRMED",
                "match_time": "1002",
                "size": "10",
                "price": "0.57",
            },
            {
                "id": "trade-2",
                "taker_order_id": "order-1",
                "market": "0xmarket",
                "asset_id": "token-1",
                "side": "SELL",
                "status": "CONFIRMED",
                "match_time": "1003",
                "size": "11.39",
                "price": "0.56",
            },
            {
                "id": "trade-3",
                "taker_order_id": "other-order",
                "market": "0xmarket",
                "asset_id": "token-1",
                "side": "SELL",
                "status": "CONFIRMED",
                "match_time": "1003",
                "size": "99",
                "price": "0.01",
            },
        ]
    )

    result = reconcile_recent_trade(
        client,
        condition_id="0xmarket",
        token_id="token-1",
        side="SELL",
        submitted_at=1000.0,
        order_id="order-1",
    )

    assert result is not None
    assert result.status == "matched"
    assert result.order_id == "order-1"
    assert result.filled_size == 21.39
    assert result.filled_amount == 12.0784
    assert round(result.avg_price, 6) == round(12.0784 / 21.39, 6)


def test_reconcile_recent_trade_ignores_old_trade():
    client = FakeClient(
        [
            {
                "id": "trade-1",
                "market": "0xmarket",
                "asset_id": "token-1",
                "side": "BUY",
                "status": "CONFIRMED",
                "match_time": "900",
                "size": "1.23",
            }
        ]
    )

    result = reconcile_recent_trade(
        client,
        condition_id="0xmarket",
        token_id="token-1",
        side="BUY",
        submitted_at=1000.0,
        min_size=1.0,
    )

    assert result is None


def test_collateral_balance_allowance_parses_relevant_v2_exchange():
    client = FakeBalanceClient(
        {
            "balance": "33616334",
            "allowances": {
                "0xE111180000d2663C0091e4f400237545B87B996B": str(2**256 - 1),
                "0xe2222d279d744050d28e00520010520000310F59": "0",
            },
        }
    )

    result = get_collateral_balance_allowance(
        client,
        chain_id=137,
        neg_risk=False,
    )

    assert result.balance_usd == 33.616334
    assert result.allowance_usd > 1e20
    assert result.spendable_usd(0.10) == 33.516334


def test_buy_market_fok_passes_balance_to_sdk_fee_adjustment():
    client = FakeBuyClient()

    result = place_buy_market_fok(
        client,
        token_id="token-1",
        price=0.98,
        amount_usd=33.25,
        tick_size=0.01,
        neg_risk=False,
        user_usdc_balance=33.516334,
    )

    assert result.status == "matched"
    assert result.filled_size == 12.34
    assert client.args.user_usdc_balance == 33.516334
