"""Scoped production C Paper profit-cap deployment; no trading or ledger edits."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from dotenv import dotenv_values

ROOT = Path('/home/ec2-user/polymarketbot-auto')
STAGE = ROOT / 'staging/c-paper-profit-20261024'
SOURCE = Path('/home/ec2-user/paper-ab/20261022T020933Z/C')
RELEASE = ROOT / 'releases/c-paper-profit-20261024'
BACKUP = ROOT / 'deploy-backups/c-paper-profit-20261024'
UNIT = Path('/etc/systemd/system/polymarket-auto-btc-paper.service.d/c-strategy.conf')
SERVICES = ['polymarket-auto-btc-paper.service', 'polymarket-auto-dashboard.service']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def assert_originals():
    for source in (STAGE / 'original/bot').glob('*.py'):
        assert digest(source) == digest(SOURCE / 'bot' / source.name), source.name
    for local, target in [('dashboard.py', ROOT / 'server/dashboard.py'),
                          ('run_paper_asset_c.sh', ROOT / 'scripts/run_paper_asset_c.sh')]:
        assert digest(STAGE / 'original' / local) == digest(target), local


def atomic_copy(source, target, mode=0o644):
    temporary = target.with_name(target.name + '.profit-deploy.tmp')
    shutil.copyfile(source, temporary)
    temporary.chmod(mode)
    os.replace(temporary, target)


def prepare():
    assert_originals()
    assert not RELEASE.exists(), 'release already exists; inspect before overwriting'
    assert not BACKUP.exists(), 'backup already exists; preserve it'
    RELEASE.mkdir(parents=True, mode=0o700)
    BACKUP.mkdir(parents=True, mode=0o700)
    shutil.copytree(SOURCE / 'bot', RELEASE / 'bot', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(SOURCE / '.env', RELEASE / '.env')
    (RELEASE / '.env').chmod(0o600)
    for name in ['config.py', 'risk.py', 'main.py', 'paper_profit.py']:
        shutil.copy2(STAGE / 'candidate/bot' / name, RELEASE / 'bot' / name)
    # The strategy/resolver/ledger/order implementations are byte-for-byte C.
    unchanged = {}
    for path in (SOURCE / 'bot').glob('*.py'):
        if path.name not in ['config.py', 'risk.py', 'main.py']:
            assert digest(path) == digest(RELEASE / 'bot' / path.name), path.name
            unchanged[path.name] = digest(path)
    for name, target in [('dashboard.py', ROOT / 'server/dashboard.py'),
                         ('run_paper_asset_c.sh', ROOT / 'scripts/run_paper_asset_c.sh'),
                         ('c-strategy.conf', UNIT)]:
        shutil.copy2(target, BACKUP / name)
    if (ROOT / 'bot/paper_profit.py').exists():
        shutil.copy2(ROOT / 'bot/paper_profit.py', BACKUP / 'paper_profit.py')
    manifest = {
        'source': str(SOURCE), 'release': str(RELEASE),
        'unchanged_modules': unchanged,
        'shadow_hashes': {p.name: digest(p) for p in (SOURCE / 'bot').glob('*.py')},
        'prepared_ts': time.time(),
        'previous_services': {s: run('systemctl', 'show', s, '-p', 'MainPID', '-p', 'ActiveState') for s in SERVICES},
    }
    (BACKUP / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    for path in list((RELEASE / 'bot').glob('*.py')) + [STAGE / 'candidate/dashboard.py']:
        compile(path.read_text(), str(path), 'exec')
    print(json.dumps({'prepared': str(RELEASE), 'backup': str(BACKUP),
                      'unchanged_module_count': len(unchanged)}))


def activate():
    assert_originals()
    assert RELEASE.exists() and (BACKUP / 'manifest.json').exists()
    assert digest(RELEASE / '.env') == digest(SOURCE / '.env'), 'C parameters changed'
    settings = dotenv_values(RELEASE / '.env')
    assert float(settings['MAX_DAILY_REALIZED_PROFIT_FRACTION']) == 0.12
    assert float(settings['PAPER_EQUITY_USD']) == 100.0
    assert float(settings['MAX_DAILY_REALIZED_PROFIT_USD']) == 0.0
    started = time.time()
    try:
        atomic_copy(RELEASE / 'bot/paper_profit.py', ROOT / 'bot/paper_profit.py')
        atomic_copy(STAGE / 'candidate/dashboard.py', ROOT / 'server/dashboard.py')
        atomic_copy(STAGE / 'candidate/run_paper_asset_c.sh', ROOT / 'scripts/run_paper_asset_c.sh', 0o755)
        run('sudo', 'install', '-m', '644', str(STAGE / 'candidate/c-strategy.conf'), str(UNIT))
        run('sudo', 'systemctl', 'daemon-reload')
        for service in SERVICES:
            run('sudo', 'systemctl', 'restart', service)
        snapshot = None
        for _ in range(20):
            try:
                snapshot = json.load(urllib.request.urlopen('http://127.0.0.1:8887/api/state', timeout=5))
                if snapshot.get('bot_mode') == 'paper' and snapshot.get('bot_running'):
                    break
            except Exception:
                pass
            time.sleep(1)
        assert snapshot and snapshot.get('bot_mode') == 'paper' and snapshot.get('bot_running'), 'Paper dashboard health'
        for service in SERVICES:
            assert run('systemctl', 'is-active', service) == 'active', service
        worker_pid = run('systemctl', 'show', SERVICES[0], '-p', 'MainPID', '--value')
        proc = Path('/proc') / worker_pid
        assert (proc / 'cwd').resolve() == RELEASE
        argv = (proc / 'cmdline').read_bytes().split(b'\0')
        assert b'--live' not in argv
        env = dict(item.split(b'=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
        assert env.get(b'TRADES_DB_PATH') == str(ROOT / 'trades-auto.db').encode()
        assert env.get(b'BTC_LIVE_ENABLED') == b'false'
        assert env.get(b'MAX_DAILY_REALIZED_PROFIT_FRACTION') == b'0.12'
        assert env.get(b'PAPER_EQUITY_USD') == b'100'
        manifest = json.loads((BACKUP / 'manifest.json').read_text())
        for name, expected in manifest['shadow_hashes'].items():
            assert digest(SOURCE / 'bot' / name) == expected, 'shadow source changed'
        result = {'deployed_ts': time.time(), 'elapsed_sec': round(time.time() - started, 2),
                  'worker_pid': worker_pid, 'mode': snapshot['bot_mode'],
                  'risk_state': snapshot.get('risk_state'),
                  'risk_snapshot': snapshot.get('risk_snapshot'),
                  'paper_btc': snapshot.get('mode_split', {}).get('paper', {}).get('by_asset', {}).get('BTC')}
        (BACKUP / 'deployment-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    except Exception:
        atomic_copy(BACKUP / 'dashboard.py', ROOT / 'server/dashboard.py')
        atomic_copy(BACKUP / 'run_paper_asset_c.sh', ROOT / 'scripts/run_paper_asset_c.sh', 0o755)
        run('sudo', 'install', '-m', '644', str(BACKUP / 'c-strategy.conf'), str(UNIT))
        run('sudo', 'systemctl', 'daemon-reload')
        for service in SERVICES:
            run('sudo', 'systemctl', 'restart', service)
        print('Activation failed: previous launcher, dashboard and unit restored; ledgers untouched.', file=sys.stderr)
        raise


if __name__ == '__main__':
    {'prepare': prepare, 'activate': activate}[sys.argv[1]]()
