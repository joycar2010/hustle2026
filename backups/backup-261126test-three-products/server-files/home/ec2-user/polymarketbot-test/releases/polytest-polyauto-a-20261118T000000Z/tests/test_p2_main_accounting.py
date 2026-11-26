"""P2 race/cost regressions with no SDK, network, signer or real orders."""
import ast
import copy
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.book import BookLevel, TopOfBook
from bot.execution_costs import FeeSchedule, estimate_execution, evaluate_net_exit


class State:
    def __init__(self): self.local_positions = {}
    def reset_for_market(self, key): self.market_id = key


def position(size=10, order='entry'):
    return SimpleNamespace(remaining_size=size, entry_size=size, entry_price=.85,
        entry_order_id=order, stop_loss_pending=True, entry_cost_remaining_usd=size*.85,
        entry_fees_remaining_usd=size*.008925)


class P2MainTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse((ROOT/'bot/main.py').read_text(encoding='utf-8'))
        selected = {'_net_profit_exit_decision', '_profit_target_fraction', '_p2_entry_quote',
                    '_IndependentExitInventory'}
        nodes = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
        nodes += [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in selected]
        self.ns = {'copy':copy, 'threading':threading, 'StrategyState':State,
            'FeeSchedule':FeeSchedule, 'estimate_execution':estimate_execution, 'evaluate_net_exit':evaluate_net_exit,
            'time':SimpleNamespace(time=lambda:100.),
            'entry_price_bounds':lambda cfg, rule, side:(.01,.99),
            'required_net_edge':lambda cfg, price, rule:.04,
            'btc_signal_allows_entry':lambda cfg, signal, side, rule, price:signal != 'reversed'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
                     'bot/main.py','exec'),self.ns)
        self.cfg = SimpleNamespace(profit_exit_enabled=True, profit_target_fraction=.05,
                                   profit_target_ticks=2, min_t_remaining_sec=120,
                                   tail_entry_min_t_remaining_sec=2, ws_exit_max_book_age_sec=1.5)
        self.market = SimpleNamespace(condition_id='market', tick_size=.01,
            fee_metadata={'feeSchedule':{'rate':.07,'exponent':1,'takerOnly':True}},
            t_remaining=lambda:150.)
        self.key = ('market','up','UP')
        self.feed_position = position()
        self.sync_hook = None
        owner = self
        class Guard:
            def __init__(self,*args): self.snapshot={}
            def sync(self,market,state):
                if owner.sync_hook: owner.sync_hook()
                prior=state.local_positions.get(owner.key)
                row=copy.copy(owner.feed_position)
                if prior: row.stop_loss_pending=prior.stop_loss_pending
                state.local_positions={owner.key:row}
                self.snapshot={'complete':True}
        self.ns['LiveExecutionGuard']=Guard
        self.inventory=self.ns['_IndependentExitInventory'](self.cfg,object(),lambda t:'cached-book',threading.Event())

    def book(self,bid=.95,ask=.96,ts=100.):
        return TopOfBook(bid,20.,ask,20.,(BookLevel(bid,20.),),(BookLevel(ask,20.),),ts)

    def test_partial_available_inventory_allocates_entry_fee_pro_rata(self):
        result=self.ns['_net_profit_exit_decision'](self.cfg,self.market,self.book(),position(),5,.85)
        self.assertTrue(result.should_exit)
        self.assertAlmostEqual(result.allocated_cost_usd,(8.5+.08925)/2)
        self.assertAlmostEqual(result.net_profit_usd,4.75-.016625-(8.5+.08925)/2)

    def test_known_maker_entry_fee_is_not_replaced_by_taker_estimate(self):
        p=position();p.entry_fees_remaining_usd=0
        result=self.ns['_net_profit_exit_decision'](self.cfg,self.market,self.book(),p,5,.85)
        self.assertAlmostEqual(result.allocated_cost_usd,4.25)

    def test_missing_entry_fee_uses_full_position_then_pro_rata(self):
        p=position();p.entry_fees_remaining_usd=None
        result=self.ns['_net_profit_exit_decision'](self.cfg,self.market,self.book(),p,5,.85)
        self.assertAlmostEqual(result.allocated_cost_usd,(8.5+.08925)/2)

    def test_refresh_retains_state_identity_and_armed_exit(self):
        self.inventory.reconcile(self.market)
        state=self.inventory.states['market']
        self.inventory.reconcile(self.market)
        self.assertIs(self.inventory.states['market'],state)
        self.assertTrue(state.local_positions[self.key].stop_loss_pending)
        self.assertEqual(state.execution_book_provider('up'),'cached-book')

    def test_slow_snapshot_cannot_overwrite_concurrent_partial_exit(self):
        self.inventory.reconcile(self.market)
        started,release=threading.Event(),threading.Event()
        def block(): started.set();release.wait(2.)
        self.sync_hook=block
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.inventory.reconcile(self.market)))
        worker.start();self.assertTrue(started.wait(1.))
        try:
            self.inventory.execute(self.market,
                lambda state:setattr(state.local_positions[self.key],'remaining_size',5))
        finally:
            release.set();worker.join(2.)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results,[False])
        self.assertEqual(self.inventory.positions(self.market)[0].remaining_size,5)

    def test_next_lagging_snapshot_cannot_resurrect_acknowledged_partial_or_full_exit(self):
        self.inventory.reconcile(self.market)
        self.inventory.execute(self.market,
            lambda state:setattr(state.local_positions[self.key],'remaining_size',5))
        self.inventory.reconcile(self.market)
        row=self.inventory.positions(self.market)[0]
        self.assertEqual(row.remaining_size,5)
        self.assertAlmostEqual(row.entry_cost_remaining_usd,4.25)
        self.assertAlmostEqual(row.entry_fees_remaining_usd,.044625)
        self.inventory.execute(self.market,lambda state:state.local_positions.clear())
        self.inventory.reconcile(self.market)
        self.assertEqual(self.inventory.positions(self.market),[])

    def test_new_entry_order_is_not_limited_by_old_exit_tombstone(self):
        self.inventory.reconcile(self.market)
        self.inventory.execute(self.market,lambda state:state.local_positions.clear())
        self.feed_position=position(5,'new-entry')
        self.inventory.reconcile(self.market)
        self.assertEqual(self.inventory.positions(self.market)[0].remaining_size,5)

    def test_dynamic_fee_change_can_disqualify_old_payout_headroom(self):
        self.market.fee_metadata['feeSchedule']['rate']=1.
        reason,_=self.ns['_p2_entry_quote'](self.cfg,self.market,self.book(.89,.9),5,.9,'edge',side='UP')
        self.assertEqual(reason,'fee_inclusive_payout_headroom_below_minimum')

    def test_maker_wait_cannot_fallback_on_stale_book_or_reversed_signal(self):
        reason,_=self.ns['_p2_entry_quote'](self.cfg,self.market,self.book(.89,.9,98.),5,.9,'edge',side='UP')
        self.assertEqual(reason,'book_stale_or_future')
        reason,_=self.ns['_p2_entry_quote'](self.cfg,self.market,self.book(.89,.9),5,.9,'edge',side='UP',signal='reversed')
        self.assertEqual(reason,'entry_signal_changed')

    def test_entry_window_elapsed_and_special_rule_minimum(self):
        self.market.t_remaining=lambda:10.
        reason,_=self.ns['_p2_entry_quote'](self.cfg,self.market,self.book(.89,.9),5,.9,'edge',side='UP')
        self.assertEqual(reason,'entry_window_elapsed')
        reason,_=self.ns['_p2_entry_quote'](self.cfg,self.market,self.book(.89,.9),5,.9,'tail_price',side='UP')
        self.assertIsNone(reason)


if __name__=='__main__': unittest.main()
