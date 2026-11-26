from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.book import BookLevel,TopOfBook
from bot.paper_filters import BinnedCalibration,FeatureWindow,FilterPolicy,evaluate_filters,inventory_reason


class ForwardCalibrationTests(unittest.TestCase):
    def test_untrained_model_does_not_turn_payout_headroom_into_probability(self):
        model=BinnedCalibration(3)
        estimate=model.estimate(2.,now=1000.)
        self.assertFalse(estimate['available'])
        self.assertIsNone(estimate['p_win'])
        self.assertEqual(estimate['reason'],'PROBABILITY_WARMUP')

    def test_only_one_market_sample_and_no_future_or_unofficial_outcomes(self):
        model=BinnedCalibration(1)
        self.assertTrue(model.record('a',observed_at=10,end_ts=20,side='UP',normalized_delta=2))
        self.assertFalse(model.record('a',observed_at=11,end_ts=20,side='DOWN',normalized_delta=3))
        with self.assertRaises(ValueError): model.resolve('a','UP',resolved_at=19,source='gamma_closed')
        with self.assertRaises(ValueError): model.resolve('a','UP',resolved_at=21,source='last_bid')
        self.assertTrue(model.resolve('a','UP',resolved_at=21,source='gamma_closed_outcome_prices'))
        self.assertFalse(model.resolve('a','DOWN',resolved_at=22,source='gamma_closed'))
        self.assertFalse(model.estimate(2,now=20)['available'])
        estimate=model.estimate(2,now=22)
        self.assertTrue(estimate['available'])
        self.assertLess(estimate['p_lower'],estimate['p_win'])

    def test_minimum_independent_market_count_and_restore(self):
        model=BinnedCalibration(30)
        for i in range(30):
            model.record(str(i),observed_at=i,end_ts=100,side='UP',normalized_delta=1.5)
            model.resolve(str(i),'UP',resolved_at=101,source='gamma_closed')
        self.assertTrue(model.estimate(1.5,now=102)['available'])
        self.assertFalse(model.estimate(3,now=102)['available'])
        restored=BinnedCalibration(30,model.snapshot())
        self.assertEqual(restored.estimate(1.5,now=102),model.estimate(1.5,now=102))
        self.assertEqual(restored.progress()['settled_markets'],30)


class FeatureTests(unittest.TestCase):
    def test_duplicate_and_out_of_order_timestamps_cannot_add_confirmations(self):
        window=FeatureWindow()
        self.assertTrue(window.observe('m',1,100.,90.))
        self.assertFalse(window.observe('m',1,105.,90.))
        self.assertFalse(window.observe('m',.5,105.,90.))
        self.assertEqual(window.features('m','UP',now=1,remaining=60)['sample_count'],1)

    def test_anchor_reversal_and_retreat_expose_false_breakout_and_decay(self):
        window=FeatureWindow()
        deltas=[12,15,-2,16,-1,20,25,20,18,15,12]
        for i,value in enumerate(deltas): window.observe('m',100.+i,1000.+value,1000.)
        features=window.features('m','UP',now=110.,remaining=60.)
        self.assertGreater(features['anchor_crossings'],1)
        self.assertLess(features['recent_velocity'],0)
        book=TopOfBook(.84,100,.85,100,(BookLevel(.84,100),),(BookLevel(.85,100),),110.)
        verdict=evaluate_filters(features,{'available':False,'reason':'PROBABILITY_WARMUP'},book=book,quantity=5.,executable_cost_usd=4.25,entry_fee_usd=.04,now=110.)
        self.assertFalse(verdict['allow'])
        self.assertIn('FALSE_BREAKOUT',verdict['reasons'])
        self.assertIn('MOMENTUM_DECAY',verdict['reasons'])

    def test_probability_and_full_costs_are_required_even_for_stable_breakout(self):
        window=FeatureWindow()
        for i in range(12): window.observe('m',100.+i,1010.+2*i,1000.)
        features=window.features('m','UP',now=111.,remaining=60.)
        book=TopOfBook(.84,100,.85,100,(BookLevel(.84,100),),(BookLevel(.85,100),),111.)
        good=evaluate_filters(features,{'available':True,'p_lower':.95},book=book,quantity=5.,executable_cost_usd=4.25,entry_fee_usd=.04,now=111.)
        self.assertTrue(good['allow'],good)
        poor=evaluate_filters(features,{'available':True,'p_lower':.87},book=book,quantity=5.,executable_cost_usd=4.25,entry_fee_usd=.04,now=111.)
        self.assertIn('INSUFFICIENT_NET_EDGE',poor['reasons'])
        stale=evaluate_filters(features,{'available':True,'p_lower':.95},book=book,quantity=5.,executable_cost_usd=4.25,entry_fee_usd=.04,now=114.)
        self.assertIn('STALE_OR_INVALID_BOOK',stale['reasons'])

    def test_exit_fee_reserve_uses_market_worst_case_above_the_default_floor(self):
        window=FeatureWindow()
        for i in range(12):window.observe('m',100.+i,1010.+2*i,1000.)
        features=window.features('m','UP',now=111.,remaining=60.)
        book=TopOfBook(.84,100,.85,100,(BookLevel(.84,100),),(BookLevel(.85,100),),111.)
        verdict=evaluate_filters(features,{'available':True,'p_lower':.90},book=book,quantity=5.,
            executable_cost_usd=4.25,entry_fee_usd=.04,exit_fee_reserve_usd=.15,now=111.)
        self.assertEqual(verdict['exit_fee_reserve_per_share'],.03)
        self.assertIn('INSUFFICIENT_NET_EDGE',verdict['reasons'])


class InventoryTests(unittest.TestCase):
    def test_minimum_lot_never_rounds_up_past_risk_budget(self):
        self.assertEqual(inventory_reason(cash=100,quantity=2.3,price=.86,entry_fee=.02,budget=2), 'MINIMUM_ORDER_SIZE')
        self.assertEqual(inventory_reason(cash=100,quantity=5.,price=.86,entry_fee=.04,budget=2), 'MARKET_RISK_BUDGET')

    def test_pending_orders_and_existing_cost_use_same_market_budget(self):
        self.assertEqual(inventory_reason(cash=234,quantity=5.,price=.86,entry_fee=.04,budget=4.68,reserved_buy_usd=.5), 'MARKET_RISK_BUDGET')
        self.assertEqual(inventory_reason(cash=234,quantity=5.,price=.86,entry_fee=.04,budget=4.68,market_buy_count=1), 'MARKET_ALREADY_ENTERED')
        self.assertIsNone(inventory_reason(cash=234,quantity=5.,price=.86,entry_fee=.04,budget=4.68))


if __name__=='__main__': unittest.main()
