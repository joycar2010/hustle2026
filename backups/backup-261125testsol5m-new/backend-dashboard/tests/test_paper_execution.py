from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.book import BookLevel,TopOfBook
from bot.execution_costs import FeeSchedule
from bot.paper_execution import PaperBroker


def book(bids=((.84,10),),asks=((.86,10),),ts=100):
    return TopOfBook(bids[0][0] if bids else None,bids[0][1] if bids else 0,
                     asks[0][0] if asks else None,asks[0][1] if asks else 0,
                     tuple(BookLevel(*r) for r in bids),tuple(BookLevel(*r) for r in asks),ts)


class PaperTests(unittest.TestCase):
    def broker(self,**kwargs):
        b=PaperBroker(starting_cash=236.006313,schedule=FeeSchedule(.07),submission_latency_sec=0,**kwargs)
        b.on_book('up',book())
        return b

    def buy(self,b,qty=5,now=100):
        o=b.submit('BUY','up',qty,.86,now=now)
        self.assertEqual(o.status,'FILLED')
        return o

    def test_fok_fee_inclusive_cash_and_inventory(self):
        b=self.broker();o=self.buy(b)
        self.assertAlmostEqual(b.cash,236.006313-4.3-.04214)
        self.assertEqual(b.inventory('up')['quantity'],5)
        self.assertAlmostEqual(b.inventory('up')['entry_fees_usd'],.04214)
        fill=b.drain_fills()[0]
        self.assertEqual(fill['liquidity_role'],'TAKER')
        self.assertAlmostEqual(fill['fee_usd'],-.04214)
        self.assertAlmostEqual(fill['cashflow_usd'],-4.34214)

    def test_minimum_size_budget_and_tick_are_enforced(self):
        b=self.broker()
        for qty,price,reason in ((4.9,.86,'below_minimum_shares'),(5,.865,'invalid_tick')):
            o=b.submit('BUY','up',qty,price,now=100)
            self.assertEqual(o.rejection_reason,reason)
        small=PaperBroker(2,FeeSchedule(.07),submission_latency_sec=0)
        small.on_book('up',book())
        self.assertEqual(small.submit('BUY','up',5,.86,now=100).rejection_reason,'insufficient_available_cash')

    def test_missing_market_fee_cannot_fake_fee_free_trade(self):
        b=PaperBroker();b.on_book('up',book())
        self.assertEqual(b.submit('BUY','up',5,.86,now=100).rejection_reason,'fee_schedule_unavailable')

    def test_post_only_crossing_is_rejected(self):
        b=self.broker()
        o=b.submit('BUY','up',5,.86,'GTC',True,100)
        self.assertEqual(o.rejection_reason,'post_only_would_cross')

    def test_float_tick_noise_is_normalised_but_real_step_violation_rejected(self):
        b=self.broker()
        o=b.submit('BUY','up',5,70*.01,'GTC',True,100)
        self.assertEqual(o.status,'OPEN')
        bad=b.submit('BUY','up',5.001,.85,'GTC',True,100)
        self.assertEqual(bad.rejection_reason,'invalid_quantity_step')

    def test_limit_or_book_touch_does_not_fill_maker(self):
        b=self.broker()
        o=b.submit('BUY','up',5,.84,'GTC',True,100)
        b.on_book('up',book(bids=((.84,5),),asks=((.84,10),),ts=100.2))
        b.advance(100.2)
        self.assertEqual(o.filled_size,0)
        self.assertEqual(b.inventory('up')['quantity'],0)

    def test_maker_queue_volume_must_clear_then_can_partially_fill(self):
        b=self.broker()
        o=b.submit('BUY','up',5,.84,'GTC',True,100)
        b.on_trade('up',.84,8,'SELL',100.1,'a')
        self.assertEqual(o.filled_size,0)
        b.on_trade('up',.84,4,'SELL',100.2,'b')
        self.assertEqual(o.filled_size,2)
        self.assertEqual(o.remaining_size,3)
        fills=b.drain_fills()
        self.assertEqual(len(fills),1)
        self.assertEqual(fills[0]['fee_usd'],0)
        b.on_trade('up',.84,3,'SELL',100.3,'c')
        self.assertTrue(o.terminal)

    def test_duplicate_and_wrong_direction_trade_do_not_fill(self):
        b=self.broker()
        o=b.submit('BUY','up',5,.85,'GTC',True,100)
        b.on_trade('up',.85,3,'BUY',100.1,'wrong')
        self.assertEqual(o.filled_size,0)
        b.on_trade('up',.85,3,'SELL',100.2,'fill')
        b.on_trade('up',.85,3,'SELL',100.2,'fill')
        self.assertEqual(o.filled_size,3)

    def test_trade_before_order_eligibility_cannot_fill(self):
        b=PaperBroker(100,FeeSchedule(.07),submission_latency_sec=.2)
        b.on_book('up',book())
        o=b.submit('BUY','up',5,.85,'GTC',True,100)
        b.on_trade('up',.85,100,'SELL',100.1,'early')
        self.assertEqual(o.status,'PENDING')
        self.assertEqual(o.filled_size,0)
        b.on_trade('up',.85,2,'SELL',100.3,'later')
        self.assertEqual(o.filled_size,2)

    def test_cancel_in_flight_keeps_cash_reserved_and_allows_pre_final_fill(self):
        b=self.broker(cancel_latency_sec=.3)
        o=b.submit('BUY','up',5,.85,'GTC',True,100)
        b.cancel(o.order_id,100.1)
        self.assertEqual(o.status,'CANCEL_PENDING')
        self.assertGreater(float(b.reserved_cash()),0)
        b.on_trade('up',.85,2,'SELL',100.2,'race')
        self.assertEqual(o.filled_size,2)
        b.advance(100.4)
        self.assertEqual(o.status,'CANCELLED')
        self.assertEqual(float(b.reserved_cash()),0)
        b.on_trade('up',.85,10,'SELL',100.5,'after')
        self.assertEqual(o.filled_size,2)

    def test_sell_reservation_blocks_second_exit_until_cancel_final(self):
        b=self.broker(cancel_latency_sec=.3);self.buy(b)
        maker=b.submit('SELL','up',5,.88,'GTC',True,100)
        second=b.submit('SELL','up',5,.84,now=100)
        self.assertEqual(second.rejection_reason,'insufficient_available_shares')
        b.cancel(maker.order_id,100.1)
        self.assertEqual(b.inventory('up')['available_quantity'],0)
        b.advance(100.4)
        self.assertEqual(b.inventory('up')['available_quantity'],5)

    def test_fok_no_partial_fill_when_depth_short(self):
        b=self.broker();b.on_book('up',book(asks=((.86,3),)))
        o=b.submit('BUY','up',5,.86,now=100)
        self.assertEqual(o.filled_size,0)
        self.assertEqual(o.status,'CLOSED_UNFILLED')

    def test_fak_partial_fill_has_fee_and_no_resting_reservation(self):
        b=self.broker();b.on_book('up',book(asks=((.86,3),)))
        o=b.submit('BUY','up',5,.86,'FAK',now=100)
        self.assertEqual(o.filled_size,3)
        self.assertEqual(o.status,'CANCELLED')
        self.assertEqual(float(b.reserved_cash()),0)
        self.assertEqual(b.inventory('up')['quantity'],3)

    def test_multiple_takers_do_not_reuse_same_visible_liquidity(self):
        b=self.broker();b.on_book('up',book(asks=((.86,5),)))
        self.buy(b)
        second=b.submit('BUY','up',5,.86,now=100)
        self.assertEqual(second.filled_size,0)
        self.assertEqual(b.inventory('up')['quantity'],5)

    def test_same_level_two_orders_share_queue_and_market_trade_volume(self):
        b=self.broker()
        first=b.submit('BUY','up',5,.84,'GTC',True,100)
        second=b.submit('BUY','up',5,.84,'GTC',True,100)
        b.on_trade('up',.84,16,'SELL',100.1,'sixteen')
        self.assertEqual(first.filled_size,5)
        self.assertEqual(second.filled_size,1)

    def test_net_realized_matches_cash_round_trip_fees_not_double_charged(self):
        b=self.broker();self.buy(b)
        b.on_book('up',book(bids=((.92,10),),asks=((.93,10),),ts=100.2))
        sold=b.submit('SELL','up',5,.92,now=100.2)
        self.assertTrue(sold.terminal)
        fees=.04214+.02576
        self.assertAlmostEqual(b.cash-236.006313,.3-fees)
        self.assertAlmostEqual(float(b.realized),.3-fees)
        self.assertEqual(b.inventory('up')['quantity'],0)

    def test_partial_sell_cost_basis_released_once(self):
        b=self.broker();self.buy(b,qty=10)
        b.on_book('up',book(bids=((.92,5),),asks=((.93,10),),ts=100.2))
        b.submit('SELL','up',10,.92,'FAK',now=100.2)
        self.assertEqual(b.inventory('up')['quantity'],5)
        self.assertAlmostEqual(b.inventory('up')['cost_usd'],4.3)
        self.assertAlmostEqual(b.inventory('up')['entry_fees_usd'],.04214)

    def test_settlement_is_binary_idempotent_and_charges_no_redeem_fee(self):
        b=self.broker();self.buy(b)
        fills=b.settle('up',1,101,'resolved')
        self.assertEqual(len(fills),1)
        self.assertEqual(fills[0]['fee_usd'],0)
        self.assertAlmostEqual(float(b.realized),5-4.34214)
        self.assertEqual(b.settle('up',1,102,'same-again'),[])
        self.assertEqual(b.submit('BUY','up',5,.86,now=102).rejection_reason,'market_already_settled')
        with self.assertRaises(ValueError):b.settle('other',.5,102,'not-official')

    def test_losing_settlement_releases_cost_and_fees_exactly(self):
        b=self.broker();self.buy(b)
        b.settle('up',0,101,'lose')
        self.assertAlmostEqual(float(b.realized),-4.34214)
        self.assertEqual(b.inventory('up')['quantity'],0)

    def test_stale_book_fails_at_actual_submission_not_request_time(self):
        b=PaperBroker(100,FeeSchedule(.07),submission_latency_sec=2)
        b.on_book('up',book())
        o=b.submit('BUY','up',5,.86,now=100)
        b.advance(102)
        self.assertEqual(o.rejection_reason,'book_stale_or_unavailable')

    def test_delayed_activation_cannot_fill_after_gtd_expired(self):
        b=PaperBroker(100,FeeSchedule(.07),submission_latency_sec=.1)
        b.on_book('up',book())
        o=b.submit('BUY','up',5,.86,'GTD',now=100,expiration=100.5)
        b.on_book('up',book(ts=101))
        b.advance(101)
        self.assertEqual(o.status,'EXPIRED')
        self.assertEqual(o.filled_size,0)
        self.assertEqual(b.cash,100)

    def test_delayed_activation_cannot_fill_after_cancel_final(self):
        b=PaperBroker(100,FeeSchedule(.07),submission_latency_sec=.1,cancel_latency_sec=.1)
        b.on_book('up',book())
        o=b.submit('BUY','up',5,.86,'GTC',now=100)
        b.cancel(o.order_id,100.05)
        b.on_book('up',book(ts=101))
        b.advance(101)
        self.assertEqual(o.status,'CANCELLED')
        self.assertEqual(o.filled_size,0)
        self.assertEqual(b.cash,100)

    def test_restart_preserves_pending_cancel_queue_fills_and_dedup(self):
        b=self.broker(cancel_latency_sec=.3)
        o=b.submit('BUY','up',5,.84,'GTC',True,100)
        b.on_trade('up',.84,11,'SELL',100.1,'one')
        b.cancel(o.order_id,100.15)
        state=json.loads(json.dumps(b.snapshot()))
        restored=PaperBroker.from_snapshot(state)
        self.assertEqual(restored.snapshot(),state)
        restored.on_trade('up',.84,11,'SELL',100.1,'one')
        self.assertEqual(restored.inventory('up')['quantity'],1)
        restored.on_trade('up',.84,2,'SELL',100.2,'two')
        self.assertEqual(restored.inventory('up')['quantity'],3)
        restored.advance(100.5)
        self.assertEqual(restored.get_order(o.order_id).status,'CANCELLED')
        self.assertEqual(len(restored.drain_fills()),2)

    def test_out_of_order_trade_does_not_rewind_or_create_fill(self):
        b=self.broker()
        o=b.submit('BUY','up',5,.85,'GTC',True,100)
        b.on_trade('up',.86,1,'BUY',100.2,'new')
        b.on_trade('up',.85,5,'SELL',100.1,'old')
        self.assertEqual(o.filled_size,0)
        self.assertFalse(b.snapshot()['simulation_coverage_complete'])


if __name__=='__main__':unittest.main()
