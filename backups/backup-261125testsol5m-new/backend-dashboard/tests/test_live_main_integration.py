"""Offline regressions at the live loop boundary; every submit call is mocked."""
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from bot import main
    from bot.book import BookLevel, TopOfBook
    from bot.config import Config
    from bot.markets import LiveMarket
    from bot.orders import OrderResult
    from bot.strategy import StrategyState, TrackedPosition
except ModuleNotFoundError as exc:
    raise unittest.SkipTest('Run in the deployed SDK environment: ' + str(exc.name))


def result(size=0., *, order_id='maker-order', price=.85, **kwargs):
    return OrderResult(order_id=order_id, status='matched', filled_size=size,
        error=None, submitted=True, avg_price=price, filled_amount=size * price,
        **kwargs)


def config():
    return Config(private_key='', wallet_address='', funder_address='', signature_type=0,
        chain_id=137, clob_host='https://example.invalid', gamma_host='https://example.invalid',
        polygon_rpc='', api_key='', api_secret='', api_passphrase='',
        reversal_exit_window_sec=180., reversal_held_bid_drawdown=.1,
        reversal_confirm_checks=1, profit_exit_enabled=True,
        profit_exit_order_mode='TAKER', order_retry_cooldown_sec=0.)


class MainExecutionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.current = LiveMarket('condition', 'btc-updown-5m-fixture', 'up', 'down',
            1_000., 1_300., .01, False)

    def combine(self, maker, taker, target=10.):
        return main._combine_buy_results(maker, taker, target_size=target,
            maker_price=.85, taker_price=.81)

    def test_combined_overfill_is_retained_and_blocks_further_entry(self):
        combined = self.combine(result(5.38, terminal=True),
            result(6.16, order_id='fallback-order', price=.75, terminal=True))
        self.assertAlmostEqual(combined.filled_size, 11.54)
        self.assertAlmostEqual(combined.filled_amount, 5.38 * .85 + 6.16 * .75)
        self.assertTrue(combined.ambiguous)
        self.assertFalse(combined.fallback_safe)
        self.assertEqual(combined.raw['component_order_ids'], ['maker-order', 'fallback-order'])

    def test_known_maker_fill_survives_unknown_fallback(self):
        combined = self.combine(result(3., terminal=True),
            result(0., order_id='fallback-order', ambiguous=True))
        self.assertAlmostEqual(combined.filled_size, 3.)
        self.assertTrue(combined.ambiguous)
        self.assertFalse(combined.terminal)

    def test_same_order_cumulative_observations_are_not_added(self):
        combined = self.combine(result(3.), result(5.38))
        self.assertAlmostEqual(combined.filled_size, 5.38)
        self.assertTrue(combined.ambiguous)
        self.assertTrue(combined.raw['duplicate_component_order'])

    def test_verified_residual_limits_fallback_shares_when_price_improves(self):
        maker = result(3., terminal=True, fallback_safe=True, remaining_size=7.)
        fallback = main._maker_fallback_size(maker, target_size=10., total_budget=8.6,
            maker_price=.85, taker_price=.50)
        # Spending the old dollar budget at .50 would buy 12.1 shares.
        self.assertEqual(fallback, 7.)

    def test_remaining_budget_and_fees_limit_fallback(self):
        maker = result(3., terminal=True, fallback_safe=True, remaining_size=7.)
        fallback = main._maker_fallback_size(maker, target_size=10., total_budget=5.,
            maker_price=.85, taker_price=.84, fee_per_share=.01)
        self.assertEqual(fallback, 2.88)
        self.assertLessEqual(maker.filled_amount + fallback * .85, 5.)

    def test_fallback_requires_terminal_cancel_and_known_remainder(self):
        safe = result(3., terminal=True, fallback_safe=True, remaining_size=7.)
        for changed in ({'terminal': False}, {'ambiguous': True},
                        {'fallback_safe': False}, {'remaining_size': None}):
            with self.subTest(changed=changed):
                self.assertEqual(main._maker_fallback_size(replace(safe, **changed),
                    target_size=10., total_budget=8.6, maker_price=.85, taker_price=.84), 0.)

    def test_fallback_cannot_use_more_than_cancelled_order_remainder(self):
        maker = result(3., terminal=True, fallback_safe=True, remaining_size=2.)
        self.assertEqual(main._maker_fallback_size(maker, target_size=10., total_budget=20.,
            maker_price=.85, taker_price=.84), 2.)

    def test_guard_refresh_does_not_apply_known_sell_twice(self):
        guard = SimpleNamespace(sync=Mock(), snapshot={'complete': True}, last_error=None)
        state = SimpleNamespace(live_execution_guard=guard, note_exit_fill=Mock())
        main._refresh_after_pending_exit(state, self.current, token_id='up', side='UP',
            filled_size=6.16, avg_price=.82, order_id='sell')
        guard.sync.assert_called_once_with(self.current, state)
        state.note_exit_fill.assert_not_called()

    def test_failed_guard_refresh_disables_new_entry(self):
        guard = SimpleNamespace(sync=Mock(side_effect=TimeoutError()),
            snapshot={'complete': True}, last_error=None)
        state = SimpleNamespace(live_execution_guard=guard, note_exit_fill=Mock())
        main._refresh_after_pending_exit(state, self.current, token_id='up', side='UP',
            filled_size=6.16, avg_price=.82, order_id='sell')
        self.assertFalse(guard.snapshot['complete'])
        self.assertEqual(guard.last_error, 'TimeoutError')
        state.note_exit_fill.assert_not_called()

    def test_without_guard_only_incremental_pending_fill_is_applied(self):
        state = SimpleNamespace(note_exit_fill=Mock())
        main._refresh_after_pending_exit(state, self.current, token_id='up', side='UP',
            filled_size=6.16, previously_known=5., avg_price=.82, order_id='sell')
        self.assertAlmostEqual(state.note_exit_fill.call_args.args[3], 1.16)

    def test_repeated_cumulative_pending_fill_has_no_second_local_decrement(self):
        state = SimpleNamespace(note_exit_fill=Mock())
        main._refresh_after_pending_exit(state, self.current, token_id='up', side='UP',
            filled_size=6.16, previously_known=6.16, avg_price=.82, order_id='sell')
        state.note_exit_fill.assert_not_called()

    def test_lagging_trade_index_cannot_erase_acknowledged_sell(self):
        acknowledged = result(6.16, order_id='sell', price=.82, terminal=True)
        with patch.object(main, 'reconcile_recent_trade', return_value=result(3., order_id='sell')):
            actual = main._reconcile_exit_result(config(), Mock(), self.current, 'up',
                acknowledged, requested_size=6.16)
        self.assertIs(actual, acknowledged)

    def test_partial_fill_does_not_prove_ambiguous_order_terminal(self):
        unknown = result(0., order_id='sell', ambiguous=True)
        with patch.object(main, 'reconcile_recent_trade', return_value=result(3., order_id='sell')):
            actual = main._reconcile_exit_result(config(), Mock(), self.current, 'up',
                unknown, requested_size=10.)
        self.assertEqual(actual.filled_size, 3.)
        self.assertTrue(actual.ambiguous)
        self.assertFalse(actual.terminal)

    def test_full_fill_can_resolve_unknown_fok(self):
        with patch.object(main, 'reconcile_recent_trade', return_value=result(10., order_id='sell')):
            actual = main._reconcile_exit_result(config(), Mock(), self.current, 'up',
                result(0., order_id='sell', ambiguous=True), requested_size=10.)
        self.assertFalse(actual.ambiguous)
        self.assertEqual(actual.filled_size, 10.)

    def test_known_partial_does_not_release_ambiguous_exit_intent(self):
        self.assertEqual(main._exit_intent_status(result(3., ambiguous=True),
            filled_size=3., requested_size=10.), 'ambiguous')
        self.assertEqual(main._exit_intent_status(result(3., terminal=True),
            filled_size=3., requested_size=10.), 'partial')

    def tracked_state(self, *, size=10., price=.85, armed=True):
        state = StrategyState()
        state.local_positions[('condition', 'up', 'UP')] = TrackedPosition(
            self.current.market_slug, 'condition', 'up', 'UP', size, size, price,
            size * price, stop_loss_pending=armed)
        state.live_authoritative = True
        state.live_execution_guard = SimpleNamespace(available_to_sell=Mock(return_value=size),
            sync=Mock(), snapshot={'complete': True})
        return state

    def books(self):
        return (TopOfBook(.60, 20., .62, 20., bids=(BookLevel(.60, 20.),)),
                TopOfBook(.38, 20., .40, 20., bids=(BookLevel(.38, 20.),)))

    def test_pending_partial_sell_stays_unknown_without_terminal_order(self):
        self._pending_sell_test(order_snapshot=None, expected='ambiguous')

    def test_pending_partial_sell_can_release_only_after_terminal_cancel(self):
        self._pending_sell_test(order_snapshot={'id': 'sell', 'asset_id': 'up', 'side': 'SELL',
            'original_size': '10', 'size_matched': '3', 'status': 'CANCELED'}, expected='partial')

    def _pending_sell_test(self, *, order_snapshot, expected):
        state = self.tracked_state()
        pending = {'updated_ts': 970., 'requested_size': 10., 'order_id': 'sell',
            'filled_size': 3., 'tier': 'stop_loss'}
        client = SimpleNamespace(get_order=Mock(return_value=order_snapshot))
        with patch.object(main.time, 'time', return_value=1_000.), \
             patch.object(main.store, 'pending_exit_intent', return_value=pending), \
             patch.object(main.store, 'upsert_exit_intent') as upsert, \
             patch.object(main.store, 'log_decision'), \
             patch.object(main, 'reconcile_recent_trade', return_value=result(3., order_id='sell')), \
             patch.object(main, 'place_sell_fok') as submit:
            acted = main.maybe_reversal_exit(config(), client, self.current, *self.books(),
                t_rem=100., dry_run=False, confirmations={}, exit_attempts={}, strategy_state=state)
        self.assertTrue(acted)
        self.assertEqual(upsert.call_args.kwargs['status'], expected)
        submit.assert_not_called()
        state.live_execution_guard.sync.assert_called_once()
        # Authenticated sync owns the quantity; the cumulative fill is not
        # blindly subtracted a second time from its rebuilt local position.
        self.assertEqual(state.active_position('condition', 'up', 'UP').remaining_size, 10.)

    def test_unpriced_authenticated_inventory_uses_protective_exit_not_profit(self):
        state = self.tracked_state(size=5.37, price=0.)
        with patch.object(main.time, 'time', return_value=1_000.), \
             patch.object(main.store, 'pending_exit_intent', return_value=None), \
             patch.object(main.store, 'latest_exit_attempt_ts', return_value=0.), \
             patch.object(main.store, 'log_decision'), \
             patch.object(main.store, 'upsert_exit_intent') as upsert, \
             patch.object(main.store, 'log_order'), \
             patch.object(main.store, 'log_execution_audit'), \
             patch.object(main, 'place_sell_fok', return_value=result(5.37, order_id='sell', price=.60)), \
             patch.object(main, '_reconcile_exit_result', side_effect=lambda cfg, cl, cur, token, value, **kw: value):
            acted = main.maybe_reversal_exit(config(), Mock(), self.current, *self.books(),
                t_rem=200., dry_run=False, confirmations={}, exit_attempts={}, strategy_state=state)
        self.assertTrue(acted)
        self.assertEqual(upsert.call_args.kwargs['tier'], 'stop_loss')
        self.assertEqual(upsert.call_args.kwargs['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
