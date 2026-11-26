"""Offline regressions for lost Maker inventory and cancellation races."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from bot import orders
except ModuleNotFoundError as exc:
    if not (exc.name.startswith("py_clob_client_v2") or exc.name == "dotenv"):
        raise
    # Local development has no SDK/credentials. The test doubles never sign,
    # connect, or submit transactions; only the SDK's argument containers
    # need to exist to exercise the production state machine.
    class Args:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    sdk = types.ModuleType("py_clob_client_v2")
    client_module = types.ModuleType("py_clob_client_v2.client")
    client_module.ClobClient = Args
    type_module = types.ModuleType("py_clob_client_v2.clob_types")
    for name in ("ApiCreds", "BalanceAllowanceParams", "MarketOrderArgsV2", "TradeParams",
                 "OrderArgsV2", "PartialCreateOrderOptions"):
        setattr(type_module, name, Args)
    type_module.AssetType = types.SimpleNamespace(COLLATERAL="COLLATERAL")
    type_module.OrderType = types.SimpleNamespace(FOK="FOK", FAK="FAK", GTC="GTC", GTD="GTD")
    cfg_module = types.ModuleType("py_clob_client_v2.config")
    cfg_module.get_contract_config = lambda _: None
    constants = types.ModuleType("py_clob_client_v2.order_builder.constants")
    constants.BUY, constants.SELL = "BUY", "SELL"
    bot_config = types.ModuleType("bot.config")
    bot_config.Config = Args
    sys.modules.update({"py_clob_client_v2": sdk, "py_clob_client_v2.client": client_module,
                        "py_clob_client_v2.clob_types": type_module,
                        "py_clob_client_v2.config": cfg_module,
                        "py_clob_client_v2.order_builder": types.ModuleType("py_clob_client_v2.order_builder"),
                        "py_clob_client_v2.order_builder.constants": constants,
                        "bot.config": bot_config})
    orders = importlib.import_module("bot.orders")

from bot.order_evidence import cancellation_confirmed, iter_account_trade_fills, order_snapshot, own_trade_legs

NOW = 1794319990.0
OWN, OTHER = "0xown-order", "0xother-order"
TOKEN, MARKET = "token-up", "0xmarket"
WALLET, OUTSIDER = "0xown-wallet", "0xother-wallet"


def maker_trade(size=5.37, *, side="BUY", order_id=OWN, price=.86, trade_id="trade-a", maker_side=True):
    maker = {"order_id": order_id, "asset_id": TOKEN, "maker_address": WALLET,
             "owner": "api-owner", "matched_amount": str(size), "price": str(price)}
    if maker_side:
        maker["side"] = side
    return {"id": trade_id, "market": MARKET, "asset_id": TOKEN,
            "side": "SELL" if side == "BUY" else "BUY", "size": "40.5", "price": str(price),
            "status": "CONFIRMED", "match_time": str(NOW + 1), "trader_side": "MAKER",
            "taker_order_id": OTHER, "maker_orders": [maker,
                {"order_id": OTHER, "asset_id": TOKEN, "maker_address": OUTSIDER,
                 "side": side, "matched_amount": "35.13", "price": str(price)}]}


def snapshot(filled=0., status="LIVE", size=5.37):
    return {"id": OWN, "asset_id": TOKEN, "side": "BUY", "price": ".86",
            "original_size": str(size), "size_matched": str(filled), "status": status}


class FakeClient:
    def __init__(self, trades=None, states=None, cancel=None, cancel_error=None, trades_error=None):
        self.trades = trades if trades is not None else [[]]
        self.states = states if states is not None else [snapshot()]
        self.cancel = cancel if cancel is not None else {"canceled": [OWN], "not_canceled": {}}
        self.cancel_error, self.trades_error = cancel_error, trades_error
        self.trade_calls, self.order_calls, self.cancel_calls, self.submissions = 0, 0, 0, []
        self.creds = types.SimpleNamespace(api_key="api-owner")
        self.builder = types.SimpleNamespace(funder=WALLET)

    def get_address(self):
        return "0xsigner"

    def get_trades(self, params, only_first_page=True):
        self.trade_calls += 1
        if self.trades_error:
            raise self.trades_error
        return copy.deepcopy(self.trades[min(self.trade_calls - 1, len(self.trades) - 1)])

    def get_order(self, order_id):
        self.order_calls += 1
        value = self.states[min(self.order_calls - 1, len(self.states) - 1)]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def create_order(self, args, opts):
        return args

    def post_order(self, signed, **kwargs):
        self.submissions.append(signed)
        return {"orderID": OWN, "status": "live", "success": True}

    def cancel_orders(self, ids):
        self.cancel_calls += 1
        if self.cancel_error:
            raise self.cancel_error
        return copy.deepcopy(self.cancel)


class TradeLegEvidenceTests(unittest.TestCase):
    def evidence(self, values, **kwargs):
        options = dict(condition_id=MARKET, token_id=TOKEN, side="BUY", submitted_at=NOW,
                       order_id=OWN, wallet_addresses=[WALLET])
        options.update(kwargs)
        return own_trade_legs(values, **options)

    def test_nested_maker_buy_uses_own_size_not_taker_size_or_side(self):
        values = self.evidence([maker_trade()])
        self.assertEqual(len(values), 1)
        self.assertAlmostEqual(values[0]["size"], 5.37)
        self.assertAlmostEqual(values[0]["amount"], 4.6182)
        self.assertEqual(values[0]["side"], "BUY")

    def test_maker_sell_has_opposite_top_level_side(self):
        values = self.evidence([maker_trade(6.16, side="SELL")], side="SELL")
        self.assertEqual(values[0]["side"], "SELL")
        self.assertEqual(values[0]["size"], 6.16)

    def test_known_order_identifies_side_when_nested_api_omits_it(self):
        values = self.evidence([maker_trade(maker_side=False)])
        self.assertEqual(values[0]["side"], "BUY")

    def test_duplicate_confirmed_and_mined_trade_is_counted_once(self):
        first = maker_trade()
        second = copy.deepcopy(first)
        second["status"] = "MINED"
        self.assertEqual(len(self.evidence([first, second])), 1)

    def test_different_trade_ids_for_one_order_are_aggregated(self):
        client = FakeClient(trades=[[maker_trade(2, trade_id="a"), maker_trade(3.37, trade_id="b")]])
        result = orders.reconcile_recent_trade(client, condition_id=MARKET, token_id=TOKEN,
            side="BUY", submitted_at=NOW, order_id=OWN)
        self.assertAlmostEqual(result.filled_size, 5.37)
        self.assertEqual(result.order_id, OWN)

    def test_only_authenticated_taker_role_can_match_without_order_id(self):
        trade = maker_trade()
        trade.update(trader_side="TAKER", side="BUY", size="2.5", taker_order_id=OWN)
        trade["maker_orders"] = []
        values = self.evidence([trade], order_id=None)
        self.assertEqual(values[0]["size"], 2.5)
        trade["trader_side"] = "MAKER"
        self.assertEqual(self.evidence([trade], order_id=None), [])

    def test_unknown_order_maker_requires_own_wallet_or_owner(self):
        trade = maker_trade()
        values = self.evidence([trade], order_id=None)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["order_id"], OWN)
        self.assertEqual(self.evidence([trade], order_id=None, wallet_addresses=[]), [])

    def test_account_iterator_returns_both_buy_and_sell_with_trade_identity(self):
        trades = [maker_trade(2, side="BUY", trade_id="buy"),
                  maker_trade(1, side="SELL", trade_id="sell")]
        values = iter_account_trade_fills(trades, owner_addresses=[WALLET])
        self.assertEqual({fill["side"] for fill in values}, {"BUY", "SELL"})
        self.assertEqual({fill["trade_id"] for fill in values}, {"buy", "sell"})
        self.assertTrue(all(fill["condition_id"] == MARKET for fill in values))

    def test_complementary_token_maker_has_same_direction_as_taker(self):
        trade = maker_trade(maker_side=False)
        trade["asset_id"] = "token-down"
        values = iter_account_trade_fills([trade], owner_addresses=[WALLET])
        self.assertEqual(values[0]["side"], "SELL")
        self.assertEqual(values[0]["token_id"], TOKEN)

    def test_reject_failed_pending_wrong_token_and_stale_records(self):
        trades = []
        for key, value in (("status", "FAILED"), ("status", "RETRYING"),
                           ("market", "other"), ("match_time", str(NOW - 10))):
            trade = maker_trade()
            trade[key] = value
            trades.append(trade)
        trade = maker_trade()
        trade["maker_orders"][0]["asset_id"] = "other"
        trades.append(trade)
        self.assertEqual(self.evidence(trades), [])

    def test_multiple_own_orders_after_submit_timeout_remain_ambiguous(self):
        client = FakeClient(trades=[[maker_trade(2, trade_id="a"), maker_trade(3, order_id="another", trade_id="b")]])
        result = orders.reconcile_recent_trade(client, condition_id=MARKET, token_id=TOKEN,
            side="BUY", submitted_at=NOW)
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.fallback_safe)


class MakerStateMachineTests(unittest.TestCase):
    def place(self, client):
        with patch.object(orders.time, "sleep"), patch.object(orders.time, "time", return_value=NOW):
            return orders.place_buy_maker(client, token_id=TOKEN, price=.86, size=5.37,
                tick_size=.01, neg_risk=False, condition_id=MARKET, ttl_sec=.1, best_ask=.87)

    def test_live_partial_is_cancelled_before_returning_inventory(self):
        client = FakeClient(trades=[[maker_trade(2)], [maker_trade(2)]],
                            states=[snapshot(2), snapshot(2, "CANCELED")])
        result = self.place(client)
        self.assertEqual(client.cancel_calls, 1)
        self.assertTrue(result.terminal)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.status, "maker_partial_cancelled")
        self.assertAlmostEqual(result.filled_size, 2)
        self.assertAlmostEqual(result.remaining_size, 3.37)
        self.assertTrue(result.fallback_safe)

    def test_full_fill_never_falls_back_or_leaves_order_open(self):
        client = FakeClient(trades=[[maker_trade()]], states=[snapshot(5.37, "MATCHED")])
        result = self.place(client)
        self.assertEqual(client.cancel_calls, 0)
        self.assertTrue(result.terminal)
        self.assertFalse(result.fallback_safe)
        self.assertEqual(result.remaining_size, 0)
        self.assertAlmostEqual(result.filled_size, 5.37)

    def test_confirmed_zero_fill_cancellation_can_fallback(self):
        client = FakeClient(states=[snapshot(), snapshot(0, "CANCELED")])
        result = self.place(client)
        self.assertEqual(result.status, "maker_timeout_cancelled")
        self.assertTrue(result.fallback_safe)
        self.assertEqual(result.remaining_size, 5.37)
        self.assertEqual(result.filled_size, 0)

    def test_http_success_not_canceled_is_not_safe(self):
        client = FakeClient(cancel={"canceled": [], "not_canceled": {OWN: "already matched"}})
        result = self.place(client)
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.fallback_safe)
        self.assertIsNone(result.remaining_size)

    def test_cancel_success_without_terminal_snapshot_is_not_safe(self):
        result = self.place(FakeClient(states=[TimeoutError(), TimeoutError()]))
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.fallback_safe)

    def test_cancel_race_fill_is_reconciled_and_not_added_to_snapshot_twice(self):
        client = FakeClient(trades=[[], [maker_trade(2)]],
                            states=[snapshot(), snapshot(2, "CANCELED")])
        result = self.place(client)
        self.assertEqual(result.filled_size, 2)
        self.assertAlmostEqual(result.filled_amount, 1.72)
        self.assertAlmostEqual(result.remaining_size, 3.37)

    def test_cancel_exception_after_full_match_still_recognizes_fill(self):
        client = FakeClient(trades=[[], [maker_trade()]],
                            states=[snapshot(), snapshot(5.37, "MATCHED")], cancel_error=TimeoutError())
        result = self.place(client)
        self.assertTrue(result.terminal)
        self.assertEqual(result.filled_size, 5.37)
        self.assertFalse(result.fallback_safe)

    def test_trade_index_outage_preserves_snapshot_inventory(self):
        client = FakeClient(states=[snapshot(2), snapshot(2, "CANCELED")], trades_error=TimeoutError())
        result = self.place(client)
        self.assertEqual(result.filled_size, 2)
        self.assertTrue(result.terminal)
        self.assertEqual(result.raw["filled_amount_source"], "order_limit_pending_trade_index")

    def test_stale_cancel_snapshot_cannot_erase_trade_evidence(self):
        client = FakeClient(trades=[[maker_trade(2)], [maker_trade(2)]],
                            states=[snapshot(), snapshot(0, "CANCELED")])
        result = self.place(client)
        self.assertEqual(result.filled_size, 2)
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.fallback_safe)

    def test_regressed_evidence_after_cancel_keeps_previous_position(self):
        client = FakeClient(trades=[[maker_trade(2)], []],
                            states=[snapshot(2), snapshot(0, "CANCELED")])
        result = self.place(client)
        self.assertEqual(result.filled_size, 2)
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.fallback_safe)

    def test_post_only_precheck_is_explicitly_safe_and_never_submits(self):
        client = FakeClient()
        result = orders.place_buy_maker(client, token_id=TOKEN, price=.86, size=5.37,
            tick_size=.01, neg_risk=False, condition_id=MARKET, best_ask=.85)
        self.assertEqual(client.submissions, [])
        self.assertTrue(result.fallback_safe)
        self.assertEqual(result.remaining_size, 5.37)

    def test_invalid_order_identity_or_missing_cumulative_size_never_proves_zero(self):
        raw = snapshot(0, "CANCELED")
        del raw["size_matched"]
        self.assertIsNone(order_snapshot(raw, order_id=OWN, token_id=TOKEN, side="BUY", requested_size=5.37))
        raw = snapshot(0, "CANCELED")
        raw["id"] = OTHER
        self.assertIsNone(order_snapshot(raw, order_id=OWN, token_id=TOKEN, side="BUY", requested_size=5.37))

    def test_cancellation_response_requires_own_id_and_no_denial(self):
        self.assertFalse(cancellation_confirmed({"success": True}, OWN))
        self.assertFalse(cancellation_confirmed({"canceled": [OTHER]}, OWN))
        self.assertFalse(cancellation_confirmed({"canceled": [OWN], "not_canceled": {OWN: "race"}}, OWN))
        self.assertTrue(cancellation_confirmed({"canceled": [OWN], "not_canceled": {}}, OWN))


class ActualAuthenticatedFixtureTests(unittest.TestCase):
    """Actual CLOB response, with every API owner identifier hashed on-server."""
    @classmethod
    def setUpClass(cls):
        base = Path(__file__).resolve().parent
        cls.fixture = json.loads((base / 'fixture_authenticated_fills_20261110.json').read_text())
        cls.activity = json.loads((base / 'fixture_authenticated_activity_20261110.json').read_text())
        cls.fills = iter_account_trade_fills(cls.fixture['records'],
            owner_addresses=[cls.fixture['wallet']], api_owner=cls.fixture['api_owner'])

    def test_all_actual_own_legs_match_public_activity_quantity_direction_and_role(self):
        self.assertEqual(len(self.fills), 6)
        by_tx = {fill['trade']['transaction_hash']: fill for fill in self.fills}
        self.assertEqual(len(by_tx), len(self.activity))
        for activity in self.activity:
            with self.subTest(tx=activity['transaction_hash']):
                fill = by_tx[activity['transaction_hash']]
                self.assertEqual(fill['condition_id'], activity['condition_id'])
                self.assertEqual(fill['token_id'], activity['token_id'])
                self.assertEqual(fill['side'], activity['side'])
                self.assertEqual(fill['liquidity_role'], activity['liquidity_role'])
                self.assertAlmostEqual(fill['size'], activity['size'], places=6)
                self.assertAlmostEqual(fill['price'], activity['price'], places=6)

    def test_actual_lost_maker_buy_is_537_not_aggregate_42709(self):
        market = self.fixture['markets'][0]
        fills = [fill for fill in self.fills if fill['condition_id'] == market]
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]['side'], 'BUY')
        self.assertEqual(fills[0]['size'], 5.37)
        self.assertEqual(fills[0]['price'], .86)
        self.assertEqual(fills[0]['trade']['size'], '427.09')
        self.assertEqual(fills[0]['trade']['side'], 'SELL')

    def test_actual_2228_two_buys_and_maker_sell_leave_538(self):
        market = self.fixture['markets'][1]
        fills = [fill for fill in self.fills if fill['condition_id'] == market]
        self.assertEqual([(fill['side'], fill['size'], fill['price'], fill['liquidity_role'])
                          for fill in fills],
                         [('BUY', 5.38, .85, 'MAKER'), ('BUY', 6.16, .75, 'TAKER'),
                          ('SELL', 6.16, .82, 'MAKER')])
        net_size = sum(fill['size'] * (1 if fill['side'] == 'BUY' else -1) for fill in fills)
        self.assertAlmostEqual(net_size, 5.38)

    def test_actual_taker_buy_sell_stay_own_direction(self):
        market = self.fixture['markets'][2]
        fills = [fill for fill in self.fills if fill['condition_id'] == market]
        self.assertEqual([(fill['side'], fill['size'], fill['price']) for fill in fills],
                         [('BUY', 5.691357, .81), ('SELL', 5.69, .91)])


if __name__ == "__main__":
    unittest.main()
