"""Exercise controller scripts against a fake service manager, never real systemd."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'Bash controller integration runs on production Linux')
class ServiceControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        for folder in ('scripts', '.venv/bin', 'fake-bin'):
            (self.project / folder).mkdir(parents=True)
        for name in ('run_live.sh', 'stop_live.sh', 'stop_live_asset.sh'):
            shutil.copy2(ROOT / 'scripts' / name, self.project / 'scripts' / name)
        self.write('.venv/bin/python', '#!/bin/sh\nprintf "%s\\n" "$LIVE_WORKER_SYSTEMD_UNIT"\n')
        self.write('fake-bin/sudo', '#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n')
        self.write('fake-bin/systemctl', '''#!/usr/bin/env python3
import json,os,pathlib,sys
root=pathlib.Path(os.environ['FAKE_PROJECT_ROOT'])
args=sys.argv[1:]
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps(args)+'\\n')
if args[0]=='show':
    if 'WorkingDirectory' in args: print(os.environ.get('FAKE_UNIT_ROOT',str(root)))
    elif 'MainPID' in args: print(os.getppid() if False else os.environ['FAKE_WORKER_PID'] if (root/'active').exists() else '0')
elif args[0]=='is-active': sys.exit(0 if (root/'active').exists() else 3)
elif args[0]=='start':
    (root/'active').write_text('1')
    for name in ('bot.pid','bot_btc.pid'): (root/name).write_text(os.environ['FAKE_WORKER_PID'])
    (root/'bot.mode').write_text('live')
elif args[0]=='stop':
    for name in ('active','bot.pid','bot_btc.pid','bot.mode'): (root/name).unlink(missing_ok=True)
else: sys.exit(2)
''')
        self.env = {**os.environ, 'PATH': str(self.project / 'fake-bin') + os.pathsep + os.environ['PATH'],
                    'LIVE_WORKER_SYSTEMD_UNIT': 'polymarket-test-btc-live.service',
                    'FAKE_PROJECT_ROOT': str(self.project), 'FAKE_WORKER_PID': str(os.getpid())}

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.project / name
        path.write_text(text, encoding='utf-8')
        path.chmod(0o755)

    def run_script(self, name, *args):
        return subprocess.run(['bash', str(self.project / 'scripts' / name), *args],
                              capture_output=True, text=True, env=self.env, timeout=15)

    def calls(self):
        path = self.project / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_start_and_stop_use_service_owner_instead_of_background_child(self):
        start = self.run_script('run_live.sh')
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        self.assertTrue((self.project / 'active').exists())
        self.assertIn(['start', 'polymarket-test-btc-live.service'], self.calls())
        stop = self.run_script('stop_live.sh')
        self.assertEqual(stop.returncode, 0, stop.stdout + stop.stderr)
        self.assertFalse((self.project / 'active').exists())
        self.assertIn(['stop', 'polymarket-test-btc-live.service'], self.calls())

    def test_existing_managed_worker_start_is_idempotent(self):
        self.assertEqual(self.run_script('run_live.sh').returncode, 0)
        again = self.run_script('run_live.sh')
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)

    def test_service_pointing_at_other_release_is_rejected(self):
        self.env['FAKE_UNIT_ROOT'] = '/not-this-release'
        result = self.run_script('run_live.sh')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(any(call[0] in ('start', 'stop') for call in self.calls()))

    def test_different_service_name_cannot_be_started_or_stopped(self):
        self.env['LIVE_WORKER_SYSTEMD_UNIT'] = 'polymarket-auto-btc-paper.service'
        self.assertEqual(self.run_script('run_live.sh').returncode, 2)
        self.assertEqual(self.run_script('stop_live.sh').returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_asset_stop_manages_only_btc(self):
        self.assertEqual(self.run_script('run_live.sh').returncode, 0)
        (self.project / 'unrelated-eth-marker').write_text('untouched')
        eth = self.run_script('stop_live_asset.sh', 'ETH')
        self.assertEqual(eth.returncode, 2)
        self.assertTrue((self.project / 'active').exists())
        btc = self.run_script('stop_live_asset.sh', 'BTC')
        self.assertEqual(btc.returncode, 0, btc.stdout + btc.stderr)
        self.assertFalse((self.project / 'active').exists())
        self.assertTrue((self.project / 'unrelated-eth-marker').exists())


if __name__ == '__main__':
    unittest.main()
