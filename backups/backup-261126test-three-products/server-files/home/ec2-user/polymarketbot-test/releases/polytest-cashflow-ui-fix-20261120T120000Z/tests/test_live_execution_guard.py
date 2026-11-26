"""Offline live-inventory/entry-intent regressions; no real orders or RPC."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from bot.live_execution import LiveExecutionGuard
    from bot.orders import OrderResult
    from bot.strategy import StrategyState, TrackedPosition
except ModuleNotFoundError as exc:
    raise unittest.SkipTest('Run this module in the deployed SDK environment: ' + str(exc.name))

HERE = Path(__file__).resolve().parent
FIXTURE = json.loads((HERE / 'fixture_authenticated_fills_20261110.json').read_text())
WALLET, OWNER = FIXTURE['wallet'], FIXTURE['api_owner']


def market_for(index):
    condition = FIXTURE['markets'][index]
    rows = [row for row in FIXTURE['records'] if row['market'] == condition]
    own = [leg for row in rows for leg in row['maker_orders']
           if str(leg.get('maker_address', '')).lower() == WALLET.lower()]
    token = own[0]['asset_id'] if own else rows[0]['asset_id']
    opposite = next((leg['asset_id'] for row in rows for leg in row['maker_orders']
                     if leg['asset_id'] != token), 'opposite-token')
    is_down = index == 0
    return types.SimpleNamespace(condition_id=condition, market_slug='btc-updown-5m-fixture',
        up_token=opposite if is_down else token, down_token=token if is_down else opposite,
        start_ts=min(float(row['match_time']) for row in rows) - 180)


def own_trade(current, *, side='BUY', size=5.37, status='CONFIRMED', trade_id='own-buy', order_id='own-buy-order'):
    return {'id': trade_id, 'market': current.condition_id, 'asset_id': current.up_token,
            'side': side, 'size': str(size), 'price': '.85', 'status': status,
            'match_time': str(current.start_ts + 10), 'trader_side': 'TAKER',
            'taker_order_id': order_id, 'maker_orders': []}


def position(current, size=5.37):
    return TrackedPosition(market_slug=current.market_slug, condition_id=current.condition_id,
        token_id=current.up_token, side='UP', entry_size=size, remaining_size=size,
        entry_price=.85, entry_notional=size * .85, entry_order_id='own-buy-order',
        entry_ts=current.start_ts + 10)


class Client:
    def __init__(self, current, records=(), balance=0.):
        self.records = list(records)
        self.orders = []
        self.balances = {current.up_token: balance, current.down_token: 0.}
        self.order_states = {}
        self.cancelled = []

    def get_trades(self, params, only_first_page=False):
        if isinstance(self.records, Exception):
            raise self.records
        return copy.deepcopy(self.records)

    def get_open_orders(self, params, only_first_page=False):
        return copy.deepcopy(self.orders)

    def get_balance_allowance(self, params):
        amount = self.balances.get(str(params.token_id))
        return {} if amount is None else {'balance': str(round(amount * 1_000_000))}

    def get_order(self, order_id):
        return copy.deepcopy(self.order_states.get(order_id))

    def cancel_orders(self, ids):
        self.cancelled.extend(ids)
        return {'canceled': list(ids), 'not_canceled': {}}


class LiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.current = market_for(1)
        self.cfg = types.SimpleNamespace(deposit_wallet_address=WALLET, funder_address=WALLET,
            wallet_address='0xsigner', signature_type=0, api_key=OWNER, max_buys_per_market=1)

    def guard(self, client):
        return LiveExecutionGuard(self.cfg, client, directory=self.temp.name)

    def claim(self, guard, client):
        guard.sync(self.current, StrategyState())
        claimed, reason = guard.claim_entry(self.current, self.current.up_token, 'UP', 5.37, .85)
        self.assertTrue(claimed, reason)

    def test_real_2228_fills_rebuild_remaining_538_instead_of_reselling_616(self):
        current = self.current
        records = [row for row in FIXTURE['records'] if row['market'] == current.condition_id]
        client = Client(current, records, 5.38)
        guard, state = self.guard(client), StrategyState()
        snapshot = guard.sync(current, state)
        item = snapshot['positions'][current.up_token]
        self.assertAlmostEqual(item['size'], 5.38)
        self.assertAlmostEqual(guard.available_to_sell(current, current.up_token), 5.38)
        self.assertAlmostEqual(next(iter(state.local_positions.values())).remaining_size, 5.38)
        self.assertEqual(snapshot['buy_count'], 2)
        self.assertIsNotNone(guard.entry_reason(current))

    def test_lost_local_maker_buy_is_recovered_from_real_account_fills(self):
        current = market_for(0)
        records = [row for row in FIXTURE['records'] if row['market'] == current.condition_id]
        client = Client(current, records)
        client.balances[current.down_token] = 5.37
        state, guard = StrategyState(), self.guard(client)
        guard.sync(current, state)
        restored = state.local_positions[(current.condition_id, current.down_token, 'DOWN')]
        self.assertEqual(restored.remaining_size, 5.37)
        self.assertEqual(restored.entry_price, .86)

    def test_matched_buy_is_kept_when_conditional_balance_is_still_zero(self):
        client = Client(self.current, [own_trade(self.current, status='MATCHED')])
        state, guard = StrategyState(), self.guard(client)
        result = guard.sync(self.current, state)
        self.assertEqual(result['positions'][self.current.up_token]['size'], 5.37)
        self.assertTrue(result['positions'][self.current.up_token]['settlement_pending'])
        self.assertEqual(guard.available_to_sell(self.current, self.current.up_token), 0)

    def test_confirmed_buy_is_also_kept_when_balance_index_lags(self):
        client = Client(self.current, [own_trade(self.current)])
        state, guard = StrategyState(), self.guard(client)
        result = guard.sync(self.current, state)
        self.assertTrue(result['positions'][self.current.up_token]['balance_mismatch'])
        self.assertEqual(next(iter(state.local_positions.values())).remaining_size, 5.37)

    def test_local_acknowledged_fill_is_not_erased_by_both_empty_indexes(self):
        client, state = Client(self.current), StrategyState()
        state.local_positions[(self.current.condition_id, self.current.up_token, 'UP')] = position(self.current)
        guard = self.guard(client)
        result = guard.sync(self.current, state)
        self.assertTrue(result['positions'][self.current.up_token]['local_pending'])
        self.assertEqual(next(iter(state.local_positions.values())).remaining_size, 5.37)
        self.assertIn('indexes', guard.entry_reason(self.current))

    def test_matched_sell_blocks_second_sell_while_balance_decrement_lags(self):
        buy = own_trade(self.current)
        sell = own_trade(self.current, side='SELL', status='MATCHED', trade_id='sell', order_id='sell-order')
        sell['match_time'] = str(float(buy['match_time']) + 1)
        client = Client(self.current, [buy, sell], 5.37)
        guard, state = self.guard(client), StrategyState()
        state.local_positions[(self.current.condition_id, self.current.up_token, 'UP')] = position(self.current)
        guard.sync(self.current, state)
        self.assertEqual(guard.available_to_sell(self.current, self.current.up_token), 0)
        self.assertEqual(state.local_positions, {})

    def test_fully_sold_inventory_clears_local_ghost(self):
        buy = own_trade(self.current)
        sell = own_trade(self.current, side='SELL', trade_id='sell', order_id='sell-order')
        sell['match_time'] = str(float(buy['match_time']) + 1)
        client = Client(self.current, [buy, sell], 0)
        state, guard = StrategyState(), self.guard(client)
        state.local_positions[(self.current.condition_id, self.current.up_token, 'UP')] = position(self.current)
        result = guard.sync(self.current, state)
        self.assertEqual(result['positions'], {})
        self.assertEqual(state.local_positions, {})

    def test_available_sell_is_clipped_by_balance_and_open_sell_reservations(self):
        client = Client(self.current, [own_trade(self.current)], 3.2)
        client.orders = [
            {'asset_id': self.current.up_token, 'side': 'SELL', 'original_size': '2', 'size_matched': '.5'},
            {'asset_id': self.current.down_token, 'side': 'SELL', 'original_size': '20', 'size_matched': '0'}]
        self.assertAlmostEqual(self.guard(client).available_to_sell(self.current, self.current.up_token), 1.7)

    def test_invalid_sell_reservations_cannot_be_treated_as_zero(self):
        client = Client(self.current, [own_trade(self.current)], 5.37)
        client.orders = [{'asset_id': self.current.up_token, 'side': 'SELL', 'original_size': '1', 'size_matched': '2'}]
        with self.assertRaises(ValueError):
            self.guard(client).available_to_sell(self.current, self.current.up_token)

    def test_missing_conditional_balance_is_not_zero(self):
        client = Client(self.current)
        client.balances[self.current.up_token] = None
        with self.assertRaises(ValueError):
            self.guard(client).sync(self.current, StrategyState())

    def test_trade_read_failure_does_not_clear_tracked_inventory(self):
        client, state = Client(self.current), StrategyState()
        client.records = TimeoutError('offline fixture')
        state.local_positions[(self.current.condition_id, self.current.up_token, 'UP')] = position(self.current)
        with self.assertRaises(TimeoutError):
            self.guard(client).sync(self.current, state)
        self.assertEqual(next(iter(state.local_positions.values())).remaining_size, 5.37)

    def test_unknown_submit_without_order_id_stays_blocked_across_new_worker(self):
        client, guard = Client(self.current), None
        guard = self.guard(client)
        self.claim(guard, client)
        guard.record_result(self.current, OrderResult(None, 'timeout', 0, 'timeout', submitted=True, ambiguous=True))
        restarted = self.guard(client)
        restarted.sync(self.current, StrategyState())
        claimed, _ = restarted.claim_entry(self.current, self.current.up_token, 'UP', 5.37, .85)
        self.assertFalse(claimed)
        self.assertTrue(restarted.snapshot['ambiguous_entry'])

    def test_none_order_snapshot_cannot_prove_cancelled_zero(self):
        client, guard = Client(self.current), None
        guard = self.guard(client)
        self.claim(guard, client)
        guard.record_result(self.current, OrderResult('unknown-order', 'pending', 0, None, submitted=True, ambiguous=True))
        restarted = self.guard(client)
        result = restarted.sync(self.current, StrategyState())
        self.assertTrue(result['ambiguous_entry'])
        self.assertIsNotNone(restarted.entry_reason(self.current))

    def test_terminal_zero_order_evidence_releases_intent(self):
        client, guard = Client(self.current), None
        guard = self.guard(client)
        self.claim(guard, client)
        guard.record_result(self.current, OrderResult('cancelled-order', 'pending', 0, None, submitted=True, ambiguous=True))
        client.order_states['cancelled-order'] = {'id': 'cancelled-order', 'asset_id': self.current.up_token,
            'side': 'BUY', 'original_size': '5.37', 'size_matched': '0', 'status': 'CANCELED'}
        restarted = self.guard(client)
        restarted.sync(self.current, StrategyState())
        self.assertFalse(restarted.snapshot['ambiguous_entry'])
        claimed, reason = restarted.claim_entry(self.current, self.current.up_token, 'UP', 5.37, .85)
        self.assertTrue(claimed, reason)

    def test_later_zero_result_cannot_erase_previous_partial_fill_or_order_ids(self):
        client, guard = Client(self.current), None
        guard = self.guard(client)
        self.claim(guard, client)
        guard.record_result(self.current, OrderResult('maker', 'maker_partial_cancelled', 2, None,
            submitted=True, terminal=True, fallback_safe=True, remaining_size=3.37))
        guard.record_result(self.current, OrderResult('fallback', 'cancelled', 0, None,
            submitted=True, terminal=True))
        intent = guard._read(self.current.condition_id)
        self.assertEqual(intent['state'], 'filled')
        self.assertEqual(intent['confirmed_fill_size'], 2)
        self.assertEqual(intent['order_ids'], ['fallback', 'maker'])
        self.assertFalse(guard.claim_entry(self.current, self.current.up_token, 'UP', 5.37, .85)[0])

    def test_repeated_record_of_same_fill_does_not_double_inventory_evidence(self):
        client, guard = Client(self.current), None
        guard = self.guard(client)
        self.claim(guard, client)
        result = OrderResult('maker', 'matched', 5.37, None, submitted=True, terminal=True)
        guard.record_result(self.current, result)
        guard.record_result(self.current, result)
        self.assertEqual(guard._read(self.current.condition_id)['confirmed_fill_size'], 5.37)


if __name__ == '__main__':
    unittest.main()
