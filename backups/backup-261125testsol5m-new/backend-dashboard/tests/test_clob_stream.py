from pathlib import Path
import asyncio
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.book import TopOfBook, BookLevel
from bot.clob_stream import ClobStreams, BookSnapshot

NOW = 1794339000.
TOKEN, OTHER, MARKET = "111", "222", "0xmarket"
OWNER, OTHER_OWNER = "own-api-never-leave-memory", "another-api-never-leave-memory"
WALLET = "0x" + "11"*20


def stream(**kwargs):
    value = ClobStreams(clock=lambda: NOW, **kwargs)
    value.subscribe((TOKEN, OTHER), (MARKET,))
    return value


def book(token=TOKEN, ts=NOW, **kwargs):
    return dict(event_type="book", asset_id=token, market=MARKET,
        timestamp=str(int(ts*1000)), hash="book-"+token+str(ts),
        bids=kwargs.get("bids", [{"price": ".84", "size": "10"}, {"price": ".83", "size": "20"}]),
        asks=kwargs.get("asks", [{"price": ".85", "size": "12"}, {"price": ".86", "size": "30"}]))


def delta(price=".84", size="0", side="BUY", ts=NOW, **kwargs):
    return dict(event_type="price_change", market=MARKET, timestamp=str(int(ts*1000)),
                price_changes=[dict(asset_id=TOKEN, price=price, size=size, side=side, **kwargs)])


