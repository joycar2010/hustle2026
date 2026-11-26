"""Exercise real Dashboard handlers with isolated account/service adapters.

The production SDK is intentionally not imported: AST loading retains the
actual handler implementations while every network/process adapter is fake.
"""
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace, ModuleType
from typing import Any, Literal, Optional
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient
import requests


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / 'server' / 'dashboard.py'
SPEC = importlib.util.spec_from_file_location('dashboard_test_chain_statistics', ROOT / 'server' / 'chain_statistics.py')
chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chain)
BJ = timezone(timedelta(hours=8))
START = datetime(2026, 11, 10, tzinfo=BJ).timestamp()
END = START + 86400
WALLET = '0x' + '12' * 20


def handlers(*names, **adapters):
    tree = ast.parse(DASHBOARD.read_text(encoding='utf-8'))
    body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in body} == set(names)
    for node in body:
        node.decorator_list = []
    namespace = dict(Any=Any, Literal=Literal, Optional=Optional, Path=Path,
        Query=Query, HTTPException=HTTPException, math=math, json=json,
        hashlib=hashlib, time=time, re=re, os=os, requests=requests,
        subprocess=subprocess,
        datetime=datetime, timedelta=timedelta, timezone=timezone,
        chain_number=chain.number, chain_cashflow=chain.cashflow,
        coherent_points=chain.coherent_points,
        summarize_activity_period=chain.summarize_activity_period)
    namespace.update(adapters)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *body], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(DASHBOARD), 'exec'), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def trade(ts, tx, side='BUY', amount=2.):
    return dict(type='TRADE', timestamp=ts, transaction_hash=tx, token_id='token',
                condition_id='condition', side=side, size=5., price=.4, usdc_size=amount)


class DashboardOrdersIntegrationTests(unittest.TestCase):
    def test_live_route_never_reads_paper_ledger(self):
        local = Mock(side_effect=AssertionError('Paper ledger leaked into live request'))
        activity = Mock(return_value={'rows': [{'record_key': 'chain:1'}], 'total': 1})
        route = handlers('orders_page', _local_orders_page=local, _polymarket_activity_rows=activity).orders_page
        result = route(offset=20, limit=20, lane='live', asset='BTC', start_ts=START, end_ts=END)
        self.assertEqual(result['lane'], 'live')
        activity.assert_called_once_with(limit=20, offset=20, start_ts=START, end_ts=END, include_period=True)
        local.assert_not_called()

    def test_paper_route_never_reads_live_account(self):
        activity = Mock(side_effect=AssertionError('Live account leaked into Paper request'))
        local = Mock(return_value={'rows': [{'record_key': 'paper:1'}], 'total': 1})
        route = handlers('orders_page', _local_orders_page=local, _polymarket_activity_rows=activity).orders_page
        result = route(offset=0, limit=20, lane='paper', asset='', start_ts=START, end_ts=END)
        self.assertEqual(result['asset'], 'BTC')
        local.assert_called_once_with(0, 20, 'paper', start_ts=START, end_ts=END)
        activity.assert_not_called()

    def test_query_defaults_do_not_escape_into_activity_adapter(self):
        activity = Mock(return_value={'rows': [], 'total': 0})
        route = handlers('orders_page', _polymarket_activity_rows=activity).orders_page
        route(offset=0, limit=20, lane='live')
        self.assertIsNone(activity.call_args.kwargs['start_ts'])
        self.assertIsNone(activity.call_args.kwargs['end_ts'])

    def test_invalid_intervals_cannot_reach_account_source(self):
        activity = Mock()
        route = handlers('orders_page', _polymarket_activity_rows=activity).orders_page
        for start, end in ((END, START), (START, START), (float('nan'), END), (START, float('inf'))):
            with self.subTest(start=start, end=end), self.assertRaises(HTTPException) as error:
                route(offset=0, limit=20, lane='live', start_ts=start, end_ts=end)
            self.assertEqual(error.exception.status_code, 422)
        activity.assert_not_called()

    def test_http_query_rejects_negative_dates_and_invalid_lanes(self):
        activity = Mock()
        route = handlers('orders_page', _polymarket_activity_rows=activity).orders_page
        app = FastAPI()
        app.get('/orders')(route)
        client = TestClient(app)
        for query in ('start_ts=-1&lane=live', 'end_ts=-1&lane=live', 'lane=unknown', 'lane=live&asset=ETH'):
            self.assertEqual(client.get('/orders?' + query).status_code, 422)
        activity.assert_not_called()

    def test_upstream_activity_failure_returns_explicit_unavailable(self):
        route = handlers('orders_page', _polymarket_activity_rows=Mock(side_effect=requests.Timeout())).orders_page
        with self.assertRaises(HTTPException) as error:
            route(offset=0, limit=20, lane='live')
        self.assertEqual(error.exception.status_code, 503)

    def test_period_filters_all_rows_before_pagination_and_fee_summary(self):
        source = [trade(END, 'at-end'), trade(START - 1, 'before')]
        source += [trade(START + index, str(index), amount=1.) for index in range(45)]
        source.sort(key=lambda row: row['timestamp'], reverse=True)
        fees = Mock()
        fees.snapshot.side_effect = lambda selected, all_rows, wallet: [
            dict(fee_status='confirmed', fee_usd=-.01, liquidity_role='TAKER') for _ in selected]
        route = handlers('_polymarket_activity_rows',
            _activity_snapshot=Mock(return_value=dict(rows=source, wallet=WALLET, available=True,
                stale=False, updated_at=END)), _TRADE_FEE_EVIDENCE=fees,
            _closed_positions_snapshot=Mock(return_value=dict(rows=[], available=True)),
            _POLY_FINANCIAL_INPUTS={'user-pnl': {'points': []}},
            _polymarket_live_summary=Mock(side_effect=AssertionError('unnecessary refresh')))._polymarket_activity_rows
        page = route(limit=20, offset=20, start_ts=START, end_ts=END, include_period=True)
        self.assertEqual(page['total'], 45)
        self.assertEqual(len(page['rows']), 20)
        self.assertEqual(page['period_summary']['records'], 45)
        self.assertEqual(page['period_summary']['net_cashflow_usd'], -45.)
        self.assertEqual(page['period_summary']['fees_usd'], -.45)
        self.assertTrue(page['period_summary']['cashflow_fee_inclusive'])
        self.assertEqual(len(fees.snapshot.call_args.args[0]), 45)
        self.assertEqual(page['period_summary']['official_scope'], 'wallet')


class DashboardDailySourceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Mock(return_value=[{'day': '2026-11-10', 'by_asset': {'BTC': {'net_pnl_usd': 99.}}}])
        module = ModuleType('server.pnl_history')
        module.daily_rows = self.ledger
        self.modules = patch.dict(sys.modules, {'server.pnl_history': module})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_live_ignores_ledger_source_parameter_and_assigns_each_day_proven_base(self):
        official = Mock(return_value=dict(available=True, daily_rows=[
            dict(day='2026-11-10', economic_pnl=-1.), dict(day='2026-11-09', economic_pnl=2.)]))
        bases = Mock(side_effect=lambda day=None: {'2026-11-10': 236., '2026-11-09': 230., None: 236.}[day])
        route = handlers('pnl_daily', _polymarket_live_summary=official, _live_day_capital=bases).pnl_daily
        result = route(lane='live', source='ledger', asset='BTC', offset=0, limit=50)
        self.assertEqual([row['capital_base_usd'] for row in result['rows']], [236., 230.])
        self.assertEqual(result['capital_base_usd'], 236.)
        self.assertEqual(result['source'], 'data_api_v2_user_pnl_activity')
        self.ledger.assert_not_called()

    def test_paper_ignores_chain_source_parameter(self):
        official = Mock(side_effect=AssertionError('chain source leaked into Paper request'))
        route = handlers('pnl_daily', DB_PATH='PAPER_ONLY.db', cfg=SimpleNamespace(paper_equity_usd=1000.),
            _state={}, _polymarket_live_summary=official).pnl_daily
        result = route(lane='paper', source='chain', asset='BTC', offset=0, limit=50)
        self.assertEqual(result['source'], 'ledger')
        self.assertEqual(result['rows'][0]['net_pnl_usd'], 99.)
        self.assertEqual(result['capital_base_usd'], 1000.)
        self.ledger.assert_called_once_with('PAPER_ONLY.db', True)
        official.assert_not_called()


class DashboardFrozenCapitalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'live-risk.json'
        self.read = Mock(return_value=dict(capital_base_usd=None))
        self.route = handlers('_live_day_capital', cfg=object(), read_live_risk_snapshot=self.read,
            _deposit_wallet_address=lambda: WALLET.upper().replace('0X', '0x'),
            live_risk_state_file=lambda: self.state)._live_day_capital

    def baseline(self, day, **changes):
        data = dict(wallet=WALLET, day_start_equity_usd=236.)
        data.update(changes)
        self.state.with_name(f'live-risk.{WALLET}.{day}.baseline.json').write_text(json.dumps(data))

    def test_historical_day_reads_that_day_and_wallet_frozen_equity(self):
        self.baseline('2026-11-10')
        self.baseline('2026-11-09', day_start_equity_usd=230.)
        self.assertEqual(self.route('2026-11-10'), 236.)
        self.assertEqual(self.route('2026-11-09'), 230.)
        self.read.assert_not_called()

    def test_missing_or_foreign_baseline_does_not_use_current_balance(self):
        self.assertIsNone(self.route('2026-11-10'))
        self.baseline('2026-11-10', wallet='0x' + '34' * 20)
        self.assertIsNone(self.route('2026-11-10'))

    def test_zero_or_nonfinite_or_malformed_proof_remains_unknown(self):
        for value in (0., float('nan'), -1., None, True):
            with self.subTest(value=value):
                self.baseline('2026-11-10', day_start_equity_usd=value)
                self.assertIsNone(self.route('2026-11-10'))

    def test_path_traversal_is_rejected(self):
        self.assertIsNone(self.route('../2026-11-10'))

    def test_expired_current_valuation_keeps_today_frozen_roi_denominator(self):
        today = datetime.now(BJ).strftime('%Y-%m-%d')
        self.baseline(today)
        self.assertEqual(self.route(), 236.)


class DashboardSharedRiskTests(unittest.TestCase):
    def route(self, running):
        authoritative = dict(capital_base_usd=236., daily_realized_usd=-1.44,
            daily_profit_target_usd=16.52, allow_entries=True, open_positions_count=2,
            position_value_usd=12.34, max_daily_loss_fraction=.03)
        route = handlers('_risk_snapshot', cfg=SimpleNamespace(max_open_positions=3),
            _service_status_snapshot=lambda: {'BTC': {'live_enabled': True}},
            read_live_risk_snapshot=lambda cfg: dict(authoritative),
            _account_positions_snapshot=lambda: {'pending_count': 0, 'total_value_usd': 0.},
            _live_worker_runtime=lambda asset: dict(worker_running=running,
                worker_service_state='RUNNING' if running else 'STOPPED'))._risk_snapshot
        return route

    def test_live_uses_shared_net_account_evidence_not_paper_pnl_or_filtered_holdings(self):
        snapshot = self.route(True)({'realized_usd': 9999., 'wins': 999})
        self.assertEqual(snapshot['daily_realized_usd'], -1.44)
        self.assertEqual(snapshot['capital_base_usd'], 236.)
        self.assertEqual(snapshot['daily_profit_target_usd'], 16.52)
        self.assertEqual(snapshot['position_count'], 2)
        self.assertEqual(snapshot['position_value_usd'], 12.34)
        self.assertTrue(snapshot['allow_entries'])

    def test_stopped_worker_cannot_be_reported_as_allowed_to_execute(self):
        snapshot = self.route(False)({})
        self.assertFalse(snapshot['allow_entries'])
        self.assertEqual(snapshot['execution_state'], 'WORKER_STOPPED')
        self.assertEqual(snapshot['daily_realized_usd'], -1.44)


