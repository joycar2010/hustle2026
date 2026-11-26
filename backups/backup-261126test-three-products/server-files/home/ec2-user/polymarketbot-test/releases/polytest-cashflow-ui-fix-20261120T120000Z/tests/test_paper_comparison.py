from dataclasses import replace
import json
import gzip
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.book import BookLevel,TopOfBook
from bot.markets import LiveMarket
from bot.paper_comparison import PaperComparison,PaperComparisonConfig
from bot.paper_public_runner import PublicTwapFeed,PublicRecorder,AsyncPublicRecorder,official_winner,verify_metadata


def book(now,bid=.84,ask=.85,depth=100.):
    return TopOfBook(bid,depth,ask,depth,(BookLevel(bid,depth),),(BookLevel(ask,depth),),now)


def signal(now):
    return {'available':True,'source':'chainlink_rtds_twap','window_sec':60,'source_ts':now,
            'anchor_verified':True,'price':10020.,'anchor':10000.}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        # Keep legacy unit fixtures deterministic; the deployed Paper public
        # config explicitly enables the adaptive band below.
        self.cfg=replace(PaperComparisonConfig(),confirm_checks=1,dynamic_entry_bounds_enabled=False)
        self.experiment=PaperComparison(self.cfg,self.temp.name,now=900.)
        self.addCleanup(lambda:self.experiment.close() if self.experiment else None)
        self.market=LiveMarket('condition','btc-updown-5m-700','up','down',700.,1000.,.01,False)
        self.experiment.add_market(self.market,{'feeSchedule':{'rate':.07,'exponent':1,'takerOnly':True},
                                               '_verified_twap_seconds':60},now=900.)

    def step(self,now,**kwargs):
        self.experiment.process('condition',{'up':book(now),'down':book(now,.14,.15)},signal(now),now=now,**kwargs)

    def test_dynamic_pair_band_uses_recent_040_061_quotes_and_never_restores_old_floor(self):
        # The requested initial Paper anchor is the latest pair of asks, not
        # the production .84-.90 range.  A low quote must therefore remain a
        # low quote all the way through order submission.
        self.experiment.cfg=replace(self.experiment.cfg,dynamic_entry_bounds_enabled=True)
        stamp=900.
        up=book(stamp,bid=.60,ask=.61)
        down=book(stamp,bid=.39,ask=.40)
        self.experiment.books.update(up=up,down=down)
        candidate,reason=self.experiment._base(self.experiment.markets['condition'],signal(stamp),stamp)
        self.assertIsNone(reason)
        self.assertAlmostEqual(candidate['entry_price_low'],.40)
        self.assertAlmostEqual(candidate['entry_price_high'],.61)
        sized,size_reason=self.experiment._budget_size('BASELINE',self.experiment.markets['condition'],candidate,stamp)
        self.assertIsNone(size_reason)
        self.experiment._submit_entry('BASELINE',self.experiment.markets['condition'],candidate,sized,stamp)
        order=next(iter(self.experiment.brokers['BASELINE'].orders.values()))
        self.assertLess(float(order.limit_price),.84)
        self.assertAlmostEqual(float(order.limit_price),.60)

    def test_dynamic_band_waits_for_a_fresh_pair_when_one_side_is_missing(self):
        self.experiment.cfg=replace(self.experiment.cfg,dynamic_entry_bounds_enabled=True)
        stamp=900.
        self.experiment.books['up']=book(stamp,bid=.39,ask=.40)
        low,high,source=self.experiment._entry_price_bounds(self.market,stamp)
        self.assertEqual(source,'pair_unavailable')
        self.assertIsNone(low)
        self.assertIsNone(high)

    def test_fast_pair_move_expands_lagged_band_instead_of_rejecting_both_sides(self):
        self.experiment.cfg=replace(self.experiment.cfg,dynamic_entry_bounds_enabled=True)
        self.experiment.books.update(up=book(900.,bid=.39,ask=.40),down=book(900.,bid=.60,ask=.61))
        self.experiment._entry_price_bounds(self.market,900.)
        self.experiment.books.update(up=book(901.,bid=.06,ask=.07),down=book(901.,bid=.93,ask=.94))
        low,high,_=self.experiment._entry_price_bounds(self.market,901.)
        self.assertLessEqual(low,.07)
        self.assertGreaterEqual(high,.94)

    def test_cached_dynamic_band_does_not_trade_when_opposite_quote_goes_stale(self):
        self.experiment.cfg=replace(self.experiment.cfg,dynamic_entry_bounds_enabled=True)
        stamp=900.
        self.experiment.books.update(up=book(stamp,bid=.60,ask=.61),down=book(stamp,bid=.39,ask=.40))
        first=self.experiment._entry_price_bounds(self.market,stamp)
        self.assertEqual(first[2],'recent_pair_median')
        # The selected UP quote is fresh, but the opposite DOWN quote is not.
        self.experiment.books['up']=book(stamp+2.,bid=.60,ask=.61)
        self.experiment.books['down']=book(stamp,bid=.39,ask=.40)
        self.assertEqual(self.experiment._entry_price_bounds(self.market,stamp+2.)[2],'pair_unavailable')

    def test_baseline_fee_headroom_gate_is_audited(self):
        exp=self.experiment
        exp.cfg=replace(self.cfg,baseline_min_net_edge_per_share=.99)
        stamp=900.;exp.books.update(up=book(stamp),down=book(stamp,.14,.15))
        candidate,reason=exp._base(exp.markets['condition'],signal(stamp),stamp)
        self.assertIsNone(reason)
        sized,size_reason=exp._budget_size('BASELINE',exp.markets['condition'],candidate,stamp)
        self.assertIsNone(sized)
        self.assertEqual(size_reason,'PAPER_NET_EDGE_BELOW_MIN')
        self.assertEqual(exp.groups['BASELINE']['edge_rejects'],1)

    def test_baseline_early_reversal_exit_does_not_wait_for_old_window(self):
        exp=self.experiment;exp.cfg=replace(self.cfg,baseline_reversal_held_bid_drawdown=.10)
        broker=exp.brokers['BASELINE']
        stamp=700.;broker.on_book('up',book(stamp,bid=.80,ask=.81))
        order=broker.submit('BUY','up',5.,.81,kind='FOK',now=stamp)
        broker.advance(stamp+.2);exp._collect('BASELINE')
        self.assertEqual(broker.inventory('up')['quantity'],5.)
        # Market has 300 seconds remaining, beyond the old 180s reversal
        # window. Two distinct fresh frames should nevertheless arm stop.
        exp.books['up']=book(stamp+1.,bid=.71,ask=.72)
        exp._exits('BASELINE',stamp+1.)
        self.assertNotIn('up',exp.groups['BASELINE']['pending'])
        exp.books['up']=book(stamp+2.,bid=.71,ask=.72)
        exp._exits('BASELINE',stamp+2.)
        pending=exp.groups['BASELINE']['pending']['up']
        self.assertEqual(pending['tier'],'stop')
        self.assertEqual(pending['phase'],'taker')
        self.assertEqual(exp.groups['BASELINE']['early_stop_triggers'],1)

    def test_common_events_and_costs_with_honest_probability_warmup(self):
        self.step(900.)
        exp=self.experiment
        self.assertEqual(exp.brokers['BASELINE'].markets['up'],exp.brokers['FILTERED'].markets['up'])
        self.assertEqual(exp.brokers['BASELINE'].submission_latency_sec,exp.brokers['FILTERED'].submission_latency_sec)
        self.assertEqual(exp.groups['BASELINE']['accepted'],1)
        self.assertEqual(exp.groups['FILTERED']['accepted'],0)
        self.assertIn('PROBABILITY_FEATURE_UNAVAILABLE',exp.groups['FILTERED']['blocked'])
        self.assertGreaterEqual(exp.groups['FILTERED']['warmup_shadow']['observations'],1)
        self.assertEqual(exp.groups['FILTERED']['fills'],0)
        summary=exp.summary(900.)
        self.assertFalse(summary['validation_complete'])
        self.assertEqual(summary['calibration']['settled_markets'],0)
        self.assertEqual(summary['groups']['FILTERED']['candidate_markets'],1)

    def test_maker_ttl_cancel_confirmation_then_fee_charged_residual_fallback(self):
        self.step(900.);self.step(900.2);self.step(903.1)
        exp=self.experiment;broker=exp.brokers['BASELINE']
        old=next(iter(broker.orders.values()))
        self.assertEqual(old.status,'CANCEL_PENDING')
        self.assertEqual(len(broker.orders),1)
        self.step(903.3)
        self.assertEqual(old.status,'CANCELLED')
        self.assertEqual(len(broker.orders),2)
        self.step(903.5)
        inv=broker.inventory('up')
        self.assertGreaterEqual(inv['quantity'],5.)
        self.assertGreater(inv['entry_fees_usd'],0.)
        self.assertLessEqual(inv['cost_usd']+inv['entry_fees_usd'],self.cfg.capital_usd*.02+1e-6)
        self.assertLess(exp.summary(903.5)['groups']['BASELINE']['fees_usd'],0.)

    def test_baseline_early_reversal_stop_does_not_wait_for_old_window(self):
        # Put an A/BASELINE inventory on the book, then make the bid fall by
        # more than the configured drawdown while the old 180s window is
        # still closed.  A must submit the emergency taker exit; FILTERED's
        # old window policy remains a separate comparison rule.
        self.experiment.cfg=replace(self.cfg, reversal_exit_window_sec=30.,
            baseline_early_reversal_enabled=True, baseline_reversal_held_bid_drawdown=.10,
            reversal_held_bid_drawdown=.30)
        self.step(900.);self.step(900.2);self.step(903.1);self.step(903.3);self.step(903.5)
        self.assertGreaterEqual(self.experiment.brokers['BASELINE'].inventory('up')['quantity'],5.)
        self.experiment.process('condition',{'up':book(904.,bid=.70,ask=.71),
            'down':book(904.,bid=.14,ask=.15)},signal(904.),now=904.)
        self.experiment.process('condition',{'up':book(904.2,bid=.70,ask=.71),
            'down':book(904.2,bid=.14,ask=.15)},signal(904.2),now=904.2)
        self.experiment.process('condition',{'up':book(904.1,bid=.70,ask=.71),
            'down':book(904.1,bid=.14,ask=.15)},signal(904.1),now=904.1)
        pending=self.experiment.groups['BASELINE']['pending'].get('up')
        self.assertIsNotNone(pending)
        self.assertEqual(pending['kind'],'exit')
        self.assertEqual(pending['tier'],'stop')
        self.assertEqual(pending['phase'],'taker')
        self.assertEqual(self.experiment.summary(904.1)['groups']['BASELINE']['early_stop_triggers'],1)

    def test_gap_blocks_fallback_and_preserves_coverage_evidence(self):
        self.step(900.);self.step(900.2)
        self.experiment.data_gap('TEST_LOST_EVENTS',now=902.)
        self.step(904.)
        broker=self.experiment.brokers['BASELINE']
        self.assertEqual(len(broker.orders),1)
        self.assertFalse(self.experiment.summary(904.)['groups']['BASELINE']['comparison_coverage_complete'])

    def test_restart_retains_orders_costs_elapsed_and_daily_denominator(self):
        self.step(900.);self.step(900.2);self.step(903.1);self.step(903.3);self.step(903.5)
        previous=self.experiment.summary(903.5)
        self.experiment.persist(903.5);self.experiment.close();self.experiment=None
        self.experiment=PaperComparison(self.cfg,self.temp.name,now=2000.)
        restored=self.experiment.summary(903.5)
        self.assertEqual(restored['started_at'],900.)
        self.assertEqual(restored['groups']['BASELINE']['cash_usd'],previous['groups']['BASELINE']['cash_usd'])
        self.assertEqual(restored['groups']['BASELINE']['fees_usd'],previous['groups']['BASELINE']['fees_usd'])
        self.assertEqual(restored['groups']['BASELINE']['daily_rows'],previous['groups']['BASELINE']['daily_rows'])
        with self.assertRaises(ValueError):PaperComparison(replace(self.cfg,capital_usd=1000.),self.temp.name,now=2000.)

    def test_restart_new_stream_sequence_does_not_inherit_old_local_cursor(self):
        self.step(900.)
        self.experiment.brokers['BASELINE']._book_sequence['up']=100000
        self.experiment.persist(900.);self.experiment.close();self.experiment=None
        self.experiment=PaperComparison(self.cfg,self.temp.name,now=900.3)
        event={'type':'book','is_delta':False,'token_id':'up','generation':1,'sequence':1,'received_ts':900.3,
               'bids':[{'price':.83,'size':7.}],'asks':[{'price':.85,'size':9.}]}
        trade={'type':'trade','token_id':'up','sequence':2,'received_ts':900.31,
               'event_id':'new-stream-print','price':.84,'size':1.,'side':'SELL'}
        self.experiment.process('condition',{},signal(900.4),events=[event,trade],now=900.4)
        self.assertEqual(self.experiment.brokers['BASELINE'].books['up'].best_bid,.83)
        self.assertEqual(self.experiment.event_count,1)
        self.assertIn('trade:up:new-stream-print',self.experiment.brokers['BASELINE']._seen)

    def test_deadline_blocks_new_entry_and_pending_maker_fallback(self):
        self.experiment.cfg=replace(self.cfg,duration_hours=.0005,validation_after_hours=.0001)
        self.step(900.);self.step(900.2);self.step(903.1);self.step(903.3)
        self.assertEqual(len(self.experiment.brokers['BASELINE'].orders),1)
        summary=self.experiment.summary(904.)
        self.assertEqual(summary['experiment_state'],'DRAINING')
        self.assertFalse(summary['validation_complete'])

    def test_official_settlement_is_idempotent_and_trains_only_recorded_windows(self):
        for i in range(12):self.step(900.+i)
        exp=self.experiment
        self.assertEqual(exp.model.progress()['observed_markets'],1)
        with self.assertRaises(ValueError):exp.resolve('condition','UP',now=999.)
        exp.resolve('condition','UP',now=1001.)
        first=exp.summary(1001.)
        exp.resolve('condition','UP',now=1002.)
        second=exp.summary(1002.)
        self.assertEqual(first['groups']['BASELINE']['cash_usd'],second['groups']['BASELINE']['cash_usd'])
        self.assertEqual(second['calibration']['settled_markets'],1)
        self.assertGreater(second['groups']['BASELINE']['net_pnl_usd'],0.)
        self.assertEqual(second['groups']['BASELINE']['open_positions_count'],0)

    def test_settled_windows_prune_depth_but_keep_audit_and_unresolved_inventory_after_restart(self):
        exp=self.experiment
        markets=[self.market,LiveMarket('second','second-slug','second-up','second-down',1000.,1300.,.01,False),
                 LiveMarket('held','held-slug','held-up','held-down',1300.,1600.,.01,False)]
        for index,market in enumerate(markets):
            stamp=900.+index*300.
            if index:exp.add_market(market,{'feeSchedule':{'rate':.07,'exponent':1,'takerOnly':True},
                '_verified_twap_seconds':60},now=stamp)
            for token in (market.up_token,market.down_token):
                exp.books[token]=book(stamp)
                exp._stream_levels[token]={'bids':{.84:100.},'asks':{.85:100.},'generation':1}
                for broker in exp.brokers.values():broker.on_book(token,book(stamp))
            for lane,broker in exp.brokers.items():
                broker.submit('BUY',market.up_token,5.,.85,kind='FOK',now=stamp)
                broker.advance(stamp+.2);exp._collect(lane)
            if index<2:exp.resolve(market.condition_id,'UP',now=market.end_ts+1.)
        for market in markets[:2]:
            self.assertIn(market.condition_id,exp.markets)
            for token in (market.up_token,market.down_token):
                self.assertNotIn(token,exp.books);self.assertNotIn(token,exp._stream_levels)
                for broker in exp.brokers.values():
                    self.assertNotIn(token,broker.books)
                    self.assertNotIn(token,broker._book_consumed)
                    self.assertIn(token,broker._settled)
        self.assertFalse(exp._prune_settled_cache(exp.markets['held']))
        self.assertIn('held-up',exp.books)
        exp.process('held',{'up':book(1500.1)}, {'available':False,'reason':'TEST'},now=1500.2,
            events=[{'type':'book','token_id':'up','received_ts':1500.1,'sequence':999,'generation':1,
                     'bids':[{'price':.84,'size':100.}],'asks':[{'price':.85,'size':100.}]}])
        self.assertNotIn('up',exp.books)
        self.assertNotIn('up',exp.brokers['BASELINE'].books)
        before=exp.summary(1500.2);exp.persist(1500.2)
        fill_count=exp.db.execute('SELECT count(*) FROM fills').fetchone()[0]
        exp.close();self.experiment=None
        self.experiment=PaperComparison(self.cfg,self.temp.name,now=1500.3)
        restored=self.experiment
        self.assertEqual(restored.started_at,900.)
        self.assertEqual(restored.cfg.digest(),self.cfg.digest())
        self.assertEqual(restored.db.execute('SELECT count(*) FROM fills').fetchone()[0],fill_count)
        for lane,broker in restored.brokers.items():
            self.assertEqual(set(broker.books),{'held-up','held-down'})
            self.assertEqual(len(broker.orders),3)
            self.assertEqual(broker.inventory('held-up')['quantity'],5.)
            self.assertEqual(restored.summary(1500.2)['groups'][lane]['cash_usd'],before['groups'][lane]['cash_usd'])

    def test_event_order_book_precedes_trade_and_tail_snapshot_is_not_backdated(self):
        self.step(900.)
        event={'type':'book','token_id':'up','received_ts':900.11,'sequence':1,
               'bids':[{'price':.84,'size':2.}],'asks':[{'price':.85,'size':100.}]}
        trade={'type':'trade','token_id':'up','price':.84,'size':3.,'side':'SELL',
               'received_ts':900.12,'event_id':'print1','sequence':2}
        self.experiment.process('condition',{'up':book(900.2,.80,.81)},signal(900.2),
                                events=[event,trade],now=900.2)
        self.assertAlmostEqual(self.experiment.brokers['BASELINE'].inventory('up')['quantity'],1.)
        self.assertAlmostEqual(self.experiment.books['up'].fetched_at,900.2)
        self.experiment.process('condition',{'up':book(900.2,.80,.81)},signal(902.),now=902.)
        self.assertEqual(self.experiment.brokers['BASELINE'].books['up'].fetched_at,900.2)

    def test_compact_books_coalesce_without_losing_any_trade_print(self):
        events=[{'type':'book','token_id':'up','received_ts':800.,'sequence':1,'generation':1,
            'bids':[{'price':.84,'size':100.}],'asks':[{'price':.85,'size':100.}]}]
        for i in range(2000):
            events.append({'type':'book','is_delta':True,'token_id':'up','generation':1,'sequence':i*2+2,
                'received_ts':800.001+i*.001,'changes':[{'side':'BUY','price':.84,'size':100.+i%4}]})
            events.append({'type':'trade','token_id':'up','event_id':f't{i}','received_ts':800.001+i*.001,
                'price':.84,'size':.01,'side':'SELL','sequence':i*2+3})
        self.experiment.process('condition',{},signal(802.1),events=events,now=802.1)
        self.assertEqual(self.experiment.event_count,2000)
        self.assertEqual(self.experiment.last_health['replayed_book_events'],1)
        self.assertEqual(self.experiment.last_health['coalesced_book_events'],2000)
        self.assertEqual(self.experiment.books['up'].best_bid,.84)
        self.assertEqual(self.experiment.books['up'].bid_size,103.)

    def test_compact_activation_barrier_retains_intervening_crossed_book(self):
        self.step(900.)
        initial={'type':'book','token_id':'up','generation':1,'sequence':1,'received_ts':900.05,
            'bids':[{'price':.84,'size':2.}],'asks':[{'price':.85,'size':100.}]}
        crossed={'type':'book','is_delta':True,'token_id':'up','generation':1,'sequence':2,'received_ts':900.11,
            'changes':[{'side':'SELL','price':.85,'size':0.},{'side':'SELL','price':.83,'size':100.}]}
        restored={**crossed,'sequence':3,'received_ts':900.12,
            'changes':[{'side':'SELL','price':.83,'size':0.},{'side':'SELL','price':.85,'size':100.}]}
        trade={'type':'trade','token_id':'up','event_id':'print','received_ts':900.13,'price':.84,'size':10.,'side':'SELL','sequence':4}
        self.experiment.process('condition',{},signal(900.2),events=[initial,crossed,restored,trade],now=900.2)
        broker=self.experiment.brokers['BASELINE'];first=next(iter(broker.orders.values()))
        self.assertEqual(first.status,'REJECTED')
        self.assertEqual(first.rejection_reason,'post_only_would_cross')
        self.assertEqual(broker.inventory('up')['quantity'],0.)

    def test_explicit_invalid_book_blocks_pending_taker_and_new_entries_until_resync(self):
        exp=self.experiment;broker=exp.brokers['BASELINE']
        broker.on_book('up',book(900.))
        pending=broker.submit('BUY','up',5.,.85,kind='FOK',now=900.)
        exp.books['up']=book(900.)
        exp.process('condition',{'up':book(900.19)},signal(900.2),now=900.2,
            stream_health={'clob':{'books':{'up':{'snapshot_valid':False}}}})
        self.assertEqual(pending.status,'REJECTED')
        self.assertEqual(pending.rejection_reason,'book_stale_or_unavailable')
        self.assertEqual(broker.inventory('up')['quantity'],0.)
        self.assertNotIn('up',exp.books)
        self.assertNotIn('up',broker.books)
        self.assertEqual(exp.groups['BASELINE']['accepted'],0)
        self.assertNotIn('coverage_block',exp.groups['BASELINE'])
        full={'type':'book','is_delta':False,'token_id':'up','received_ts':900.3,'generation':1,'sequence':1,
            'bids':[{'price':.84,'size':100.}],'asks':[{'price':.85,'size':100.}]}
        exp.process('condition',{}, {'available':False,'reason':'TEST_ENTRIES_DISABLED'},now=900.31,
            events=[full],stream_health={'clob':{'books':{'up':{'snapshot_valid':True}}}})
        recovered=broker.submit('BUY','up',5.,.85,kind='FOK',now=900.31)
        broker.advance(900.5)
        self.assertEqual(recovered.status,'FILLED')
        self.assertEqual(broker.inventory('up')['quantity'],5.)

    def test_invalid_book_keeps_real_trade_evidence_for_existing_resting_maker(self):
        exp=self.experiment;broker=exp.brokers['BASELINE']
        broker.on_book('up',book(900.,depth=2.))
        maker=broker.submit('BUY','up',5.,.84,kind='GTC',post_only=True,now=900.)
        broker.advance(900.11)
        self.assertEqual(maker.status,'OPEN')
        exp.process('condition',{}, {'available':False,'reason':'TEST'},now=900.3,
            events=[{'type':'trade','token_id':'up','price':.84,'size':3.,'side':'SELL',
                     'received_ts':900.2,'event_id':'real-print-during-resync'}],
            stream_health={'clob':{'books':{'up':{'snapshot_valid':False}}}})
        self.assertEqual(broker.inventory('up')['quantity'],1.)
        self.assertEqual(maker.status,'OPEN')
        self.assertNotIn('up',broker.books)
        self.assertNotIn('coverage_block',exp.groups['BASELINE'])


