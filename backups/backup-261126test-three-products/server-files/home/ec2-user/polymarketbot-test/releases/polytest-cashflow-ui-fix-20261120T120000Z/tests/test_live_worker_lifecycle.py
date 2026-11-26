import ast
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('supervised_live_worker', ROOT / 'bot' / 'live_worker.py')
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


@contextmanager
def fake_lock(path):
    yield


class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / 'shared-state'
        self.environment = patch.dict(os.environ, {'LIVE_WORKER_STATE_DIR': str(self.state),
            'LIVE_WORKER_SYSTEMD_UNIT': 'polymarket-test-btc-live.service'})
        self.environment.start()
        self.cfg = SimpleNamespace(min_entry_price=.84, max_entry_price=.9, order_risk_fraction=.02,
            max_daily_loss_fraction=.03, max_daily_realized_profit_fraction=.07,
            private_key='PRIVATE_DO_NOT_LEAK', polygon_rpc_url='https://secret_rpc/DO_NOT_LEAK')
        (self.root / '.env').write_text('PRIVATE_KEY=PRIVATE_DO_NOT_LEAK\n', encoding='utf-8')

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def run_fake(self, loop_runner):
        return worker.run_worker(self.root, loop_runner=loop_runner, config_loader=lambda: self.cfg,
                                 lock_factory=fake_lock, setup_logs=False)

    def manifest(self):
        return json.loads((self.state / 'live-worker-runtime.json').read_text())

    def test_foreground_loop_has_owned_pid_files_and_safe_config_manifest(self):
        called = []
        def loop(live, asset):
            called.append((live, asset))
            self.assertEqual((self.root / 'bot.pid').read_text().strip(), str(os.getpid()))
            self.assertEqual((self.root / 'bot_btc.pid').read_text().strip(), str(os.getpid()))
            self.assertEqual((self.root / 'bot.mode').read_text().strip(), 'live')
            snapshot = self.manifest()
            self.assertTrue(snapshot['running'])
            self.assertEqual(snapshot['effective_config']['max_daily_loss_fraction'], .03)
            self.assertEqual(len(snapshot['configuration_sha256']), 64)
            raise worker.OperatorStop(signal.SIGTERM)
        self.assertEqual(self.run_fake(loop), 0)
        self.assertEqual(called, [(True, 'BTC')])
        self.assertFalse((self.root / 'bot.pid').exists())
        self.assertFalse((self.root / 'bot_btc.pid').exists())
        self.assertFalse((self.root / 'bot.mode').exists())

    def test_manual_stop_records_success_so_restart_on_failure_does_not_restart(self):
        def loop(*args):
            raise worker.OperatorStop(signal.SIGTERM)
        self.assertEqual(self.run_fake(loop), 0)
        result = self.manifest()
        self.assertEqual(result['exit_reason'], 'operator_signal')
        self.assertEqual(result['signal'], 'SIGTERM')
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['running'])

    def test_keyboard_interrupt_is_clean_stop(self):
        def loop(*args):
            raise KeyboardInterrupt
        self.assertEqual(self.run_fake(loop), 0)
        self.assertEqual(self.manifest()['exit_reason'], 'operator_interrupt')

    def test_unexpected_return_is_failure_with_explicit_reason(self):
        self.assertEqual(self.run_fake(lambda *args: None), 1)
        self.assertEqual(self.manifest()['exit_reason'], 'unexpected_loop_return')

    def test_exception_evidence_does_not_copy_message_or_environment(self):
        def loop(*args):
            raise RuntimeError('PRIVATE_DO_NOT_LEAK https://secret_rpc/DO_NOT_LEAK')
        self.assertEqual(self.run_fake(loop), 1)
        raw = (self.state / 'live-worker-runtime.json').read_text()
        self.assertNotIn('PRIVATE_DO_NOT_LEAK', raw)
        self.assertNotIn('https://secret_rpc', raw)
        self.assertEqual(self.manifest()['exception_type'], 'RuntimeError')
        self.assertTrue(self.manifest()['exception_frames'])

    def test_system_exit_zero_is_not_mistaken_for_manual_stop(self):
        def loop(*args):
            raise SystemExit(0)
        self.assertEqual(self.run_fake(loop), 1)
        self.assertEqual(self.manifest()['exit_reason'], 'system_exit')

    def test_duplicate_legacy_process_never_overwrites_active_evidence(self):
        self.state.mkdir()
        path = self.state / 'live-worker-runtime.json'
        path.write_text('{"pid":12345,"running":true}')
        (self.root / 'bot.pid').write_text('12345')
        with patch.object(worker, 'pid_alive', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'existing_project_worker'):
                self.run_fake(lambda *args: None)
        self.assertEqual(json.loads(path.read_text()), {'pid': 12345, 'running': True})

    def test_only_owned_pid_files_are_removed(self):
        (self.root / 'bot.pid').write_text('7777')
        (self.root / 'bot_btc.pid').write_text(str(os.getpid()))
        (self.root / 'bot_eth.pid').write_text('8888')
        (self.root / 'bot.mode').write_text('live')
        worker.clean_pid_files(self.root, os.getpid())
        self.assertEqual((self.root / 'bot.pid').read_text(), '7777')
        self.assertEqual((self.root / 'bot_eth.pid').read_text(), '8888')
        self.assertTrue((self.root / 'bot.mode').exists())

    def test_allowlist_covers_all_dashboard_restart_verification_fields(self):
        tree = ast.parse((ROOT / 'server' / 'dashboard.py').read_text(encoding='utf-8'))
        required = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if set(names) & {'_RISK_WORKER_FIELDS', '_EXECUTION_WORKER_FIELDS'}:
                    required.update(ast.literal_eval(node.value))
        self.assertTrue(required)
        self.assertFalse(required - set(worker.SAFE_CONFIG_FIELDS), required - set(worker.SAFE_CONFIG_FIELDS))

    @unittest.skipUnless(os.name == 'posix', 'flock is a production Linux property')
    def test_kernel_lock_rejects_second_owner(self):
        lock = self.root / 'worker.lock'
        with worker.process_lock(lock):
            with self.assertRaisesRegex(RuntimeError, 'lock_held'):
                with worker.process_lock(lock):
                    self.fail('second lock owner admitted')

    @unittest.skipUnless(os.name == 'posix', 'POSIX mode verification')
    def test_runtime_evidence_is_private(self):
        def loop(*args):
            raise worker.OperatorStop(signal.SIGTERM)
        self.run_fake(loop)
        mode = (self.state / 'live-worker-runtime.json').stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == '__main__':
    unittest.main()