class MarketBookTests(unittest.TestCase):
    def test_default_ring_retains_throughput_and_wrapping_reports_a_gap(self):
        self.assertEqual(stream().health()['market_ring_capacity'], 4096)
        value = stream(ring_size=32)
        for index in range(40):
            value.ingest_market(book(ts=NOW-index/1000)) if index == 0 else value.ingest_market(
                dict(event_type="last_trade_price", asset_id=TOKEN, market=MARKET,
                    timestamp=str(int(NOW*1000)), price=".85", size=str(index), side="BUY",
                    transaction_hash="trade-"+str(index)))
        events, cursor = value.market_events(0)
        health = value.health()
        self.assertEqual(cursor, 40)
        self.assertEqual(len(events), 32)
        self.assertEqual(health['market_ring_dropped'], 8)
        self.assertEqual(health['market_oldest_sequence'], 9)

    def test_snapshot_is_sorted_and_carries_source_clock(self):
        value = stream()
        self.assertTrue(value.ingest_market(book(bids=[{"price": ".83", "size": "20"}, {"price": ".84", "size": "10"}])))
        snapshot = value.snapshot(TOKEN)
        self.assertEqual(snapshot.source, "market_ws")
        self.assertEqual(snapshot.event_ts, NOW)
        self.assertEqual(snapshot.received_ts, NOW)
        self.assertEqual(snapshot.book.best_bid, .84)
        self.assertEqual(snapshot.book.ask_size, 12.)

    def test_compact_delta_ring_does_not_duplicate_unchanged_depth(self):
        value=stream()
        value.ingest_market(book())
        value.ingest_market(delta(price='.835',size='7',best_bid='.84',best_ask='.85'))
        events,_=value.market_events()
        self.assertFalse(events[0]['is_delta'])
        self.assertTrue(events[1]['is_delta'])
        self.assertNotIn('bids',events[1])
        self.assertEqual(events[1]['changes'],[{'price':.835,'size':7.,'side':'BUY'}])
        events[1]['changes'][0]['size']=999
        self.assertEqual(value.market_events()[0][1]['changes'][0]['size'],7.)
        self.assertEqual(len(value.latest_book(TOKEN).bids),3)

    def test_legacy_full_event_opt_in_preserves_full_depth_contract(self):
        value=stream(compact_events=False)
        value.ingest_market(book());value.ingest_market(delta())
        event=value.market_events()[0][-1]
        self.assertFalse(event['is_delta'])
        self.assertEqual(event['bids'],[{'price':.83,'size':20.}])

    def test_rejected_source_timestamp_has_diagnostic_reason_without_payload(self):
        value=stream()
        self.assertFalse(value.ingest_market(book(ts=NOW-31)))
        health=value.health()['market']
        self.assertEqual(health['invalid_reasons'],{'source_older_than_30s':1})
        self.assertEqual(health['latest_ingress_lag_sec'],31.)

    def test_delta_removes_then_adds_depth_without_fabricating_size(self):
        value = stream()
        value.ingest_market(book())
        self.assertTrue(value.ingest_market(delta(best_bid=".83", best_ask=".85")))
        self.assertEqual(value.latest_book(TOKEN).best_bid, .83)
        value.ingest_market(delta(price=".835", size="7", best_bid=".835", best_ask=".85"))
        self.assertEqual(value.latest_book(TOKEN).bid_size, 7.)

    def test_batch_changes_are_applied_atomically_per_asset(self):
        value = stream()
        value.ingest_market(book())
        frame = delta()
        frame['price_changes'] = [
            dict(asset_id=TOKEN, side="BUY", price=".84", size="0", best_bid=".82", best_ask=".85"),
            dict(asset_id=TOKEN, side="BUY", price=".83", size="0", best_bid=".82", best_ask=".85"),
            dict(asset_id=TOKEN, side="BUY", price=".82", size="5", best_bid=".82", best_ask=".85")]
        self.assertTrue(value.ingest_market(frame))
        self.assertEqual(value.latest_book(TOKEN).best_bid, .82)

    def test_delta_before_snapshot_cannot_be_used(self):
        value = stream()
        self.assertFalse(value.ingest_market(delta()))
        self.assertIsNone(value.latest_book(TOKEN))
        self.assertTrue(value.health()['books'][TOKEN]['resync_required'])

    def test_out_of_order_snapshot_does_not_restore_removed_bid(self):
        value = stream()
        value.ingest_market(book(ts=NOW-1))
        value.ingest_market(delta(ts=NOW, best_bid=".83", best_ask=".85"))
        self.assertFalse(value.ingest_market(book(ts=NOW-.5)))
        self.assertEqual(value.latest_book(TOKEN).best_bid, .83)
        self.assertEqual(value.health()['market']['out_of_order'], 1)

    def test_duplicate_frame_does_not_double_notify_or_trade(self):
        value = stream()
        event = book()
        value.ingest_market(event)
        revision = value.revision
        self.assertFalse(value.ingest_market(event))
        self.assertEqual(value.revision, revision)
        self.assertEqual(value.health()['market']['duplicates'], 1)

    def test_sdk_camel_case_envelope_is_supported(self):
        value = stream()
        frame = book()
        frame['assetId'] = frame.pop('asset_id')
        frame['conditionId'] = frame.pop('market')
        frame.pop('event_type')
        self.assertTrue(value.ingest_market({'topic': 'market', 'type': 'book', 'payload': frame}))
        self.assertEqual(value.latest_book(TOKEN).best_ask, .85)

    def test_truncated_top_change_invalidates_depth_and_requests_resync(self):
        value = stream()
        value.ingest_market(book())
        value.ingest_market(dict(event_type="best_bid_ask", asset_id=TOKEN, market=MARKET,
            timestamp=NOW*1000, best_bid=".80", best_ask=".85"))
        self.assertIsNone(value.latest_book(TOKEN))
        self.assertTrue(value.health()['books'][TOKEN]['resync_required'])

    def test_unchanged_top_message_does_not_renew_full_book_age(self):
        value = stream()
        value.ingest_market(book(ts=NOW-2))
        value.ingest_market(dict(event_type="best_bid_ask", asset_id=TOKEN, market=MARKET,
            timestamp=NOW*1000, best_bid=".84", best_ask=".85"))
        self.assertIsNone(value.latest_book(TOKEN, max_age_sec=1.5))

    def test_best_mismatch_or_crossed_book_is_not_tradable(self):
        value = stream()
        value.ingest_market(book())
        value.ingest_market(delta(price=".86", size="3", best_bid=".86", best_ask=".85"))
        self.assertIsNone(value.latest_book(TOKEN))
        self.assertTrue(value.health()['books'][TOKEN]['resync_required'])

    def test_future_stale_and_missing_timestamp_frames_are_rejected(self):
        value = stream()
        for ts in (NOW+3, NOW-31): self.assertFalse(value.ingest_market(book(ts=ts)))
        frame=book(); frame.pop('timestamp')
        self.assertFalse(value.ingest_market(frame))
        self.assertIsNone(value.latest_book(TOKEN))

    def test_reconnect_invalidates_prior_generation_until_new_snapshot(self):
        value = stream()
        value._mark_connected('market')
        value.ingest_market(book())
        self.assertEqual(value.snapshot(TOKEN).generation, 1)
        value._mark_disconnected('market', ConnectionError('sensitive-url-never-log'))
        self.assertIsNone(value.snapshot(TOKEN))
        value._mark_connected('market')
        value.ingest_market(delta(size="11"))
        self.assertIsNone(value.snapshot(TOKEN))
        value.ingest_market(book())
        self.assertEqual(value.snapshot(TOKEN).generation, 2)
        self.assertNotIn('sensitive-url', json.dumps(value.health()))

    def test_rest_recovery_is_explicit_and_cannot_renew_ws_age(self):
        value = stream()
        value.ingest_market(book(ts=NOW-2))
        old_book = TopOfBook(.8, 1., .9, 2., fetched_at=NOW)
        result = value.refresh_rest(TOKEN, MARKET, loader=lambda host, token: old_book)
        self.assertEqual(result.source, 'rest')
        self.assertIsNone(value.snapshot(TOKEN))
        self.assertEqual(value.snapshot(TOKEN, allow_rest=True).source, 'rest')
        self.assertIsNone(value.latest_book(TOKEN))

    def test_removed_subscription_cannot_receive_old_book(self):
        value = stream()
        value.ingest_market(book())
        value.subscribe([OTHER], [MARKET])
        self.assertIsNone(value.snapshot(TOKEN))
        self.assertFalse(value.ingest_market(book()))

    def test_array_message_processes_all_tokens(self):
        value = stream()
        value.ingest_market([book(), book(token=OTHER)])
        self.assertIsNotNone(value.latest_book(TOKEN))
        self.assertIsNotNone(value.latest_book(OTHER))

    def test_book_ring_returns_deep_copies_for_counterfactual_consumers(self):
        value = stream()
        value.ingest_market(book())
        events, cursor=value.market_events()
        events[0]['bids'][0]['size']=999.
        second, _=value.market_events()
        self.assertEqual(second[0]['bids'][0]['size'], 10.)
        self.assertEqual(value.market_events(cursor)[0], [])

    def test_trade_events_have_aggressor_side_and_no_assumed_volume(self):
        value=stream()
        frame=dict(event_type='last_trade_price', market=MARKET, asset_id=TOKEN,
            timestamp=NOW*1000, price='.85', side='BUY')
        value.ingest_market(frame)
        event=value.market_events()[0][-1]
        self.assertEqual(event['type'], 'trade')
        self.assertEqual(event['side'], 'BUY')
        self.assertIsNone(event['size'])
        self.assertIsNone(value.latest_book(TOKEN))

    def test_tick_change_is_not_lost(self):
        value=stream()
        value.ingest_market(dict(event_type='tick_size_change', market=MARKET,
            asset_id=TOKEN, timestamp=NOW*1000, new_tick_size='.001'))
        self.assertEqual(value.market_events()[0][0]['tick_size'], .001)

    def test_ring_gap_is_visible(self):
        value=stream(ring_size=32)
        for i in range(40):
            value.ingest_market(dict(event_type='last_trade_price', asset_id=TOKEN,
                market=MARKET, timestamp=NOW*1000, price='.85', size=str(i+1), side='BUY'))
        self.assertEqual(len(value.market_events()[0]),32)
        self.assertEqual(value.health()['market_oldest_sequence'], 9)