class PublicSourceTests(unittest.TestCase):
    def test_async_journal_backlog_is_bounded_and_reported_as_incomplete(self):
        release=threading.Event()
        class SlowWriter:
            def __init__(self,directory):self.rows=[]
            def write(self,event):release.wait(2.);self.rows.append(event)
            def close(self):pass
        recorder=AsyncPublicRecorder('unused',max_events=2,writer_factory=SlowWriter)
        try:
            self.assertTrue(recorder.submit_batch([{'type':'trade'},{'type':'trade'}]))
            self.assertFalse(recorder.write({'type':'trade'}))
            self.assertFalse(recorder.health()['coverage_complete'])
            self.assertLessEqual(recorder.health()['queued_events'],2)
        finally:release.set();recorder.close()
        self.assertEqual(len(recorder.writer.rows),2)

    def test_twap_subscription_does_not_suppress_updates_with_server_symbol_filter(self):
        feed=PublicTwapFeed(PaperComparisonConfig())
        self.assertNotIn('filters',feed.subscription()['subscriptions'][0])
        self.assertFalse(feed.ingest({'topic':'crypto_prices_twap_sixty','payload':{
            'symbol':'eth/usd','window_s':60,'timestamp':1000.,'value':2000.}},received_at=1001.))
        self.assertTrue(feed.ingest({'topic':'crypto_prices_twap_sixty','type':'update','payload':{
            'symbol':'btc/usd','window_s':60,'timestamp':1000.,'value':10000.}},received_at=1001.))
    def test_recorder_keeps_first_full_book_then_replayable_deletions_and_trades(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder=PublicRecorder(directory)
            first={'type':'book','token_id':'up','received_ts':1000.,'sequence':1,
                'bids':[{'price':.84,'size':4.}],'asks':[{'price':.85,'size':5.}]}
            recorder.write(first)
            recorder.write({**first,'sequence':2,'received_ts':1001.,'bids':[]})
            recorder.write({'type':'trade','token_id':'up','received_ts':1001.1,'price':.84,'size':4.,'side':'SELL','event_id':'x'})
            recorder.close()
            files=list(Path(directory).glob('*.jsonl.gz'))
            with gzip.open(files[0],'rt',encoding='utf-8') as stream:rows=[json.loads(line) for line in stream]
            self.assertEqual(rows[0]['type'],'book')
            self.assertEqual(rows[1]['type'],'book_delta')
            self.assertEqual(rows[1]['bids'],[{'price':.84,'size':0.}])
            self.assertEqual(rows[2]['event_id'],'x')

    def test_twap60_history_ingest_rejects_wrong_window_and_stale_source(self):
        feed=PublicTwapFeed(PaperComparisonConfig())
        base={'topic':'crypto_prices_twap_sixty','payload':{'symbol':'btc/usd','window_s':60,
            'data':[{'timestamp':1000.,'value':10000.},{'timestamp':1001.,'value':10001.}]}}
        self.assertTrue(feed.ingest(base,received_at=1001.))
        self.assertEqual(len(feed.samples),2)
        base['payload']['window_s']=30
        self.assertFalse(feed.ingest(base,received_at=1001.))
        market=LiveMarket('m','s','up','down',1000.,1300.,.01,False)
        feed.anchors['m']={'price':10000.,'source':'chainlink','source_ts':1000.,'window_sec':60,'verified':True}
        self.assertFalse(feed.signal(market,now=1007.)['available'])
        with patch('bot.paper_public_runner.requests.get',side_effect=AssertionError('decision loop did REST')):
            self.assertTrue(feed.signal(market,now=1002.)['available'])
            feed.anchors.clear()
            self.assertFalse(feed.signal(market,now=1002.)['available'])

    def test_official_contract_window_and_binary_resolution_required(self):
        self.assertEqual(verify_metadata({'description':'Chainlink TWAP 60-second average'},60)['_verified_twap_seconds'],60)
        self.assertEqual(verify_metadata({'resolutionSource':'https://chainlink.test/twap/btc-usd/60s'},60)['_verified_twap_seconds'],60)
        with self.assertRaises(ValueError):verify_metadata({'description':'Chainlink TWAP 30-second average'},60)
        self.assertIsNone(official_winner({'closed':False,'outcomes':['Up','Down'],'outcomePrices':['1','0']}))
        self.assertIsNone(official_winner({'closed':True,'outcomes':['Up','Down'],'outcomePrices':['.99','.01']}))
        self.assertEqual(official_winner({'closed':True,'outcomes':['Up','Down'],'outcomePrices':['1','0']}),'UP')


if __name__=='__main__':unittest.main()