class DashboardRestartEvidenceTests(unittest.TestCase):
    def clock(self):
        values = iter(index * .5 for index in range(100))
        return SimpleNamespace(monotonic=lambda: next(values), sleep=lambda seconds: None)

    def test_saved_config_and_unchanged_pid_are_not_verified_as_restart(self):
        runtime = lambda asset: dict(worker_running=True, worker_pid=123,
            configuration_matches_saved=True,
            effective_config={'max_daily_loss_fraction': .03})
        route = handlers('_verify_live_worker', '_worker_setting_matches',
            _live_worker_runtime=runtime, time=self.clock())._verify_live_worker
        with self.assertRaises(HTTPException) as error:
            route({'max_daily_loss_fraction': .03}, previous_pid=123)
        self.assertEqual(error.exception.status_code, 503)

    def test_new_pid_with_stale_manifest_values_is_not_accepted(self):
        runtime = lambda asset: dict(worker_running=True, worker_pid=124,
            configuration_matches_saved=True,
            effective_config={'max_daily_loss_fraction': .01})
        route = handlers('_verify_live_worker', '_worker_setting_matches',
            _live_worker_runtime=runtime, time=self.clock())._verify_live_worker
        with self.assertRaises(HTTPException):
            route({'max_daily_loss_fraction': .03}, previous_pid=123)

    def test_every_expected_field_must_exist_in_running_manifest(self):
        runtime = lambda asset: dict(worker_running=True, worker_pid=124,
            configuration_matches_saved=True,
            effective_config={'max_daily_loss_fraction': .03})
        route = handlers('_verify_live_worker', '_worker_setting_matches',
            _live_worker_runtime=runtime, time=self.clock())._verify_live_worker
        with self.assertRaises(HTTPException):
            route({'max_daily_loss_fraction': .03, 'sell_exit_reconcile_trades': True}, previous_pid=123)

    def test_new_pid_and_exact_effective_values_are_verified(self):
        runtime = lambda asset: dict(worker_running=True, worker_pid=124,
            configuration_matches_saved=True,
            effective_config={'max_daily_loss_fraction': .03, 'sell_exit_reconcile_trades': True})
        route = handlers('_verify_live_worker', '_worker_setting_matches',
            _live_worker_runtime=runtime, time=self.clock())._verify_live_worker
        result = route({'max_daily_loss_fraction': .03, 'sell_exit_reconcile_trades': True}, previous_pid=123)
        self.assertEqual(result['worker_pid'], 124)

    def test_saved_env_hash_must_match_even_when_selected_fields_match(self):
        runtime = lambda asset: dict(worker_running=True, worker_pid=124,
            configuration_matches_saved=False,
            effective_config={'max_daily_loss_fraction': .03})
        route = handlers('_verify_live_worker', '_worker_setting_matches',
            _live_worker_runtime=runtime, time=self.clock())._verify_live_worker
        with self.assertRaises(HTTPException):
            route({'max_daily_loss_fraction': .03}, previous_pid=123)

    def test_live_env_isolated_from_optional_paper_unit_configuration(self):
        process = Mock(side_effect=AssertionError('Live must not inspect/write Paper env files'))
        route = handlers('_risk_env_paths', ROOT=Path('/current/live-release'),
            _service_status_snapshot=lambda: {'BTC': {'live_enabled': True}},
            subprocess=SimpleNamespace(run=process))._risk_env_paths
        self.assertEqual(route(), [Path('/current/live-release/.env')])
        process.assert_not_called()

    def test_running_paper_takes_priority_over_live_permission_when_selecting_env(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'current'
            paper_env = Path(folder) / 'paper.env'
            paper_env.write_text('MAX_DAILY_LOSS_FRACTION=.03\n')
            run = Mock(return_value=SimpleNamespace(stdout=str(paper_env)))
            route = handlers('_risk_env_paths', ROOT=root,
                _service_status_snapshot=lambda: {'BTC': {'live_enabled': True, 'paper_running': True}},
                subprocess=SimpleNamespace(run=run))._risk_env_paths
            self.assertEqual(route(), [root / '.env', paper_env])
            run.assert_called_once()

    def test_settings_save_chooses_actual_paper_mode_and_parses_preserved_boolean(self):
        verify = Mock(return_value={'worker_pid': 124, 'worker_config': {'sell_exit_reconcile_trades': True}})
        route = handlers('_apply_risk_settings',
            _validate_risk_settings=lambda body: ({'max_daily_loss_fraction': .03}, {'MAX_DAILY_LOSS_FRACTION': '.03'}, ['saved']),
            _RISK_WORKER_FIELDS={'max_daily_loss_fraction': 'MAX_DAILY_LOSS_FRACTION'},
            _EXECUTION_WORKER_FIELDS={'sell_exit_reconcile_trades': 'SELL_EXIT_RECONCILE_TRADES'},
            _control_env_values=lambda: {'SELL_EXIT_RECONCILE_TRADES': 'true'},
            _service_status_snapshot=lambda: {'BTC': {'live_enabled': True, 'paper_running': True}},
            _live_worker_runtime=Mock(side_effect=AssertionError('must not control live')),
            _paper_worker_loss_cache={}, _paper_worker_daily_loss=lambda *args: {'worker_pid': 123},
            _update_env_keys=lambda changes: ['paper.env'], cfg=SimpleNamespace(),
            _kelly_flag_cache={}, ROOT=Path('/current/release'), DB_PATH='paper.db',
            subprocess=SimpleNamespace(run=Mock(), SubprocessError=subprocess.SubprocessError),
            _verify_risk_worker=verify)._apply_risk_settings
        result = route({'restart_workers': True})
        self.assertEqual(result['worker_mode'], 'paper')
        self.assertEqual(result['workers_restarted'], ['btc-paper'])
        self.assertEqual(verify.call_args.args, ({'max_daily_loss_fraction': .03, 'sell_exit_reconcile_trades': True}, 123))

    def test_stopped_selected_live_mode_remains_live_without_restarting_on_save_only(self):
        route = handlers('_apply_risk_settings',
            _validate_risk_settings=lambda body: ({'max_daily_loss_fraction': .03}, {'MAX_DAILY_LOSS_FRACTION': '.03'}, []),
            _RISK_WORKER_FIELDS={}, _EXECUTION_WORKER_FIELDS={}, _control_env_values=lambda: {},
            _service_status_snapshot=lambda: {'BTC': {'live_enabled': True, 'paper_running': False, 'live_running': False}},
            _update_env_keys=lambda changes: ['live.env'], cfg=SimpleNamespace(),
            _kelly_flag_cache={}, _paper_worker_loss_cache={})._apply_risk_settings
        result = route({'restart_workers': False})
        self.assertEqual(result['worker_mode'], 'live')
        self.assertEqual(result['workers_restarted'], [])


class DashboardProcessManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'release'
        self.root.mkdir()
        (self.root / '.env').write_text('PUBLIC_TEST_CONFIG_ONLY=1\n')
        (self.root / 'bot_btc.pid').write_text('123')
        self.state = Path(self.temp.name) / 'state'
        self.state.mkdir()
        self.manifest = dict(pid=123, mode='live', asset='BTC', running=True,
            release_root=str(self.root), configuration_sha256=hashlib.sha256((self.root / '.env').read_bytes()).hexdigest(),
            effective_config={'max_daily_loss_fraction': .03})
        self.cwd = self.root
        self.patch_env = patch.dict(os.environ, {'LIVE_WORKER_STATE_DIR': str(self.state)})
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)

    def route(self):
        (self.state / 'live-worker-runtime.json').write_text(json.dumps(self.manifest))
        def path(value):
            if str(value).startswith('/proc/') and str(value).endswith('/cwd'):
                return SimpleNamespace(resolve=lambda strict=False: self.cwd.resolve())
            return Path(value)
        return handlers('_live_worker_runtime', ROOT=self.root, Path=path,
            _pid_command_line=lambda pid_path: 'python -m bot.live_worker --live --asset BTC',
            live_risk_state_file=lambda: self.state / 'live-risk.json')._live_worker_runtime

    def test_pid_command_cwd_manifest_and_saved_hash_all_agree(self):
        result = self.route()('BTC')
        self.assertTrue(result['worker_running'])
        self.assertTrue(result['configuration_matches_saved'])
        self.assertEqual(result['effective_max_daily_loss_fraction'], .03)

    def test_pid_of_another_release_is_not_current_worker(self):
        self.cwd = self.root.parent / 'older-release'
        result = self.route()('BTC')
        self.assertFalse(result['worker_running'])
        self.assertNotIn('effective_config', result)

    def test_stopped_or_foreign_manifest_never_proves_effective_config(self):
        for changes in ({'pid': 456}, {'running': False}, {'mode': 'paper'}, {'release_root': str(self.root.parent / 'other')}):
            with self.subTest(changes=changes):
                saved = dict(self.manifest)
                self.manifest.update(changes)
                result = self.route()('BTC')
                self.assertNotIn('effective_config', result)
                self.manifest = saved

    def test_saved_config_edit_without_worker_reload_is_reported_stale(self):
        self.manifest['configuration_sha256'] = '0' * 64
        result = self.route()('BTC')
        self.assertTrue(result['worker_running'])
        self.assertFalse(result['configuration_matches_saved'])


if __name__ == '__main__':
    unittest.main()