def order(*, ts=NOW, matched='2', status='LIVE', **kwargs):
    return dict(event_type='order', type='UPDATE', market=MARKET, asset_id=TOKEN,
        id='own-order', owner=OWNER, order_owner=OWNER, original_size='5',
        size_matched=matched, price='.85', side='BUY', timestamp=ts*1000,
        status=status, **kwargs)


class UserEvidenceTests(unittest.TestCase):
    def value(self):
        return stream(api_key=OWNER,api_secret='private-secret-never-output',
                      api_passphrase='private-passphrase-never-output',owner_addresses=[WALLET])

    def test_order_cumulative_progress_and_terminal_state(self):
        value=self.value()
        value.ingest_user(order())
        value.ingest_user(order(matched='5',status='MATCHED'))
        event=value.user_events()[0][-1]
        self.assertEqual(event['size_matched'],5.)
        self.assertTrue(event['terminal'])
        self.assertEqual(event['remaining_size'],0.)

    def test_old_or_regressing_cumulative_order_update_is_ignored(self):
        value=self.value()
        value.ingest_user(order(matched='4'))
        self.assertFalse(value.ingest_user(order(matched='3')))
        self.assertFalse(value.ingest_user(order(ts=NOW-1,matched='5',status='MATCHED')))
        self.assertEqual(len(value.user_events()[0]),1)

    def test_cancellation_does_not_erase_known_fill_or_reopen_order(self):
        value=self.value()
        value.ingest_user(order(matched='2',status='CANCELED'))
        self.assertFalse(value.ingest_user(order(matched='2',status='LIVE')))
        event=value.user_events()[0][-1]
        self.assertEqual(event['size_matched'],2.)
        self.assertTrue(event['terminal'])

    def test_historical_confirmation_not_discarded_as_stale_book(self):
        value=self.value()
        self.assertTrue(value.ingest_user(order(ts=NOW-600, matched='5', status='MATCHED')))

    def test_auth_values_and_other_owner_never_appear_in_events_or_health(self):
        value=self.value()
        value.ingest_user(order())
        frame=dict(event_type='trade', id='trade-1', market=MARKET, asset_id=TOKEN,
            side='BUY', size='100', price='.85', status='MATCHED', timestamp=NOW*1000,
            trader_side='MAKER', owner=OTHER_OWNER, trade_owner=OTHER_OWNER,
            taker_order_id='their-taker',
            maker_orders=[dict(order_id='own-maker',owner=OWNER,maker_address=WALLET,
                matched_amount='2',price='.85',asset_id=TOKEN,side='SELL'),
                dict(order_id='their-maker',owner=OTHER_OWNER,maker_address='0xother',
                matched_amount='98',price='.85',asset_id=TOKEN,side='SELL')])
        self.assertTrue(value.ingest_user(frame))
        event=value.user_events()[0][-1]
        self.assertEqual(len(event['fills']),1)
        self.assertEqual(event['fills'][0]['size'],2.)
        self.assertEqual(event['fills'][0]['side'],'SELL')
        text=json.dumps([value.health(),value.user_events()[0]])
        for secret in (OWNER,OTHER_OWNER,'private-secret-never-output','private-passphrase-never-output'):
            self.assertNotIn(secret,text)

    def test_sdk_camel_case_user_trade_and_status_are_normalized(self):
        value=self.value()
        payload=dict(id='trade-2',conditionId=MARKET,assetId=TOKEN,side='BUY',
            size='3',price='.85',status='TRADE_STATUS_CONFIRMED',timestamp=NOW*1000,
            traderSide='TAKER',takerOrderId='own-taker',owner=OWNER)
        self.assertTrue(value.ingest_user(dict(topic='user',type='trade',payload=payload)))
        event=value.user_events()[0][-1]
        self.assertEqual(event['fills'][0]['order_id'],'own-taker')
        self.assertEqual(event['fills'][0]['size'],3.)
        self.assertEqual(event['status'],'CONFIRMED')

    def test_failed_trade_not_recorded_as_confirmed_inventory(self):
        value=self.value()
        value.ingest_user(dict(event_type='trade', id='trade-3', market=MARKET,asset_id=TOKEN,
            side='BUY',size='3',price='.85',status='FAILED',timestamp=NOW*1000,
            trader_side='TAKER',taker_order_id='own-taker',owner=OWNER))
        event=value.user_events()[0][-1]
        self.assertEqual(event['fills'],[])
        self.assertEqual(event['status'],'FAILED')


