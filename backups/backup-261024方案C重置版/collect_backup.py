"""Online dual-domain backup: exact encrypted files + reviewable sanitized source."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import tarfile
import time
from dotenv import dotenv_values

LABEL = '261024方案C重置版'
BASE = Path('/home/ec2-user/backups/poly-261024-c-reset')
PUB = BASE / 'publish'
PRIVATE = BASE / 'private'
ROOTS = {
    'server-main/polymarketbot': Path('/home/ec2-user/polymarketbot'),
    'server-auto/polymarketbot-auto': Path('/home/ec2-user/polymarketbot-auto'),
    'paper-shadow/20261022T020933Z': Path('/home/ec2-user/paper-ab/20261022T020933Z'),
    'web-roots/poly.hustle2026.xyz': Path('/var/www/poly.hustle2026.xyz'),
    'web-roots/polyauto.hustle2026.xyz': Path('/var/www/polyauto.hustle2026.xyz'),
}
os.umask(0o077)
BASE.mkdir(exist_ok=False)
PUB.mkdir()
PRIVATE.mkdir()
START = time.time()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def entries(root):
    # rglob does not descend symlink directories: preserve links in the archive.
    return sorted(root.rglob('*'))


def files(root):
    return [p for p in entries(root) if p.is_file() and not p.is_symlink()]


def frontend_manifest():
    result = {}
    for prefix, root in ROOTS.items():
        for p in files(root):
            rel = p.relative_to(root)
            in_dist = any('dist' in part.lower() for part in rel.parts[:-1])
            if (prefix.startswith('web-roots/') or in_dist) and not any(x in rel.parts for x in ['node_modules', '.venv', '.git']):
                result[f'{prefix}/{rel.as_posix()}'] = sha(p)
    return result


def service_state():
    units = subprocess.check_output(['systemctl', 'list-unit-files', 'polymarket*', '--no-legend', '--no-pager'], text=True)
    names = [line.split()[0] for line in units.splitlines() if line.strip()]
    return subprocess.check_output(['systemctl', 'show', *names, '-p', 'Id', '-p', 'ActiveState', '-p', 'UnitFileState', '-p', 'MainPID'])


def critical_service_state():
    return subprocess.check_output(['systemctl', 'show', 'polymarket-dashboard.service',
        'polymarket-auto-dashboard.service', 'polymarket-auto-btc-paper.service',
        'polymarket-auto-openclaw-paper.service', '-p', 'Id', '-p', 'ActiveState', '-p', 'MainPID'])


front_before = frontend_manifest()
service_before = service_state()
critical_before = critical_service_state()
write_json(PRIVATE / 'frontend-before.json', front_before)
print('Inventory: frontend files', len(front_before), flush=True)

# Gather current and retired credentials internally; never print their values.
secret_name = re.compile(r'PRIVATE.?KEY|SECRET|PASSPHRASE|PASSWORD|TOKEN|API.?KEY|MNEMONIC|SEED', re.I)
known = set()
for root in ROOTS.values():
    for p in files(root):
        if '.env' not in p.name:
            continue
        for key, value in dotenv_values(p, interpolate=False).items():
            if value and secret_name.search(key) and len(value) >= 8 and not re.fullmatch(r'[0-9.]+', value):
                if not any(s in value.lower() for s in ['your_', 'replace_', 'changeme', 'example']):
                    known.add(value.encode())
PATTERNS = {
    'private_key': re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
    'api_token': re.compile(rb'\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    'credential_url': re.compile(rb'(?:https?|postgres(?:ql)?|mysql|rediss?|amqps?)://[^\s/"\']+:[^\s/@"\']+@'),
    'secret_literal': re.compile(rb'(?i)(?:PRIVATE_KEY|API_SECRET|API_KEY|PASSPHRASE|DASHBOARD_CONTROL_TOKEN|PASSWORD|SECRET|MNEMONIC)["\']?\s*[=:]\s*["\']([A-Za-z0-9_+/.=-]{16,})["\']'),
}


def has_secrets(data):
    return any(x in data for x in known) or any(p.search(data) for p in PATTERNS.values())


def redact(data):
    for secret in sorted(known, key=len, reverse=True):
        data = data.replace(secret, b'[REDACTED]')
    for pattern in PATTERNS.values():
        data = pattern.sub(b'[REDACTED]', data)
    return data


# Every SQLite file is detected by its header, including .bak and odd filenames.
# Only immutable snapshots enter the archive; committed WAL pages are included.
db_map, db_manifest = {}, []
for prefix, root in ROOTS.items():
    for src in files(root):
        if src.name.endswith(('-wal', '-shm')):
            continue
        with src.open('rb') as stream:
            if stream.read(16) != b'SQLite format 3\x00':
                continue
        arcname = f'{prefix}/{src.relative_to(root).as_posix()}'
        snapshot = PRIVATE / 'database' / arcname
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(src.as_uri() + '?mode=ro', uri=True, timeout=20) as source:
            # Fix a WAL read snapshot so ongoing trading cannot repeatedly
            # invalidate a multi-page backup. Source remains read-only.
            source.execute('BEGIN')
            source.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
            with sqlite3.connect(snapshot) as target:
                source.backup(target, pages=4096, sleep=0.02)
                assert [r[0] for r in target.execute('PRAGMA quick_check')] == ['ok'], arcname
                counts = {name: target.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                          for (name,) in target.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        db_map[src] = snapshot
        db_manifest.append({'archive_path': arcname, 'source_path': str(src), 'bytes': snapshot.stat().st_size,
                            'sha256': sha(snapshot), 'quick_check': 'ok', 'tables': counts,
                            'snapshot_completed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'storage': 'encrypted archive only'})
        print('SQLite snapshot verified:', arcname, flush=True)

source_manifest, private_only, redacted_paths = {}, [], []
skip_parts = {'.venv', 'node_modules', '__pycache__', '.pytest_cache', '.git', 'logs'}
media = {'.png', '.jpg', '.jpeg', '.ico', '.webp', '.gif', '.mp3', '.mp4', '.woff', '.woff2', '.ttf'}


def windows_safe(rel):
    return all(not re.search(r'[<>:"\\|?*]', p) and not p.endswith((' ', '.')) for p in rel.parts)


for prefix, root in ROOTS.items():
    for src in files(root):
        rel = src.relative_to(root)
        arcname = f'{prefix}/{rel.as_posix()}'
        reason = None
        if any(p in skip_parts for p in rel.parts): reason = 'dependencies/cache/log/git'
        elif src in db_map or src.name.endswith(('-wal', '-shm', '.pid', '.pyc', '.log', '.jsonl')): reason = 'runtime/database'
        elif '.env' in src.name or src.suffix in ['.pem', '.key', '.p12', '.pfx'] or 'metamask' in src.name.lower(): reason = 'private configuration'
        elif src.suffix.lower() in ['.zip', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.enc', '.db']: reason = 'nested archive/database'
        elif src.name in ['bot.mode', 'openclaw-heartbeat.json'] or ('agents' in rel.parts and 'out' in rel.parts): reason = 'runtime state'
        elif not windows_safe(rel): reason = 'Windows-incompatible path (original retained encrypted)'
        if reason:
            private_only.append({'path': arcname, 'reason': reason})
            continue
        data = src.read_bytes()
        if b'\x00' in data and src.suffix.lower() not in media:
            private_only.append({'path': arcname, 'reason': 'binary original'})
            continue
        if has_secrets(data):
            if arcname in front_before:
                raise RuntimeError('Credential in frontend; keep full file encrypted, review before publishing: ' + arcname)
            if b'\x00' in data:
                private_only.append({'path': arcname, 'reason': 'private binary'})
                continue
            data = redact(data)
            redacted_paths.append(arcname)
        dest = PUB / arcname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        source_manifest[arcname] = sha(dest)
    # Configuration schema only. Exact settings are inside the encrypted archive.
    env = root / '.env'
    if env.exists():
        dest = PUB / prefix / 'environment.redacted'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('\n'.join(str(k) + '=[REDACTED]' for k in dotenv_values(env, interpolate=False)) + '\n')
        source_manifest[str(dest.relative_to(PUB))] = sha(dest)

ops_files = [Path('/etc/nginx/nginx.conf'), Path('/etc/nginx/conf.d/poly.conf'), Path('/etc/nginx/conf.d/polyauto.conf'),
             Path('/etc/letsencrypt/options-ssl-nginx.conf'), Path('/etc/letsencrypt/ssl-dhparams.pem'),
             Path('/home/ec2-user/paper-ab/LATEST')]
for p in Path('/etc/systemd/system').glob('polymarket*'):
    ops_files.extend(files(p) if p.is_dir() else [p])
ops_files = sorted(set(p for p in ops_files if p.is_file()))
for p in ops_files:
    dest = PUB / 'ops' / p.relative_to('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(redact(p.read_bytes()))
    source_manifest[str(dest.relative_to(PUB))] = sha(dest)

write_json(PUB / 'database-manifest.json', db_manifest)
write_json(PUB / 'source-manifest.json', source_manifest)
write_json(PUB / 'frontend-manifest.json', front_before)
write_json(PUB / 'private-only-paths.json', private_only)
write_json(PUB / 'redacted-source-paths.json', redacted_paths)
(PUB / 'services-before.txt').write_bytes(redact(service_before))

# Stream the complete original tree into authenticated encryption. Only SQLite
# sources are substituted with consistent snapshots; WAL/SHM are unnecessary.
key_file = PRIVATE / 'restore.key'
key_file.write_text(secrets.token_hex(32) + '\n')
key_file.chmod(0o600)
encrypted = PUB / 'poly-complete.tar.gz.enc'
encrypt = subprocess.Popen(['openssl', 'enc', '-aes-256-cbc', '-salt', '-pbkdf2', '-iter', '200000',
                            '-pass', 'file:' + str(key_file), '-out', str(encrypted)], stdin=subprocess.PIPE)
expected = {}


class HashReader:
    def __init__(self, stream): self.stream, self.hash = stream, hashlib.sha256()
    def read(self, n=-1):
        data = self.stream.read(n)
        self.hash.update(data)
        return data


with tarfile.open(fileobj=encrypt.stdin, mode='w|gz') as archive:
    def add(src, arcname):
        origin = src
        src = db_map.get(src, src)
        info = archive.gettarinfo(str(origin), arcname)
        if src != origin:
            # Snapshot contents include WAL, but deployment ownership/mode
            # must come from the original database, not the sudo backup user.
            info.size = src.stat().st_size
        entry = {'size': info.size, 'type': info.type.decode(), 'link': info.linkname,
                 'uid': info.uid, 'gid': info.gid, 'mode': info.mode & 0o7777}
        if info.isfile():
            with src.open('rb') as stream:
                reader = HashReader(stream)
                archive.addfile(info, reader)
                entry['sha256'] = reader.hash.hexdigest()
        elif info.isdir() or info.issym() or info.islnk():
            archive.addfile(info)
        else:
            raise RuntimeError('Unsupported runtime special file: ' + str(origin))
        expected[info.name] = entry

    for prefix, root in ROOTS.items():
        add(root, prefix)
        for src in entries(root):
            if src.name.endswith(('-wal', '-shm')): continue
            add(src, f'{prefix}/{src.relative_to(root).as_posix()}')
        print('Encrypted tree:', prefix, flush=True)
    for src in ops_files: add(src, 'ops/' + str(src.relative_to('/')))
    for domain in ['poly.hustle2026.xyz', 'polyauto.hustle2026.xyz']:
        for kind in ['live', 'archive']:
            root = Path('/etc/letsencrypt') / kind / domain
            for src in entries(root): add(src, 'ops/' + str(src.relative_to('/')))
        p = Path('/etc/letsencrypt/renewal') / (domain + '.conf')
        if p.exists(): add(p, 'ops/' + str(p.relative_to('/')))
encrypt.stdin.close()
assert encrypt.wait() == 0, 'encryption failed'
mac_key = hmac.new(key_file.read_bytes().strip(), b'polyauto-backup-auth-v1', hashlib.sha256).digest()
mac = hmac.new(mac_key, digestmod=hashlib.sha256)
with encrypted.open('rb') as stream:
    for data in iter(lambda: stream.read(1024 * 1024), b''): mac.update(data)
(PUB / 'poly-complete.tar.gz.enc.hmac').write_text(mac.hexdigest() + '\n')
write_json(PRIVATE / 'encrypted-archive-manifest.json', expected)
print('Encrypted archive bytes:', encrypted.stat().st_size, flush=True)

decrypt = subprocess.Popen(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                            '-pass', 'file:' + str(key_file), '-in', str(encrypted)], stdout=subprocess.PIPE)
verified = set()
with tarfile.open(fileobj=decrypt.stdout, mode='r|gz') as archive:
    for member in archive:
        entry = expected[member.name]
        assert member.type.decode() == entry['type'] and member.linkname == entry['link'], member.name
        assert (member.uid, member.gid, member.mode) == (entry['uid'], entry['gid'], entry['mode']), member.name
        if member.isfile():
            value = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
            assert value.hexdigest() == entry['sha256'] and member.size == entry['size'], member.name
        verified.add(member.name)
decrypt.stdout.read()
assert decrypt.wait() == 0 and verified == set(expected), 'decryption verification failed'
for item in db_manifest: assert expected[item['archive_path']]['sha256'] == item['sha256']

# Recheck exact frontend bytes both on the host and in the public backup.
assert front_before == frontend_manifest(), 'frontend changed during snapshot'
for path, value in front_before.items():
    assert (PUB / path).is_file() and sha(PUB / path) == value, path
service_after = service_state()
(PUB / 'services-after.txt').write_bytes(redact(service_after))
critical_after = critical_service_state()
assert critical_before == critical_after, 'persistent production service changed during backup; review'
(PUB / 'persistent-services-before.txt').write_bytes(critical_before)
(PUB / 'persistent-services-after.txt').write_bytes(critical_after)
for p in files(PUB):
    if p == encrypted or p.name.endswith('.hmac'): continue
    assert not has_secrets(p.read_bytes()), 'Publish secret scan hit: ' + str(p.relative_to(PUB))

write_json(PUB / 'backup-manifest.json', {
    'label': LABEL, 'host': '18.179.50.168', 'domains': ['poly.hustle2026.xyz', 'polyauto.hustle2026.xyz'],
    'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(START)),
    'completed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'sqlite_databases': len(db_manifest), 'archive_members': len(verified),
    'frontend_files': len(front_before), 'frontend_unchanged': True,
    'service_state_unchanged': service_before == service_after, 'persistent_services_unchanged': True,
    'service_note': 'Timer-driven agents may start/finish naturally; no service start/stop/restart was issued by this backup.',
    'secret_scan_hits': 0, 'source_files': len(source_manifest), 'redacted_files': len(redacted_paths),
    'archive_sha256': sha(encrypted), 'archive_bytes': encrypted.stat().st_size,
    'archive_roundtrip_verified': True, 'encryption': 'AES-256-CBC/PBKDF2-SHA256-200000 + encrypt-then-HMAC-SHA256',
    'restore_key_server': str(key_file),
    'production_btc_source': '/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024',
    'production_btc_database': '/home/ec2-user/polymarketbot-auto/trades-auto.db',
})
print('BACKUP VERIFIED:', PUB, flush=True)
