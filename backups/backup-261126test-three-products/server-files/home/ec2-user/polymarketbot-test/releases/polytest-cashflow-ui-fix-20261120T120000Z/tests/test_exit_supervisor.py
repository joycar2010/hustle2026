from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import threading
import time
from types import SimpleNamespace
import unittest
from bot.exit_supervisor import IndependentExitSupervisor, PriorityOrderGate
from bot.clob_stream import ClobStreams
from bot.book import TopOfBook, BookLevel


class Streams:
    def __init__(self):
        self.books={'up':object(),'down':object()}
        self.rest={}
        self.rest_calls=[]
        self.user=True
        self.market=True
        self.received_at=100.
    def subscribe(self,*args): pass
    def start(self): pass
    def stop(self): pass
    def latest_book(self,token,**kwargs): return self.books.get(token)
    def snapshot(self,token,**kwargs):
        value=self.latest_book(token)
        if value is not None:
            return SimpleNamespace(book=value,source='market_ws',event_ts=100.,received_ts=100.)
        return self.rest.get(token) if kwargs.get('allow_rest') else None
    def refresh_rest(self,token,condition):
        self.rest_calls.append((token,condition))
        self.rest[token]=SimpleNamespace(book=object(),source='rest',event_ts=100.,received_ts=100.)
        return self.rest[token]
    def health(self): return {'user':{'connected':self.user,'received_at':self.received_at},
                              'market':{'connected':self.market,'received_at':self.received_at}}
    def wait(self,revision,timeout):
        time.sleep(min(.01,timeout));return revision+1


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.stream=Streams()
        self.calls=[]
        self.market=SimpleNamespace(condition_id='market',up_token='up',down_token='down',end_ts=200.)
        self.sup=IndependentExitSupervisor(self.stream,execute=lambda *x:self.calls.append(x) or True,
            reconcile=lambda m:None,urgent_check=lambda *x:False,now=lambda:100.)
        self.sup.update_market(self.market)

    def test_missing_auth_blocks_entries_without_fabricated_exit_prices(self):
        self.stream.user=False
        self.stream.books={}
        self.sup.tick();self.sup.execute_once()
        self.assertEqual(self.calls,[])
        self.assertIsNotNone(self.sup.entry_block_reason())

    def test_missing_unheld_side_does_not_block_known_side_exit_callback(self):
        self.stream.books.pop('down')
        self.sup.tick();self.sup.execute_once()
        self.assertEqual(len(self.calls),1)
        self.assertIsNone(self.calls[0][2])
        self.assertIsNotNone(self.sup.entry_block_reason())

    def test_fresh_books_and_auth_allow_entry(self):
        self.sup.tick()
        self.assertIsNone(self.sup.entry_block_reason())

    def test_rest_recovery_exits_without_reopening_buy_admission(self):
        self.stream.books={};self.stream.market=False
        self.assertEqual(self.sup.rest_refresh_once(),2)
        self.sup.tick();self.sup.execute_once()
        self.assertEqual(len(self.calls),1)
        self.assertIs(self.calls[0][1],self.stream.rest['up'].book)
        self.assertIsNotNone(self.sup.entry_block_reason())
        self.assertEqual(self.sup.health()['exit_book_sources']['up']['source'],'rest')

    def test_cache_only_exit_read_and_execution_never_perform_rest(self):
        self.stream.books={}
        self.sup.tick();self.sup.exit_book('up');self.sup.execute_once()
        self.assertEqual(self.stream.rest_calls,[])

    def test_returning_ws_is_preferred_and_stops_rest_recovery(self):
        self.stream.books={};self.sup.rest_refresh_once()
        fresh=object();self.stream.books={'up':fresh,'down':object()}
        self.assertIs(self.sup.exit_book('up'),fresh)
        self.assertEqual(self.sup.health()['exit_book_sources']['up']['source'],'market_ws')
        self.assertEqual(self.sup.rest_refresh_once(),0)
        self.assertEqual(len(self.stream.rest_calls),2)

    def test_current_rest_observation_is_not_polled_again_immediately(self):
        self.stream.books={}
        self.sup.rest_refresh_once();self.sup.rest_refresh_once()
        self.assertEqual(len(self.stream.rest_calls),2)

    def test_disconnected_or_stale_ws_never_grants_entry_from_cached_books(self):
        self.stream.market=False;self.sup.tick()
        self.assertIsNotNone(self.sup.entry_block_reason())
        self.stream.market=True;self.stream.received_at=74.;self.sup.tick()
        self.assertIsNotNone(self.sup.entry_block_reason())

    def test_recovery_exception_is_redacted_and_other_token_still_recovers(self):
        self.stream.books={}
        original=self.stream.refresh_rest
        def refresh(token,condition):
            if token=='down':raise ValueError('secret=url?key=private')
            return original(token,condition)
        self.stream.refresh_rest=refresh
        self.assertEqual(self.sup.rest_refresh_once(),1)
        self.assertEqual(self.sup.health()['rest_error_type'],'ValueError')
        self.assertNotIn('private',str(self.sup.health()))

    def test_rest_network_stall_does_not_block_watch_or_known_book_exit(self):
        entered=threading.Event();release=threading.Event();exited=threading.Event()
        self.stream.books.pop('down')
        def slow_refresh(token,condition):entered.set();release.wait(1.)
        self.stream.refresh_rest=slow_refresh
        self.sup.execute=lambda *args:exited.set() or True
        self.sup.start()
        try:
            self.assertTrue(entered.wait(.5))
            self.assertTrue(exited.wait(.5))
            self.assertIsNotNone(self.sup.health().get('last_watch_at'))
        finally:
            release.set();self.sup.stop()

    def test_expired_market_is_not_rest_recovered_or_entry_ready(self):
        self.market.end_ts=99.;self.stream.books={}
        self.assertEqual(self.sup.rest_refresh_once(),0)
        self.sup.tick()
        self.assertIsNotNone(self.sup.entry_block_reason())

    def test_real_cache_rejects_expired_rest_and_recovers_to_ws_source(self):
        clock=[100.]
        streams=ClobStreams(clock=lambda:clock[0])
        sup=IndependentExitSupervisor(streams,execute=lambda *x:True,reconcile=lambda m:None,
            urgent_check=lambda *x:False,authenticated=False,now=lambda:clock[0])
        sup.update_market(self.market)
        book=TopOfBook(.8,10.,.81,10.,(BookLevel(.8,10.),),(BookLevel(.81,10.),),fetched_at=100.)
        streams.refresh_rest('up','market',loader=lambda *args:book)
        self.assertIs(sup.exit_book('up'),book)
        self.assertEqual(sup.health()['exit_book_sources']['up']['source'],'rest')
        sup.tick();self.assertIsNotNone(sup.entry_block_reason())
        clock[0]=101.6
        self.assertIsNone(sup.exit_book('up'))
        streams._mark_connected('market')
        streams.ingest_market(dict(event_type='book',asset_id='up',market='market',timestamp=101.6,
            bids=[{'price':'.82','size':'10'}],asks=[{'price':'.83','size':'10'}]))
        self.assertEqual(sup.exit_book('up').best_bid,.82)
        self.assertEqual(sup.health()['exit_book_sources']['up']['source'],'market_ws')

    def test_urgent_event_preempts_passive_wait_without_waiting_entry_lock(self):
        self.sup.urgent_check=lambda *args:True
        started=threading.Event();released=threading.Event()
        def entry():
            with self.sup.gate.entry() as allowed:
                self.assertTrue(allowed)
                started.set()
                self.sup.gate.urgent.wait(timeout=1.)
            released.set()
        thread=threading.Thread(target=entry)
        thread.start();self.assertTrue(started.wait(.5))
        self.sup.tick()
        self.assertTrue(released.wait(.5));thread.join()
        with self.sup.gate.entry() as allowed:self.assertFalse(allowed)

    def test_expired_market_is_never_sold_from_old_book(self):
        self.market.end_ts=99.
        self.sup.tick();self.sup.execute_once()
        self.assertEqual(self.calls,[])

    def test_rechecks_cached_book_after_order_lock(self):
        self.sup.tick();self.stream.books={}
        self.sup.execute_once()
        self.assertEqual(self.calls,[])

    def test_exit_runs_while_inventory_network_refresh_is_blocked(self):
        entered=threading.Event();release=threading.Event();exited=threading.Event()
        def reconcile(m):entered.set();release.wait(1.)
        self.sup.reconcile=reconcile
        self.sup.execute=lambda *args:exited.set() or True
        self.sup.start()
        try:
            self.assertTrue(entered.wait(.5))
            self.assertTrue(exited.wait(.5))
        finally:
            release.set();self.sup.stop()

    def test_order_writer_is_serialized(self):
        gate=PriorityOrderGate();inside=threading.Event();finished=threading.Event()
        def exit():
            with gate.exit():finished.set()
        with gate.entry():
            thread=threading.Thread(target=exit);thread.start()
            self.assertFalse(finished.wait(.03))
        self.assertTrue(finished.wait(.5));thread.join()


if __name__=='__main__':unittest.main()
