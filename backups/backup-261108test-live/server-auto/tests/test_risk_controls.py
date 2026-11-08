"""Risk control contract tests, isolated from databases, services and secrets."""
import ast
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from dotenv import dotenv_values
from fastapi import HTTPException
import pytest


@pytest.fixture
def helpers(tmp_path):
    source = Path(__file__).parents[1] / 'server/dashboard.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'_validate_risk_settings', '_apply_risk_settings', '_verify_risk_worker', '_update_env_keys'}
    fields = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_RISK_WORKER_FIELDS' for t in n.targets))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    root = tmp_path / 'root'; root.mkdir()
    release = root / 'release'; release.mkdir()
    env_paths = [root / '.env', release / '.env']
    for path in env_paths:
        path.write_text('MAX_DAILY_LOSS_FRACTION=0.05\nMAX_DAILY_REALIZED_PROFIT_FRACTION=0.08\nREVERSAL_HELD_BID_DRAWDOWN=0.3\nORDER_RISK_FRACTION=0.02\nPRIVATE_KEY=never-return\n')
    clock = SimpleNamespace(now=0.)
    def sleep(seconds): clock.now += seconds
    runtime = Mock(return_value={'worker_running': False, 'worker_service_state': 'STOPPED'})
    config = SimpleNamespace(max_daily_loss_fraction=.05, max_daily_realized_profit_fraction=.08, reversal_held_bid_drawdown=.3, order_risk_fraction=.02)
    ns = {'Any': object, 'Optional': object, 'Path': Path, 'math': math,
          'HTTPException': HTTPException, 'ROOT': root, 'DB_PATH': root / 'trades.db',
          'os': __import__('os'), 'time': SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep, strftime=lambda _: 'test'),
          'subprocess': SimpleNamespace(run=Mock(), SubprocessError=subprocess.SubprocessError),
          '_risk_env_paths': lambda: env_paths, '_is_polyauto_instance': lambda: True,
          '_control_env_values': lambda: dotenv_values(env_paths[0]), '_paper_worker_daily_loss': runtime,
          '_paper_worker_loss_cache': {}, '_kelly_flag_cache': {'ts': 1.}, '_paper_shadow_cache': {'ts': 1.}, 'cfg': config}
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), fields, *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), ns)
    ns['_paths'] = env_paths
    return ns


def test_stop_and_risk_persist_to_both_configs_without_changing_daily_limits(helpers):
    result = helpers['_apply_risk_settings']({'reversal_held_bid_drawdown': .1, 'order_risk_fraction': .02, 'restart_workers': False})
    for path in helpers['_paths']:
        values = dotenv_values(path)
        assert float(values['REVERSAL_HELD_BID_DRAWDOWN']) == .1
        assert float(values['ORDER_RISK_FRACTION']) == .02
        assert float(values['MAX_DAILY_LOSS_FRACTION']) == .05
        assert float(values['MAX_DAILY_REALIZED_PROFIT_FRACTION']) == .08
        assert path.with_name('.env.before-risk.test').exists()
    assert 'never-return' not in str(result)
    assert helpers['cfg'].reversal_held_bid_drawdown == .1
    assert result['workers_restarted'] == []


@pytest.mark.parametrize('field', ['reversal_held_bid_drawdown', 'order_risk_fraction'])
@pytest.mark.parametrize('value', [True, False, None, float('nan'), float('inf'), 0., -.01, 1.01, 'bad'])
def test_invalid_controls_do_not_mutate_files_or_config(helpers, field, value):
    before = [p.read_bytes() for p in helpers['_paths']]
    with pytest.raises(HTTPException) as error:
        helpers['_apply_risk_settings']({'max_daily_loss_fraction': .1, field: value})
    assert error.value.status_code == 400
    assert [p.read_bytes() for p in helpers['_paths']] == before
    assert helpers['cfg'].max_daily_loss_fraction == .05
    helpers['subprocess'].run.assert_not_called()


@pytest.mark.parametrize('body', [[], None, {}, {'kelly_sizing_enabled': 'false'}, {'order_risk_fraction': .02, 'restart_workers': 'false'}, {'max_daily_realized_profit_fraction': float('nan')}])
def test_malformed_request_rejected(helpers, body):
    with pytest.raises(HTTPException) as error:
        helpers['_apply_risk_settings'](body)
    assert error.value.status_code == 400


def test_restart_command_failure_is_not_reported_as_success(helpers):
    helpers['subprocess'].run.side_effect = subprocess.CalledProcessError(1, 'systemctl')
    with pytest.raises(HTTPException) as error:
        helpers['_apply_risk_settings']({'reversal_held_bid_drawdown': .1})
    assert error.value.status_code == 503
    assert '配置已保存' in error.value.detail


def test_immediately_failed_worker_is_not_reported_as_success(helpers):
    with pytest.raises(HTTPException) as error:
        helpers['_apply_risk_settings']({'reversal_held_bid_drawdown': .1})
    assert error.value.status_code == 503


def running(pid, **values):
    return {'worker_running': True, 'worker_service_state': 'RUNNING', 'worker_pid': pid,
            'worker_config': {'max_daily_loss_fraction': .05, 'max_daily_realized_profit_fraction': .08,
                              'reversal_held_bid_drawdown': .1, 'order_risk_fraction': .02, **values}}


@pytest.mark.parametrize('failure', ['old_pid', 'wrong_parameter', 'missing_parameter'])
def test_wrong_or_stale_runtime_is_rejected(helpers, failure):
    actual = running(123)
    if failure == 'wrong_parameter': actual['worker_config']['reversal_held_bid_drawdown'] = .3
    if failure == 'missing_parameter': actual['worker_config'].pop('order_risk_fraction')
    helpers['_paper_worker_daily_loss'].return_value = actual
    with pytest.raises(HTTPException):
        helpers['_verify_risk_worker']({'reversal_held_bid_drawdown': .1, 'order_risk_fraction': .02}, 123 if failure == 'old_pid' else 100)


def test_new_process_must_load_all_saved_controls(helpers):
    helpers['_paper_worker_daily_loss'].side_effect = [running(100), running(200), running(200), running(200)]
    result = helpers['_apply_risk_settings']({'reversal_held_bid_drawdown': .1, 'order_risk_fraction': .02})
    assert result['worker_pid'] == 200
    assert result['effective_config']['max_daily_loss_fraction'] == .05
    assert result['effective_config']['max_daily_realized_profit_fraction'] == .08
    assert result['workers_restarted'] == ['btc-paper']
    assert helpers['subprocess'].run.call_count == 1


def test_production_manifest_allows_operator_controls_but_shadow_remains_fixed():
    import runpy
    manifest = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/write_runtime_manifest.py'))
    values = manifest['expected_for']('D-production', {})
    values.update(REVERSAL_HELD_BID_DRAWDOWN='0.1', ORDER_RISK_FRACTION='0.02', PAPER_EQUITY_USD='100',
                  MAX_DAILY_LOSS_FRACTION='0.05', MAX_DAILY_REALIZED_PROFIT_FRACTION='0.08')
    manifest['validate_production_values'](values)
    assert values['CONFIG_PROFILE'] == 'D'
    assert manifest['expected_for']('A', {})['REVERSAL_HELD_BID_DRAWDOWN'] == '0.30'
    assert manifest['expected_for']('B', {})['MAX_DAILY_REALIZED_PROFIT_FRACTION'] == '0.12'
    values['REVERSAL_HELD_BID_DRAWDOWN'] = 'nan'
    with pytest.raises(SystemExit): manifest['validate_production_values'](values)
