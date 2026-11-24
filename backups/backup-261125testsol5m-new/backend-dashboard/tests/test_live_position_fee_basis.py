"""Exercise the real FIFO reconciler without importing a signing SDK."""
import ast
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.execution_costs import FeeSchedule,estimate_execution,evaluate_net_exit
from bot.book import BookLevel,TopOfBook

source=Path(__file__).resolve().parents[1]/'bot/live_execution.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_number','aggregate_positions'}]
namespace={'math':math,'FeeSchedule':FeeSchedule}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),namespace)
aggregate=namespace['aggregate_positions']

MARKET=SimpleNamespace(condition_id='market',up_token='up',down_token='down')

def fill(side,q,p,ts,role='TAKER'):
    return {'side':side,'size':q,'price':p,'ts':ts,'liquidity_role':role,'token_id':'up',
            'order_id':str(ts),'trade_id':str(ts),'status':'CONFIRMED'}


class PositionFeeTests(unittest.TestCase):
    def positions(self,fills,size,schedule=FeeSchedule(.07)):
        return aggregate(fills,{'up':size,'down':0},market=MARKET,fee_schedule=schedule)[0]['up']

    def test_authenticated_maker_has_no_entry_fee(self):
        p=self.positions([fill('BUY',5,.85,1,'MAKER')],5)
        self.assertEqual(p['entry_fees_remaining_usd'],0)
        self.assertEqual(p['fee_source'],'authenticated_maker_zero_protocol')
        self.assertEqual(p['entry_cost_remaining_usd'],4.25)

    def test_taker_fee_is_explicit_estimate_not_chain_confirmed(self):
        p=self.positions([fill('BUY',6,.85,1)],6)
        self.assertAlmostEqual(p['entry_fees_remaining_usd'],.05355)
        self.assertEqual(p['fee_source'],'authenticated_fill_protocol_fee_estimate')
        self.assertTrue(p['fee_estimated'])

    def test_mixed_buys_and_fifo_exit_keep_only_unsold_lot_fee(self):
        p=self.positions([fill('BUY',5,.8,1,'MAKER'),fill('BUY',5,.9,2),fill('SELL',6,.91,3)],4)
        self.assertAlmostEqual(p['size'],4)
        self.assertAlmostEqual(p['entry_cost_remaining_usd'],3.6)
        self.assertAlmostEqual(p['entry_fees_remaining_usd'],.0252)
        self.assertEqual(p['fee_source'],'authenticated_fill_protocol_fee_estimate')

    def test_partial_lot_exit_allocates_fee_once(self):
        p=self.positions([fill('BUY',6,.85,1),fill('SELL',3,.9,2)],3)
        self.assertAlmostEqual(p['entry_fees_remaining_usd'],.026775)
        self.assertAlmostEqual(p['entry_cost_remaining_usd'],2.55)

    def test_unknown_role_is_conservative_taker_and_labelled(self):
        p=self.positions([fill('BUY',5,.85,1,None)],5)
        self.assertAlmostEqual(p['entry_fees_remaining_usd'],.044625)
        self.assertIn('unknown_role_conservative',p['fee_source'])

    def test_market_dynamic_rate_is_used(self):
        p=self.positions([fill('BUY',5,.85,1)],5,FeeSchedule(.04))
        self.assertAlmostEqual(p['entry_fees_remaining_usd'],.0255)

    def test_missing_fee_table_does_not_erase_exit_inventory(self):
        p=self.positions([fill('BUY',5,.85,1)],5,None)
        self.assertEqual(p['size'],5)
        self.assertEqual(p['available_size'],5)
        self.assertIsNone(p['entry_fees_remaining_usd'])
        self.assertFalse(p['entry_fee_complete'])
        b=TopOfBook(.95,10,.96,10,(BookLevel(.95,10),),(BookLevel(.96,10),),100)
        unknown=estimate_execution(b,'SELL',5,.9,None,now=100)
        self.assertFalse(evaluate_net_exit(unknown,position_size=5,remaining_cost_usd=4.25).available)

    def test_unexplained_balance_has_unknown_cost_and_fee(self):
        p=self.positions([],5)
        self.assertEqual(p['available_size'],5)
        self.assertTrue(p['unpriced'])
        self.assertIsNone(p['entry_fees_remaining_usd'])


if __name__=='__main__':unittest.main()
