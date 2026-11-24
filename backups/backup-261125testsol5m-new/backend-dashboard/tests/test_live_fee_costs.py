"""Actual FIFO admission-cost logic, without importing a signing SDK."""
import ast
import math
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.execution_costs import FeeSchedule


# Compile the production pure function and its numeric helper. This permits
# the same cost regressions on review machines without CLOB credentials/SDK.
source = ast.parse((ROOT / 'bot/live_execution.py').read_text(encoding='utf-8'))
nodes = [node for node in source.body
         if isinstance(node, ast.FunctionDef) and node.name in {'aggregate_positions', '_number'}]
namespace = {'FeeSchedule': FeeSchedule, 'math': math}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'bot/live_execution.py', 'exec'), namespace)
aggregate_positions = namespace['aggregate_positions']


def fill(side='BUY', quantity=5, price=.85, role='TAKER', ts=100, order='buy'):
    return {'token_id': 'up', 'side': side, 'size': quantity, 'price': price,
            'liquidity_role': role, 'ts': ts, 'order_id': order,
            'trade_id': f'trade-{order}', 'status': 'CONFIRMED'}


class LiveFeeCostsTests(unittest.TestCase):
    market = types.SimpleNamespace(condition_id='condition', up_token='up', down_token='down')

    def aggregate(self, fills, balance, schedule=FeeSchedule(.07)):
        positions, _, _ = aggregate_positions(fills, {'up': balance, 'down': 0},
                                               market=self.market, fee_schedule=schedule)
        return positions['up']

    def test_taker_entry_fee_and_cost_are_kept_separately(self):
        position = self.aggregate([fill()], 5)
        self.assertAlmostEqual(position['entry_cost_remaining_usd'], 4.25)
        self.assertAlmostEqual(position['entry_fees_remaining_usd'], .044625)
        self.assertTrue(position['entry_fee_complete'])
        self.assertTrue(position['fee_estimated'])
        self.assertEqual(position['fee_source'], 'authenticated_fill_protocol_fee_estimate')

    def test_maker_zero_requires_explicit_taker_only_schedule(self):
        position = self.aggregate([fill(role='MAKER')], 5)
        self.assertEqual(position['entry_fees_remaining_usd'], 0)
        self.assertEqual(position['fee_source'], 'authenticated_maker_zero_protocol')
        missing = self.aggregate([fill(role='MAKER')], 5, schedule=None)
        self.assertIsNone(missing['entry_fees_remaining_usd'])
        self.assertFalse(missing['entry_fee_complete'])

    def test_missing_schedule_never_invents_zero_taker_fee(self):
        position = self.aggregate([fill()], 5, schedule=None)
        self.assertIsNone(position['entry_fees_remaining_usd'])
        self.assertEqual(position['fee_source'], 'fee_schedule_unavailable')

    def test_unknown_role_uses_explicit_conservative_taker_estimate(self):
        position = self.aggregate([fill(role='')], 5)
        self.assertAlmostEqual(position['entry_fees_remaining_usd'], .044625)
        self.assertIn('unknown_role_conservative_taker', position['fee_source'])

    def test_partial_sell_releases_only_consumed_lot_fee(self):
        position = self.aggregate([fill(), fill('SELL', 3, .8, ts=101, order='sell')], 2)
        self.assertAlmostEqual(position['entry_cost_remaining_usd'], 1.7)
        self.assertAlmostEqual(position['entry_fees_remaining_usd'], .01785)
        self.assertEqual(position['size'], 2)

    def test_fifo_exhausts_taker_lot_before_maker_lot(self):
        records = [fill(quantity=6, order='taker'),
                   fill(quantity=4, price=.86, role='MAKER', ts=101, order='maker'),
                   fill('SELL', 8, .88, ts=102, order='sell')]
        position = self.aggregate(records, 2)
        self.assertAlmostEqual(position['price'], .86)
        self.assertAlmostEqual(position['entry_cost_remaining_usd'], 1.72)
        self.assertEqual(position['entry_fees_remaining_usd'], 0)
        self.assertEqual(position['fee_source'], 'authenticated_maker_zero_protocol')

    def test_fee_metadata_changes_are_applied_to_current_market_schedule(self):
        position = self.aggregate([fill()], 5, schedule=FeeSchedule(.04, 2))
        self.assertAlmostEqual(position['entry_fees_remaining_usd'], .003252)

    def test_unpriced_external_balance_has_no_fabricated_cost_or_fee(self):
        position = self.aggregate([], 5)
        self.assertTrue(position['unpriced'])
        self.assertIsNone(position['entry_fees_remaining_usd'])
        self.assertFalse(position['entry_fee_complete'])


if __name__ == '__main__':
    unittest.main()
