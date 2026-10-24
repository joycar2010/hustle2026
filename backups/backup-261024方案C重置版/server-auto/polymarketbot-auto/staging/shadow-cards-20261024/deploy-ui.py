"""Publish only UI sources and new hashed bundles, preserving every old asset."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

ROOT = Path('/home/ec2-user/polymarketbot-auto')
STAGE = ROOT / 'staging/shadow-cards-20261024'
BUILT = STAGE / 'ui/dist'
WEB = Path('/var/www/polyauto.hustle2026.xyz')
DIST = ROOT / 'ui/dist'
BACKUP = ROOT / 'deploy-backups/shadow-cards-20261024'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.shadow-ui.tmp')
    shutil.copy2(source, temp)
    temp.chmod(0o644)
    os.replace(temp, target)


def manifest(root):
    return {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}


assert not BACKUP.exists(), 'preserve existing backup'
for name in ['App.tsx', 'index.css']:
    assert sha(ROOT / 'ui/src' / name) == sha(STAGE / 'original' / name), name
assert 'A/B/C' in (STAGE / 'ui/src/App.tsx').read_text()
BACKUP.mkdir(parents=True, mode=0o700)
for source, name in [(DIST, 'ui-dist'), (WEB, 'webroot')]:
    shutil.copytree(source, BACKUP / name, symlinks=True)
for name in ['App.tsx', 'index.css']:
    shutil.copy2(ROOT / 'ui/src' / name, BACKUP / name)
before = {'ui-dist': manifest(DIST), 'webroot': manifest(WEB)}
(BACKUP / 'before-manifest.json').write_text(json.dumps(before, indent=2))

try:
    # Assets first, index last: old tabs can still fetch all prior bundle names.
    for destination in [DIST, WEB]:
        for source in (BUILT / 'assets').iterdir():
            if source.suffix not in ('.js', '.css'):
                continue
            target = destination / 'assets' / source.name
            if target.exists():
                assert sha(target) == sha(source), 'hashed asset collision'
            else:
                atomic_copy(source, target)
    for name in ['App.tsx', 'index.css']:
        atomic_copy(STAGE / 'ui/src' / name, ROOT / 'ui/src' / name)
    for destination in [DIST, WEB]:
        atomic_copy(BUILT / 'index.html', destination / 'index.html')
    for name, root in [('ui-dist', DIST), ('webroot', WEB)]:
        for relative, digest in before[name].items():
            if relative != 'index.html':
                assert (root / relative).exists() and sha(root / relative) == digest, relative
    result = {'deployed_ts': time.time(), 'backup': str(BACKUP),
              'old_asset_files_preserved': sum(len(v) - 1 for v in before.values()),
              'new_assets': [p.name for p in (BUILT / 'assets').glob('*')],
              'index_sha256': sha(WEB / 'index.html')}
    (BACKUP / 'deployment.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
except Exception:
    for name in ['App.tsx', 'index.css']:
        atomic_copy(BACKUP / name, ROOT / 'ui/src' / name)
    atomic_copy(BACKUP / 'ui-dist/index.html', DIST / 'index.html')
    atomic_copy(BACKUP / 'webroot/index.html', WEB / 'index.html')
    raise
