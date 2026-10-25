"""Read-only program collector; also runs over SSH using only stdlib Python."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

SCOPES = ('frontend', 'frontend-admin', 'python-business', 'rust-engine', 'deploy', 'docs')
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache',
             'target', 'logs', 'backups', 'production-backup', '.mypy_cache'}
SKIP_SUFFIXES = {'.pyc', '.pyo', '.pem', '.key', '.p12', '.pfx', '.dump', '.sqlite', '.sqlite3',
                 '.db', '.session', '.log', '.bak'}


def allowed(path: Path) -> bool:
    """dist/static/public are always included; credentials and runtime data are not."""
    for part in path.parts:
        lower = part.lower()
        if lower in SKIP_DIRS or lower.startswith(('.backup', '.doc6-release', '.env', '.ssh')):
            return False
        if lower in ('secrets', 'credentials') or lower.startswith(('credentials.', 'service-account.')):
            return False
        if lower in ('id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa') or lower.endswith(('.session-journal', '.db-wal', '.db-shm')):
            return False
        if lower.endswith(('.tar.gz', '.tgz', '.dump.gz', '.sql.gz')):
            return False
    return path.suffix.lower() not in SKIP_SUFFIXES


def systemd(service: str) -> dict:
    out = subprocess.run(['systemctl', 'show', service, '-p', 'MainPID', '-p', 'WorkingDirectory', '-p', 'ActiveState'],
                         capture_output=True, text=True, timeout=10, check=True).stdout
    return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)


def collect(root: Path, role: str, stream) -> None:
    root = root.resolve(strict=True)
    required = ['rust-engine/src', 'rust-engine/Cargo.toml'] if role == 'rust' else [
        'frontend/src', 'frontend-admin/src', 'python-business/app', 'python-business/engine',
        'python-business/static/spa/index.html', 'python-business/static/admin-spa/index.html']
    for rel in required:
        if not (root / rel).exists():
            raise RuntimeError(f'Required program source or frontend entry is missing: {rel}')
    services = {name: systemd(name) for name in (
        ['cex-engine.service'] if role == 'rust' else ['cex-business.service', 'cex-worker.service'])}
    records = []
    with tarfile.open(fileobj=stream, mode='w|gz') as archive:
        def add(path: Path, name: str, original: str | None = None):
            # Read each file once. The tar member hash describes the exact captured bytes.
            with path.open('rb') as f:
                before = os.fstat(f.fileno())
                content = f.read()
                after = os.fstat(f.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f'Program changed during backup: {name}; retry after deployment completes')
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(content), before.st_mode & 0o777, int(before.st_mtime)
            archive.addfile(entry, io.BytesIO(content))
            records.append({'path': name, 'source': original or str(path), 'size': len(content),
                            'sha256': hashlib.sha256(content).hexdigest(), 'mode': entry.mode})
        for scope in SCOPES:
            source = root / scope
            if not source.is_dir():
                continue
            for parent, dirs, names in os.walk(source, followlinks=False):
                parent = Path(parent)
                dirs[:] = sorted(d for d in dirs if allowed((parent / d).relative_to(root)))
                for dirname in dirs:
                    if (parent / dirname).is_symlink():
                        raise RuntimeError(f'Program directory link requires explicit backup scope: {parent / dirname}')
                for name in sorted(names):
                    path = parent / name
                    rel = path.relative_to(root)
                    if not allowed(rel) or not path.is_file():
                        continue
                    resolved = path.resolve()
                    if not resolved.is_relative_to(root):
                        raise RuntimeError(f'External program link requires explicit backup scope: {rel}')
                    add(path, 'project/' + rel.as_posix())
        if role == 'python':
            # This live domain asset is served by an nginx alias outside the project.
            logo = Path('/usr/share/nginx/html/coinadmin-logo.png')
            if logo.is_file():
                add(logo, 'runtime/web/coinadmin-logo.png')
        nginx = Path('/etc/nginx/conf.d/coin.conf')
        if nginx.is_file():
            add(nginx, 'runtime/nginx/coin.conf')
        if role == 'rust':
            pid = int(services['cex-engine.service'].get('MainPID', '0'))
            if pid <= 0:
                raise RuntimeError('Cannot capture running Rust executable: no engine PID')
            binary = Path(f'/proc/{pid}/exe')
            add(binary, 'runtime/cex-engine', os.readlink(binary))
        manifest = {'schema': 1, 'role': role, 'project': str(root),
                    'host': '57.181.214.206' if role == 'rust' else '18.176.76.127',
                    'captured_at': datetime.now(timezone.utc).isoformat(), 'services': services,
                    'files': records, 'file_count': len(records),
                    'excluded': 'Credentials, dependencies/build caches, database/market data and historical archives'}
        body = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        entry = tarfile.TarInfo('snapshot-manifest.json')
        entry.size = len(body)
        archive.addfile(entry, io.BytesIO(body))


if __name__ == '__main__':
    collect(Path(sys.argv[1]), sys.argv[2], sys.stdout.buffer)
