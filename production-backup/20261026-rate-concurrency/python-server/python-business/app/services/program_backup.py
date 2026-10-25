"""Isolated, asynchronous two-server program snapshots for the version page.

Never stages, resets, checks out or rewrites the running application repository.
Only an independent bare Git object store and a private temporary index are written.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parents[3]
BACKUP_ROOT = Path(os.getenv('CEX_PROGRAM_BACKUP_ROOT', '/home/ec2-user/coin-backups/program-push'))
BRANCH = 'coin'
PREFIX = 'hustlecoin-cex/production-backup/current-programs'
PART_SIZE = 40 * 1024 * 1024
_history_lock = threading.Lock()
_history_cache = None
_history_at = 0.0


def run(args, *, cwd=None, env=None, timeout=120, input=None):
    result = subprocess.run(args, cwd=cwd, env=env, input=input, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # Git can echo an authenticated remote URL. Do not expose credentials in UI/logs.
        detail = result.stderr.decode('utf-8', errors='replace')[-1200:]
        detail = re.sub(r'https://[^/@\s]+@', 'https://[redacted]@', detail)
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {detail}')
    return result.stdout


def git(*args, env=None, timeout=120, input=None):
    base = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Coin Production Backup',
                GIT_AUTHOR_EMAIL='backup@localhost', GIT_COMMITTER_NAME='Coin Production Backup',
                GIT_COMMITTER_EMAIL='backup@localhost')
    key = BACKUP_ROOT / 'github-ed25519'
    if key.is_file():
        base['GIT_SSH_COMMAND'] = ('ssh -i ' + shlex.quote(str(key)) + ' -o IdentitiesOnly=yes'
                                  ' -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10'
                                  ' -o UserKnownHostsFile=' + shlex.quote(str(BACKUP_ROOT / 'github-known-hosts')))
    if env:
        base.update(env)
    return run(['git', '--git-dir', str(BACKUP_ROOT / 'remote.git'), *args], env=base,
               timeout=timeout, input=input)


def prepare_remote():
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Read only the URL; never mutate origin or refs/index in the live repository.
    url = run(['git', '-C', str(PROJECT), 'remote', 'get-url', 'origin'], timeout=10).decode().strip()
    # Dedicated repository deploy key: no account-wide token on the business host.
    if (BACKUP_ROOT / 'github-ed25519').is_file():
        github = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', url)
        if github:
            url = 'ssh://git@ssh.github.com:443/' + github.group(1)
    if not (BACKUP_ROOT / 'remote.git').exists():
        run(['git', 'init', '--bare', str(BACKUP_ROOT / 'remote.git')], timeout=20)
    git('config', 'remote.origin.url', url)
    git('config', 'remote.origin.promisor', 'true')
    git('config', 'remote.origin.partialclonefilter', 'blob:none')
    git('fetch', '--no-tags', '--filter=blob:none', '--depth=30', 'origin',
        f'+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}', timeout=90)
    return git('rev-parse', f'refs/remotes/origin/{BRANCH}').decode().strip()


def atomic_json(path, value):
    temp = path.with_suffix('.tmp-' + uuid.uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def default_message():
    note = PROJECT / 'deploy' / 'latest-repair-summary.txt'
    if note.is_file() and note.read_text(encoding='utf-8').strip():
        return note.read_text(encoding='utf-8').strip()[:500]
    return run(['git', '-C', str(PROJECT), 'log', '-1', '--format=%s'], timeout=10).decode().strip()[:500]


def status(job_id=None):
    if job_id is None:
        latest = BACKUP_ROOT / 'latest.json'
        if not latest.exists():
            return {'status': 'idle', 'default_message': default_message()}
        job_id = json.loads(latest.read_text())['job_id']
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('Invalid backup job id')
    path = BACKUP_ROOT / job_id / 'status.json'
    if not path.is_file():
        raise FileNotFoundError('Backup job not found')
    result = json.loads(path.read_text(encoding='utf-8'))
    if result['status'] in ('queued', 'running'):
        with (BACKUP_ROOT / 'backup.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                result.update(status='error', phase='备份任务已中断，请重试', output='Backup process interrupted')
                atomic_json(path, result)
    result['default_message'] = default_message()
    return result


def start(message=''):
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (BACKUP_ROOT / 'backup.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return status()
    job_id = uuid.uuid4().hex
    folder = BACKUP_ROOT / job_id
    folder.mkdir(mode=0o700)
    initial = {'job_id': job_id, 'status': 'queued', 'progress': 0, 'phase': '准备双服务器程序备份',
               'message': (message.strip() or default_message())[:500],
               'created_at': datetime.now(timezone.utc).isoformat()}
    atomic_json(folder / 'status.json', initial)
    atomic_json(BACKUP_ROOT / 'latest.json', {'job_id': job_id})
    try:
        with (folder / 'worker.log').open('wb') as log:
            subprocess.Popen([sys.executable, '-m', 'app.services.program_backup', job_id, str(lock.fileno())],
                             cwd=str(PROJECT / 'python-business'), pass_fds=(lock.fileno(),),
                             stdout=log, stderr=log, start_new_session=True)
    except Exception:
        initial.update(status='error', phase='无法启动备份任务')
        atomic_json(folder / 'status.json', initial)
        raise
    finally:
        lock.close()
    return initial


def verify_archive(path: Path, role: str):
    with tarfile.open(path, 'r:gz') as archive:
        manifest = json.load(archive.extractfile('snapshot-manifest.json'))
        expected = {row['path']: row for row in manifest['files']}
        if manifest['role'] != role or not expected:
            raise RuntimeError('Host snapshot manifest is invalid')
        for member in archive:
            if member.name == 'snapshot-manifest.json':
                continue
            row = expected.pop(member.name, None)
            if row is None or not member.isfile():
                raise RuntimeError('Unexpected snapshot member')
            digest = hashlib.sha256()
            f = archive.extractfile(member)
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
            if digest.hexdigest() != row['sha256'] or member.size != row['size']:
                raise RuntimeError(f'Checksum mismatch: {member.name}')
        if expected:
            raise RuntimeError('Snapshot is incomplete')
    return manifest


def capture(folder: Path, role: str):
    from app.services.program_snapshot import collect
    target = folder / f'{role}.tar.gz'
    if role == 'python':
        with target.open('wb') as output:
            collect(PROJECT, role, output)
    else:
        host = os.getenv('CEX_RUST_PROBE_HOST', '10.0.1.139')
        key = os.getenv('CEX_BACKUP_RUST_KEY', os.path.expanduser('~/.ssh/cex-trading-key2.pem'))
        project = os.getenv('CEX_RUST_PROJECT_DIR', '/home/ec2-user/coin-project')
        # stdin is Python source, not shell commands; capture stdout bytes directly.
        import shlex
        command = 'python3 - ' + shlex.quote(project) + ' rust'
        with target.open('wb') as output:
            result = subprocess.run(['ssh', '-i', key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                                     '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                                     'ec2-user@' + host, command],
                                    input=Path(__file__).with_name('program_snapshot.py').read_bytes(),
                                    stdout=output, stderr=subprocess.PIPE, timeout=240)
        if result.returncode:
            raise RuntimeError('Rust program capture failed: ' + result.stderr.decode(errors='replace')[-500:])
    return target, verify_archive(target, role)


def split_archive(archive: Path, folder: Path):
    parts = []
    with archive.open('rb') as source:
        index = 0
        while data := source.read(PART_SIZE):
            name = archive.name + f'.part{index:03d}'
            target = folder / name
            target.write_bytes(data)
            parts.append({'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            index += 1
    return parts


def publish(folder, payload, message):
    """Build a child of current GitHub coin without replaying divergent live commits."""
    mirror_lock = (BACKUP_ROOT / 'remote.lock').open('a')
    try:
        fcntl.flock(mirror_lock, fcntl.LOCK_EX)
        base = prepare_remote()
        worktree = folder / 'empty-worktree'
        worktree.mkdir(exist_ok=True)
        env = {'GIT_INDEX_FILE': str(folder / 'publish.index'), 'GIT_WORK_TREE': str(worktree)}
        for attempt in range(3):
            git('read-tree', base, env=env)
            old = git('ls-files', '-z', '--', PREFIX, env=env)
            if old:
                git('update-index', '--force-remove', '-z', '--stdin', env=env, input=old)
            for file in sorted(payload.iterdir()):
                digest = git('hash-object', '-w', str(file)).decode().strip()
                git('update-index', '--add', '--cacheinfo', '100644', digest, f'{PREFIX}/{file.name}', env=env)
            tree = git('write-tree', env=env).decode().strip()
            sha = git('commit-tree', tree, '-p', base, input=(message + '\n').encode()).decode().strip()
            # A plain push is deliberately fast-forward only; concurrent remote commits are retained.
            try:
                git('push', 'origin', f'{sha}:refs/heads/{BRANCH}', timeout=240)
            except RuntimeError:
                new_base = prepare_remote()
                if new_base == base or attempt == 2:
                    raise
                base = new_base
                continue
            remote = git('ls-remote', 'origin', f'refs/heads/{BRANCH}', timeout=30).decode().split()[0]
            if remote != sha:
                # Verify ancestry if someone appended a commit immediately after this push.
                prepare_remote()
                git('merge-base', '--is-ancestor', sha, remote)
            git('update-ref', f'refs/remotes/origin/{BRANCH}', remote)
            return sha
        raise RuntimeError('GitHub branch changed repeatedly; please retry')
    finally:
        mirror_lock.close()


def execute(job_id):
    folder = BACKUP_ROOT / job_id
    state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    def report(progress, phase, **extra):
        state.update(status='running', progress=progress, phase=phase, **extra)
        atomic_json(folder / 'status.json', state)
    try:
        report(5, '核对备份空间与 GitHub 分支')
        if shutil.disk_usage(BACKUP_ROOT).free < 2 * 1024 * 1024 * 1024:
            raise RuntimeError('Insufficient backup workspace disk space')
        payload = folder / 'payload'
        payload.mkdir()
        report(15, '采集 Python 服务器源码和两个域名前端')
        python_tar, python_manifest = capture(folder, 'python')
        report(40, '采集 Rust 服务器源码和实际运行程序')
        rust_tar, rust_manifest = capture(folder, 'rust')
        report(65, '校验全部程序和前端资源')
        hosts = []
        for archive, manifest in ((python_tar, python_manifest), (rust_tar, rust_manifest)):
            parts = split_archive(archive, payload)
            hosts.append({k: manifest[k] for k in ('role', 'host', 'project', 'file_count', 'captured_at')})
            hosts[-1]['parts'] = parts
            atomic_json(payload / (manifest['role'] + '-files.json'), manifest)
        atomic_json(payload / 'manifest.json', {'schema': 1, 'job_id': job_id, 'message': state['message'],
                    'captured_at': datetime.now(timezone.utc).isoformat(), 'hosts': hosts,
                    'domains': ['coin.hustle2026.xyz', 'coinadmin.hustle2026.xyz']})
        (payload / 'README.md').write_text(
            '# 双服务器程序备份\n\n' + state['message'] + '\n\n'
            '当前运行目录的源码、前后端程序、static/dist/public 和 Rust 运行二进制均在对应主机归档内。\n'
            '每个文件和归档分片的 SHA-256 见 manifest.json 与 *-files.json。\n'
            '凭证、数据库、行情数据、依赖缓存和旧备份不在本次程序备份范围。\n\n'
            '恢复到独立目录：先按编号拼接分片，校验 SHA-256，再解压；不要覆盖正在运行的系统。\n'
            '```sh\ncat python.tar.gz.part* > python.tar.gz\ncat rust.tar.gz.part* > rust.tar.gz\n'
            'mkdir python-restore rust-restore\ntar -xzf python.tar.gz -C python-restore\n'
            'tar -xzf rust.tar.gz -C rust-restore\n```\n', encoding='utf-8')
        report(80, '推送完整备份到 GitHub coin 分支')
        sha = publish(folder, payload, state['message'])
        state.update(status='success', progress=100, phase='双服务器程序备份已同步 GitHub',
                     git_commit=sha, short_hash=sha[:8], hosts=hosts, rust_synced=True,
                     completed_at=datetime.now(timezone.utc).isoformat(), output='GitHub branch verified')
        atomic_json(folder / 'status.json', state)
    except Exception as error:
        state.update(status='error', phase='备份未完成', output=str(error)[:1500])
        atomic_json(folder / 'status.json', state)
    finally:
        # Delete only this job's temporary duplicate archives, never any live/dist file.
        for name in ('python.tar.gz', 'rust.tar.gz', 'publish.index'):
            (folder / name).unlink(missing_ok=True)
        # All payloads are reproducible; retain only small audit manifests/status locally.
        # The remote bare store retains published Git objects and prior GitHub commits.
        payload = folder / 'payload'
        if payload.is_dir():
            for part in payload.glob('*.part[0-9][0-9][0-9]'):
                part.unlink()


def history(force=False):
    global _history_cache, _history_at
    latest = status()
    latest_sha = latest.get('git_commit') if latest.get('status') == 'success' else None
    cached_has_latest = not latest_sha or any(r['hash'] == latest_sha for r in (_history_cache or []))
    with _history_lock:
        if _history_cache is not None and time.monotonic() - _history_at < 15 and not force and cached_has_latest:
            return _history_cache
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (BACKUP_ROOT / 'remote.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            prepare_remote()
            raw = git('log', f'refs/remotes/origin/{BRANCH}', '-30', '--format=%H%x00%h%x00%s%x00%an%x00%aI').decode('utf-8')
        result = []
        for line in raw.splitlines():
            fields = line.split('\0')
            if len(fields) == 5:
                result.append(dict(zip(('hash', 'short_hash', 'message', 'author', 'date'), fields)))
        _history_cache, _history_at = result, time.monotonic()
        return result


if __name__ == '__main__':
    # The inherited flock lives until this detached process exits.
    execute(sys.argv[1])
    if len(sys.argv) > 2:
        os.close(int(sys.argv[2]))