class FakeSocket:
    def __init__(self, frames, hook=None):
        self.frames=list(frames)
        self.sent=[]
        self.hook=hook

    async def send(self, value): self.sent.append(value)

    async def recv(self):
        if self.hook: self.hook(self)
        if not self.frames: raise ConnectionError('socket-ended')
        item=self.frames.pop(0)
        if isinstance(item,Exception): raise item
        return item


class FakeContext:
    def __init__(self,socket): self.socket=socket
    async def __aenter__(self): return self.socket
    async def __aexit__(self,*args): pass


class ReaderProtocolTests(unittest.TestCase):
    def test_market_protocol_and_dynamic_subscription(self):
        value=stream()
        calls=[]
        def hook(socket):
            if len(socket.frames)==2: value.subscribe([OTHER], [MARKET])
            elif len(socket.frames)==1: value._stop.set()
        socket=FakeSocket(['PONG','PONG'],hook)
        def connect(url,**kwargs): calls.append(url); return FakeContext(socket)
        value._connect=connect
        asyncio.run(value._reader('market'))
        frames=[json.loads(x) for x in socket.sent if x not in ('PING','PONG')]
        self.assertEqual(frames[0]['type'],'market')
        self.assertEqual(frames[0]['assets_ids'],[TOKEN,OTHER])
        self.assertIn({'operation':'unsubscribe','assets_ids':[TOKEN], 'custom_feature_enabled':True}, frames)
        self.assertNotIn('auth',json.dumps(frames))

    def test_user_auth_sent_immediately_and_never_in_health(self):
        value=stream(api_key=OWNER,api_secret='secret',api_passphrase='phrase')
        socket=FakeSocket(['PONG'],hook=lambda socket:value._stop.set())
        value._connect=lambda *args,**kwargs:FakeContext(socket)
        asyncio.run(value._reader('user'))
        frame=json.loads(socket.sent[0])
        self.assertEqual(frame,{'auth':{'apiKey':OWNER,'secret':'secret','passphrase':'phrase'},'type':'user','markets':[MARKET]})
        self.assertNotIn(OWNER,json.dumps(value.health()))

    def test_application_ping_heartbeat(self):
        value=stream()
        socket=FakeSocket(['PONG'],hook=lambda socket:value._stop.set())
        value._connect=lambda *args,**kwargs:FakeContext(socket)
        samples=iter([0.,0.,11.,12.])
        with patch('bot.clob_stream.time',SimpleNamespace(monotonic=lambda:next(samples))):
            asyncio.run(value._reader('market'))
        self.assertIn('PING',socket.sent)

    def test_notify_callback_error_does_not_kill_ingestion(self):
        value=stream(on_event=lambda:(_ for _ in ()).throw(RuntimeError('not-reader-failure')))
        self.assertTrue(value.ingest_market(book()))
        self.assertIsNotNone(value.latest_book(TOKEN))


if __name__=='__main__': unittest.main()
