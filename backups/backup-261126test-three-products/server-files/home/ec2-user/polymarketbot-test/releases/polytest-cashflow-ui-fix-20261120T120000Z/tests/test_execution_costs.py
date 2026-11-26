from pathlib import Path
import sys
import unittest
from decimal import Decimal

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.book import BookLevel,TopOfBook
from bot.execution_costs import FeeSchedule,estimate_execution,evaluate_net_exit,executable_entry_edge


def book(bids=((.85,10),),asks=((.86,10),),ts=100):
    return TopOfBook(bids[0][0] if bids else None,bids[0][1] if bids else 0,
                     asks[0][0] if asks else None,asks[0][1] if asks else 0,
                     tuple(BookLevel(*r) for r in bids),tuple(BookLevel(*r) for r in asks),ts)


class CostTests(unittest.TestCase):
    def setUp(self):self.schedule=FeeSchedule(.07)

    def test_market_fee_requires_explicit_schedule(self):
        with self.assertRaises(ValueError):FeeSchedule.from_market({'takerBaseFee':1000})
        with self.assertRaises(ValueError):FeeSchedule.from_market({'feeSchedule':{'rate':.07}})
        with self.assertRaises(ValueError):FeeSchedule.from_market({'feeSchedule':{'rate':.07,'exponent':1}})

    def test_fee_free_requires_explicit_disabled_metadata(self):
        s=FeeSchedule.from_market({'feesEnabled':False})
        self.assertEqual(s.fee(100,.5),0)

    def test_dynamic_market_fee_matches_confirmed_crypto_formula(self):
        s=FeeSchedule.from_market({'feeSchedule':{'rate':.07,'exponent':1,'takerOnly':True}},as_of=100)
        self.assertEqual(s.fee(6.16,.75),Decimal('.080850'))
        self.assertEqual(s.fee(6,.85),Decimal('.053550'))
        self.assertEqual(s.fee(6,.85,role='MAKER'),0)

    def test_different_schedule_and_exponent_are_used(self):
        s=FeeSchedule.from_market({'feeSchedule':{'rate':.04,'exponent':2,'takerOnly':True}})
        self.assertEqual(s.fee(100,.5),Decimal('.250000'))

    def test_invalid_numeric_or_negative_fee_is_not_accepted(self):
        for rate in (float('nan'),float('inf'),-.01,True,None,2):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):FeeSchedule(rate)

    def test_buy_walks_depth_not_best_ask_and_charges_fee_once(self):
        e=estimate_execution(book(asks=((.85,2),(.87,4))), 'BUY',6,.87,self.schedule,now=100)
        self.assertTrue(e.complete)
        self.assertAlmostEqual(e.gross_amount_usd,5.18)
        self.assertAlmostEqual(e.vwap,5.18/6)
        self.assertAlmostEqual(e.net_cash_change_usd,-e.gross_amount_usd-e.fee_usd)

    def test_sell_walks_bids_and_subtracts_fee_once(self):
        e=estimate_execution(book(bids=((.85,2),(.83,4))), 'SELL',6,.83,self.schedule,now=100)
        self.assertAlmostEqual(e.gross_amount_usd,5.02)
        self.assertAlmostEqual(e.net_cash_change_usd,e.gross_amount_usd-e.fee_usd)

    def test_depth_is_sorted_and_limit_is_respected(self):
        e=estimate_execution(book(asks=((.9,100),(.85,2),(.87,4))), 'BUY',6,.87,self.schedule,now=100)
        self.assertAlmostEqual(e.vwap,5.18/6)
        self.assertEqual(e.worst_price,.87)

    def test_fok_insufficient_depth_returns_no_execution(self):
        e=estimate_execution(book(asks=((.85,2),(.9,100))), 'BUY',6,.85,self.schedule,now=100)
        self.assertFalse(e.available)
        self.assertEqual(e.filled_size,0)

    def test_fak_can_value_partial_depth(self):
        e=estimate_execution(book(asks=((.85,2),(.9,100))), 'BUY',6,.85,self.schedule,now=100,require_complete=False)
        self.assertTrue(e.available)
        self.assertFalse(e.complete)
        self.assertEqual(e.filled_size,2)

    def test_stale_future_missing_book_and_fee_fail_closed(self):
        for b,fee in ((book(ts=98),self.schedule),(book(ts=101),self.schedule),(book(ts=0),self.schedule),(book(),None)):
            with self.subTest(book=b,fee=fee):
                self.assertFalse(estimate_execution(b,'SELL',5,.8,fee,now=100).available)

    def test_maker_is_conditional_limit_valuation_without_fee(self):
        e=estimate_execution(book(),'SELL',5,.88,self.schedule,now=100,liquidity_role='MAKER')
        self.assertEqual(e.net_cash_change_usd,4.4)
        self.assertEqual(e.fee_usd,0)
        self.assertEqual(e.vwap,.88)

    def test_gross_target_can_fail_after_both_sides_fees(self):
        e=estimate_execution(book(bids=((.91,10),)),'SELL',5,.9,self.schedule,now=100)
        result=evaluate_net_exit(e,position_size=5,remaining_cost_usd=4.3,entry_fees_usd=.04214,
                                 target_fraction=.05,profit_buffer_usd=.1)
        self.assertFalse(result.should_exit)
        self.assertAlmostEqual(result.allocated_cost_usd,4.34214)
        self.assertAlmostEqual(result.net_profit_usd,e.net_cash_change_usd-4.34214)

    def test_net_target_met_includes_paid_entry_fee(self):
        e=estimate_execution(book(bids=((.96,10),)),'SELL',5,.95,self.schedule,now=100)
        result=evaluate_net_exit(e,position_size=5,remaining_cost_usd=4.3,entry_fees_usd=.04214,
                                 target_fraction=.05,profit_buffer_usd=.1)
        self.assertTrue(result.should_exit)
        self.assertAlmostEqual(result.required_net_profit_usd,4.34214*.05+.1)

    def test_inclusive_cost_is_not_charged_entry_fee_again(self):
        e=estimate_execution(book(bids=((.96,10),)),'SELL',5,.95,self.schedule,now=100)
        a=evaluate_net_exit(e,position_size=5,remaining_cost_usd=4.3,entry_fees_usd=.04)
        b=evaluate_net_exit(e,position_size=5,remaining_cost_usd=4.34,entry_fees_usd=0)
        self.assertAlmostEqual(a.net_profit_usd,b.net_profit_usd)

    def test_partial_exit_allocates_remaining_cost_proportionally(self):
        e=estimate_execution(book(bids=((.95,2),)),'SELL',5,.9,self.schedule,now=100,require_complete=False)
        r=evaluate_net_exit(e,position_size=5,remaining_cost_usd=4.3,entry_fees_usd=.04)
        self.assertAlmostEqual(r.allocated_cost_usd,4.34*2/5)

    def test_unknown_cost_no_exit_profit_claim(self):
        e=estimate_execution(book(),'SELL',5,.8,self.schedule,now=100)
        for cost in (None,0,float('nan')):
            self.assertFalse(evaluate_net_exit(e,position_size=5,remaining_cost_usd=cost).available)

    def test_entry_ev_uses_probability_not_assumed_one_dollar(self):
        e=estimate_execution(book(),'BUY',5,.86,self.schedule,now=100)
        edge=executable_entry_edge(.85,e,uncertainty_buffer=.01)
        self.assertLess(edge,0)
        self.assertAlmostEqual(edge,.85-.01-(-e.net_cash_change_usd)/5)


if __name__=='__main__':unittest.main()
