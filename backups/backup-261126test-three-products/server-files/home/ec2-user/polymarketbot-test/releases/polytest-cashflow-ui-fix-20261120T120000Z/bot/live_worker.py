"""Foreground BTC live-worker supervisor for the isolated systemd service.

This module never provisions keys or bypasses trading gates. It owns process
lifecycle evidence, a cross-release lock and compatibility PID files; the
existing BTC loop remains the sole order executor.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import traceback


SAFE_CONFIG_FIELDS = (
    'min_entry_price', 'max_entry_price', 'up_min_entry_price', 'up_max_entry_price',
    'seconds_before_close', 'min_t_remaining_sec', 'confirm_checks',
    'order_risk_fraction', 'order_fixed_notional_usd', 'max_open_positions',
    'max_buys_per_market', 'one_side_per_market', 'max_orders_per_hour',
    'btc_delta_filter_enabled', 'btc_up_min_delta_usd', 'btc_down_max_delta_usd',
    'max_daily_loss_fraction', 'max_daily_realized_profit_fraction',
    'max_daily_realized_profit_usd', 'reversal_exit_enabled',
    'paper_equity_usd', 'sell_fok_slippage_ticks', 'sell_exit_max_depth_ticks',
    'sell_exit_max_depth_levels', 'entry_maker_order_type', 'profit_exit_confirm_checks',
    'take_profit_enabled', 'take_profit_min_gain_fraction', 'take_profit_exit_fraction',
    'max_hold_seconds', 'expiry_exit_enabled', 'expiry_exit_seconds', 'expiry_exit_fraction',
    'profit_maker_order_type', 'reversal_partial_exit_fraction', 'reversal_partial_exit_enabled',
    'sell_exit_fak_fallback_enabled', 'sell_exit_reconcile_trades',
    'reversal_exit_window_sec', 'reversal_held_bid_drawdown', 'reversal_confirm_checks',
    'entry_order_mode', 'entry_maker_ttl_sec', 'entry_maker_post_only',
    'entry_maker_fallback_taker', 'profit_exit_enabled', 'profit_target_fraction',
    'profit_target_ticks', 'profit_exit_fraction', 'profit_exit_order_mode',
    'profit_maker_ttl_sec', 'profit_maker_post_only', 'profit_maker_fallback_taker',
    'stop_exit_order_mode', 'reversal_exit_order_mode', 'near_close_exit_enabled',
    'near_close_exit_window_sec', 'near_close_exit_order_mode',
)


class OperatorStop(BaseException):
    def __init__(self, signum):
        self.signum = signum


def safe_config_snapshot(cfg):
    """Explicit allowlist: no credentials, RPC URLs, tokens or full env values."""
    values = {}
    for name in SAFE_CONFIG_FIELDS:
        value = getattr(cfg, name, None)
        if value is None or isinstance(value, (bool, int, float, str)):
            values[name] = value
    encoded = json.dumps(values, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return values, hashlib.sha256(encoded).hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, sort_keys=True, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_text(path, text):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def process_lock(path):
    # Imported lazily so evidence-writing tests also run on Windows. The
    # production service is Linux and must obtain the kernel lock.
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = path.open('a+', encoding='utf-8')
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('btc_live_worker_lock_held') from None
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()) + '\n')
        handle.flush()
        yield
    finally:
        handle.close()


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def assert_no_legacy_worker(root, pid):
    for name in ('bot.pid', 'bot_btc.pid', 'bot_eth.pid'):
        path = root / name
        try:
            previous = int(path.read_text().strip())
        except (OSError, ValueError):
            continue
        if previous != pid and pid_alive(previous):
            raise RuntimeError('existing_project_worker_must_be_stopped')


def clean_pid_files(root, pid):
    for name in ('bot.pid', 'bot_btc.pid'):
        path = root / name
        try:
            owned = path.read_text().strip() == str(pid)
        except OSError:
            owned = False
        if owned:
            path.unlink(missing_ok=True)
    # Leave unrelated asset workers/mode evidence intact.
    if not (root / 'bot.pid').exists() and not (root / 'bot_btc.pid').exists() and not (root / 'bot_eth.pid').exists():
        (root / 'bot.mode').unlink(missing_ok=True)


def configure_logging(root):
    logs = root / 'logs'
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = 'bot_btc_' + time.strftime('%Y%m%d_%H%M%S', time.gmtime()) + '.log'
    path = logs / filename
    handlers = [logging.StreamHandler(sys.stderr), logging.FileHandler(path, encoding='utf-8')]
    os.chmod(path, 0o600)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    formatter.converter = time.gmtime
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    link = logs / ('bot_btc_current.' + str(os.getpid()))
    link.symlink_to(filename)
    os.replace(link, logs / 'bot_btc_current.log')
    return str(path)


def run_worker(root=None, *, loop_runner=None, config_loader=None, lock_factory=process_lock, setup_logs=True):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    state = Path(os.environ.get('LIVE_WORKER_STATE_DIR') or os.environ.get('STATE_DIR') or root / 'state').expanduser()
    if not state.is_absolute():
        state = root / state
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    pid = os.getpid()
    # A duplicate process must never overwrite the active worker's evidence.
    with lock_factory(state / 'live-worker.lock'):
        assert_no_legacy_worker(root, pid)
        started = time.time()
        runtime = {'schema_version': 1, 'asset': 'BTC', 'mode': 'live', 'pid': pid,
                   'worker_pid': pid, 'running': False, 'started_at': started,
                   'updated_at': started, 'release_root': str(root),
                   'systemd_unit': os.environ.get('LIVE_WORKER_SYSTEMD_UNIT'),
                   'exit_reason': None, 'exit_code': None}
        runtime_path = state / 'live-worker-runtime.json'
        original_handlers = {}

        def stop(signum, frame):
            raise OperatorStop(signum)

        status = 1
        try:
            if setup_logs:
                runtime['log_path'] = configure_logging(root)
            for signum in (signal.SIGTERM, signal.SIGINT):
                original_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, stop)
            if config_loader is None:
                from bot.config import load
                config_loader = load
            cfg = config_loader()
            snapshot, digest = safe_config_snapshot(cfg)
            env_path = root / '.env'
            runtime.update(effective_config=snapshot, config_sha256=digest,
                           configuration_sha256=hashlib.sha256(env_path.read_bytes()).hexdigest() if env_path.exists() else None)
            for name in ('bot.pid', 'bot_btc.pid'):
                atomic_text(root / name, str(pid) + '\n')
            atomic_text(root / 'bot.mode', 'live\n')
            runtime.update(running=True, updated_at=time.time())
            atomic_json(runtime_path, runtime)
            logging.getLogger(__name__).info('BTC supervised live worker started pid=%s config=%s', pid, digest)
            if loop_runner is None:
                from bot.main import loop
                loop_runner = loop
            loop_runner(True, 'BTC')
            runtime['exit_reason'] = 'unexpected_loop_return'
            status = 1
        except OperatorStop as exc:
            runtime.update(exit_reason='operator_signal', signal=signal.Signals(exc.signum).name)
            status = 0
        except KeyboardInterrupt:
            runtime['exit_reason'] = 'operator_interrupt'
            status = 0
        except SystemExit as exc:
            status = int(exc.code) if isinstance(exc.code, int) and exc.code != 0 else 1
            runtime.update(exit_reason='system_exit', exception_type='SystemExit')
        except BaseException as exc:
            runtime.update(exit_reason='worker_exception', exception_type=type(exc).__name__,
                           exception_frames=[{'file': Path(frame.filename).name, 'line': frame.lineno,
                                              'function': frame.name} for frame in traceback.extract_tb(exc.__traceback__)])
            logging.getLogger(__name__).error('BTC supervised worker exception type=%s', type(exc).__name__)
            status = 1
        finally:
            runtime.update(running=False, stopped_at=time.time(), updated_at=time.time(), exit_code=status)
            atomic_json(runtime_path, runtime)
            clean_pid_files(root, pid)
            for signum, handler in original_handlers.items():
                signal.signal(signum, handler)
        return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--asset', choices=('BTC',), default='BTC')
    parser.parse_args()
    return run_worker()


if __name__ == '__main__':
    raise SystemExit(main())
