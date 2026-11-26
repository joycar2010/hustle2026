import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from server import paper_comparison_view as view


class PaperPresentation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.directory=self.root/'runs'/'one';self.directory.mkdir(parents=True)
        (self.root/'current.json').write_text(json.dumps({'directory':'runs/one'}))
        # Presentation tests exercise the secondary B lane explicitly.  The
        # production default is BASELINE (A); keeping this override makes the
        # fixture's FILTERED-only summary deterministic without changing the
        # deployed primary lane.
        self.env=patch.dict(os.environ,{'PAPER_COMPARISON_ROOT':str(self.root),
                                        'PAPER_PRIMARY_GROUP':'FILTERED'})
        self.env.start()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def write(self,**kw):
        doc={'mode':'paper','live_trading_allowed':False,'updated_at':time.time(),
             'groups':{'FILTERED':{'realized_pnl_usd':1.2,'positions':[],
               'daily_rows':[{'day':'2026-11-10','realized_pnl_usd':1.2,'fees_usd':-.2,'wins':1,'losses':0}]}},
             'configuration':{'capital_usd':236.006313},**kw}
        (self.directory/'summary.json').write_text(json.dumps(doc))
        return doc

    def test_missing_summary_never_reads_old_ledger(self):
        self.assertFalse(view.read_summary()['available'])
        self.assertIsNone(view.account()['pnl']['realized_usd'])

    def test_wrong_lane_rejected(self):
        self.write(mode='live');self.assertFalse(view.read_summary()['available'])

    def test_stale_evidence_kept_explicit(self):
        self.write(updated_at=time.time()-30)
        data=view.read_summary();self.assertTrue(data['stale']);self.assertEqual(data['groups']['FILTERED']['realized_pnl_usd'],1.2)

    def test_zero_pnl_is_explicitly_no_fill_with_block_reasons(self):
        self.write(groups={'BASELINE': {'fills': 4, 'realized_pnl_usd': .2},
                           'FILTERED': {'fills': 0, 'candidates': 1209,
                                         'accepted': 0,
                                         'realized_pnl_usd': 0.,
                                         'blocked': {'PROBABILITY_WARMUP': 743,
                                                     'INSUFFICIENT_NET_EDGE': 423},
                                         'positions': [], 'daily_rows': []}})
        data = view.read_summary()
        group = data['groups']['FILTERED']
        self.assertEqual(group['trade_state'], 'NO_FILLED_ORDERS')
        self.assertEqual(group['pnl_status'], 'NOT_APPLICABLE')
        self.assertTrue(group['pnl_is_zero_due_to_no_fill'])
        self.assertEqual(group['zero_pnl_reason']['code'], 'NO_FILLED_ORDERS')
        self.assertEqual(group['zero_pnl_reason']['blocked_reasons'][0]['reason'], 'PROBABILITY_WARMUP')

    def test_primary_group_defaults_to_a_baseline(self):
        with patch.dict(os.environ, {'PAPER_PRIMARY_GROUP': 'invalid'}, clear=False):
            self.assertEqual(view.primary_group(), 'BASELINE')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(view.primary_group(), 'BASELINE')

    def test_traversal_rejected(self):
        (self.root/'current.json').write_text(json.dumps({'directory':'../elsewhere'}))
        self.assertFalse(view.read_summary()['available'])

    def test_daily_fee_sign_and_pnl_mapping(self):
        self.write();r=view.daily_page()['rows'][0]
        self.assertEqual(r['realized_usd'],1.2);self.assertEqual(r['fees_usd'],-.2)

    def test_orders_are_owned_by_current_group(self):
        self.write()
        with closing(sqlite3.connect(self.directory/'comparison.sqlite3')) as db:
            db.executescript('CREATE TABLE fills(lane,fill_id,ts,market_id,payload);CREATE TABLE windows(market_id,payload);')
            db.execute('INSERT INTO windows VALUES(?,?)',('m',json.dumps({'market_slug':'btc-5m','up_token':'u','down_token':'d'})))
            for lane in ('FILTERED','BASELINE'):
                db.execute('INSERT INTO fills VALUES(?,?,?,?,?)',(lane,'1',time.time(),'m',json.dumps({
                  'token_id':'d','side':'BUY','size':5,'price':.85,'fee_usd':-.02})))
            db.commit()
        page=view.orders_page();self.assertEqual(page['total'],1);self.assertEqual(page['rows'][0]['side'],'DOWN')
        self.assertTrue(page['rows'][0]['dry_run']);self.assertEqual(page['rows'][0]['fee_usd'],-.02)

    def test_export_never_copies_credentials(self):
        path=self.root/'config.json'
        result=view.export_public_config({'PRIVATE_KEY':'never-copy','BTC_LIVE_ENABLED':'true',
            'MAX_DAILY_LOSS_FRACTION':'.03','MAX_DAILY_REALIZED_PROFIT_FRACTION':'.07',
            'MIN_ENTRY_PRICE':'.84','MAX_ENTRY_PRICE':'.9'},path)
        self.assertNotIn('never-copy',path.read_text());self.assertEqual(result['mode'],'paper')
        self.assertEqual(result['capital_usd'],236.006313)

    def test_stopped_process_not_claimed_running(self):
        self.write(worker_pid=999999999);self.assertFalse(view.read_runtime()['worker_running'])

if __name__=='__main__':unittest.main()
