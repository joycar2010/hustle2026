"""Isolated Linux tests: no production services, Binance calls or GitHub writes.

Run this file directly with Python. It imports the adjacent service files by
absolute path so it cannot accidentally exercise an installed older version.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SERVICES = Path(__file__).resolve().parents[1] / 'app' / 'services'


def load_service(name):
    spec = importlib.util.spec_from_file_location('tested_' + name, SERVICES / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load_service('program_backup')
snapshot = load_service('program_snapshot')


def command(*args, cwd=None):
    env = dict(os.environ, GIT_AUTHOR_NAME='Isolated Test', GIT_AUTHOR_EMAIL='test@localhost',
               GIT_COMMITTER_NAME='Isolated Test', GIT_COMMITTER_EMAIL='test@localhost',
               GIT_TERMINAL_PROMPT='0')
    return subprocess.run(args, cwd=cwd, env=env, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def write(path, content=b'program content\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class IsolatedGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coin-backup-git-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'upstream.git'
        command('git', 'init', '--bare', str(self.remote))
        self.writer = self.root / 'writer'
        command('git', 'clone', str(self.remote), str(self.writer))
        command('git', 'checkout', '-b', 'coin', cwd=self.writer)
        write(self.writer / 'hustlecoin-cex' / 'frontend' / 'dist' / 'keep.js', b'live remote asset')
        write(self.writer / backup.PREFIX / 'old-backup.part000', b'old archive')
        write(self.writer / 'historical-backups' / 'retain.txt', b'previous approved backup')
        command('git', 'add', '.', cwd=self.writer)
        command('git', 'commit', '-m', 'remote baseline', cwd=self.writer)
        command('git', 'push', 'origin', 'coin', cwd=self.writer)
        self.base = command('git', 'rev-parse', 'HEAD', cwd=self.writer).decode().strip()
        self.live = self.root / 'live'
        command('git', 'clone', '-b', 'coin', str(self.remote), str(self.live))
        write(self.live / 'hustlecoin-cex' / 'live-fix.txt', b'unpublished production fix')
        command('git', 'add', '.', cwd=self.live)
        command('git', 'commit', '-m', 'divergent production repair', cwd=self.live)
        write(self.writer / 'concurrent-remote.txt', b'existing remote-only change')
        command('git', 'add', '.', cwd=self.writer)
        command('git', 'commit', '-m', 'divergent remote repair', cwd=self.writer)
        command('git', 'push', 'origin', 'coin', cwd=self.writer)
        self.remote_base = command('git', 'rev-parse', 'HEAD', cwd=self.writer).decode().strip()
        write(self.live / 'hustlecoin-cex' / 'staged-fix.txt', b'staged work must remain')
        command('git', 'add', '.', cwd=self.live)
        write(self.live / 'hustlecoin-cex' / 'frontend' / 'dist' / 'keep.js', b'dirty live dist')
        write(self.live / 'untracked.txt', b'untracked work must remain')
        # The prior production failure involved unmerged state; publishing must
        # not depend on or repair the application's index/merge state.
        write(self.live / '.git' / 'MERGE_HEAD', (self.base + '\n').encode())
        self.backup_root = self.root / 'backup-workspace'
        self.backup_root.mkdir()
        self.job = self.backup_root / ('a' * 32)
        self.job.mkdir()
        self.payload = self.job / 'payload'
        self.payload.mkdir()
        write(self.payload / 'python.tar.gz.part000', b'python archive')
        write(self.payload / 'rust.tar.gz.part000', b'rust archive')
        write(self.payload / 'manifest.json', b'{"schema": 1}')
        for name, value in [('PROJECT', self.live / 'hustlecoin-cex'),
                            ('BACKUP_ROOT', self.backup_root),
                            ('_history_cache', None), ('_history_at', 0.0)]:
            mock = patch.object(backup, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def live_signature(self):
        return {
            'head': command('git', 'rev-parse', 'HEAD', cwd=self.live),
            'index': (self.live / '.git' / 'index').read_bytes(),
            'merge': (self.live / '.git' / 'MERGE_HEAD').read_bytes(),
            'dist': (self.live / 'hustlecoin-cex' / 'frontend' / 'dist' / 'keep.js').read_bytes(),
            'staged': (self.live / 'hustlecoin-cex' / 'staged-fix.txt').read_bytes(),
            'untracked': (self.live / 'untracked.txt').read_bytes(),
        }

    def remote_file(self, sha, path):
        return command('git', '--git-dir', str(self.remote), 'show', sha + ':' + path)

    def test_publish_preserves_diverged_live_repository_and_remote_history(self):
        before = self.live_signature()
        sha = backup.publish(self.job, self.payload, '修复双服务器备份与历史刷新')
        self.assertEqual(command('git', '--git-dir', str(self.remote), 'rev-parse', 'coin').decode().strip(), sha)
        self.assertEqual(command('git', '--git-dir', str(self.remote), 'rev-parse', sha + '^').decode().strip(), self.remote_base)
        self.assertEqual(self.live_signature(), before)
        self.assertEqual(self.remote_file(sha, 'hustlecoin-cex/frontend/dist/keep.js'), b'live remote asset')
        self.assertEqual(self.remote_file(sha, 'concurrent-remote.txt'), b'existing remote-only change')
        self.assertEqual(self.remote_file(sha, 'historical-backups/retain.txt'), b'previous approved backup')
        paths = command('git', '--git-dir', str(self.remote), 'ls-tree', '-r', '--name-only', sha).decode().splitlines()
        self.assertNotIn(backup.PREFIX + '/old-backup.part000', paths)
        for file in self.payload.iterdir():
            self.assertEqual(self.remote_file(sha, backup.PREFIX + '/' + file.name), file.read_bytes())

    def test_concurrent_remote_commit_is_retained_and_publish_retries(self):
        original_git = backup.git
        concurrent = []
        def race_git(*args, **kwargs):
            if args and args[0] == 'push' and not concurrent:
                write(self.writer / 'concurrent-during-push.txt', b'keep concurrent write')
                command('git', 'add', '.', cwd=self.writer)
                command('git', 'commit', '-m', 'another publisher', cwd=self.writer)
                command('git', 'push', 'origin', 'coin', cwd=self.writer)
                concurrent.append(command('git', 'rev-parse', 'HEAD', cwd=self.writer).decode().strip())
            return original_git(*args, **kwargs)
        before = self.live_signature()
        with patch.object(backup, 'git', side_effect=race_git):
            sha = backup.publish(self.job, self.payload, 'keep concurrent history')
        self.assertEqual(command('git', '--git-dir', str(self.remote), 'rev-parse', sha + '^').decode().strip(), concurrent[0])
        self.assertEqual(self.remote_file(sha, 'concurrent-during-push.txt'), b'keep concurrent write')
        self.assertEqual(self.live_signature(), before)

    def test_history_refreshes_after_verified_job_and_preserves_chinese_subject(self):
        initial = backup.history()
        self.assertEqual(initial[0]['hash'], self.remote_base)
        sha = backup.publish(self.job, self.payload, '提前借币、自定义币种监控召回；修复备份刷新')
        backup.atomic_json(self.job / 'status.json', {'job_id': self.job.name, 'status': 'success', 'git_commit': sha})
        backup.atomic_json(self.backup_root / 'latest.json', {'job_id': self.job.name})
        refreshed = backup.history()
        self.assertEqual(refreshed[0]['hash'], sha)
        self.assertEqual(refreshed[0]['message'], '提前借币、自定义币种监控召回；修复备份刷新')

    def test_remote_error_is_reported_instead_of_empty_successful_history(self):
        with patch.object(backup, 'prepare_remote', side_effect=RuntimeError('network unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'network unavailable'):
                backup.history(force=True)


class JobLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coin-backup-lock-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('BACKUP_ROOT', self.root), ('PROJECT', self.root)]:
            mock = patch.object(backup, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(backup, 'default_message', return_value='最近修复内容')
        mock.start()
        self.addCleanup(mock.stop)

    def test_start_inherits_lock_and_duplicate_start_returns_existing_job(self):
        held = []
        def fake_popen(args, **kwargs):
            self.assertTrue(kwargs['start_new_session'])
            fd = kwargs['pass_fds'][0]
            self.assertEqual(args[-1], str(fd))
            held.append(os.dup(fd))
            return object()
        try:
            with patch.object(backup.subprocess, 'Popen', side_effect=fake_popen) as popen:
                first = backup.start('')
                self.assertEqual(first['message'], '最近修复内容')
                self.assertEqual(backup.status()['status'], 'queued')
                again = backup.start('second duplicate request')
                self.assertEqual(again['job_id'], first['job_id'])
                self.assertEqual(popen.call_count, 1)
        finally:
            for fd in held:
                os.close(fd)
        final = backup.status()
        self.assertEqual(final['status'], 'error')
        self.assertIn('interrupted', final['output'])

    def test_spawn_failure_is_recorded_and_releases_lock(self):
        with patch.object(backup.subprocess, 'Popen', side_effect=OSError('cannot fork')):
            with self.assertRaisesRegex(OSError, 'cannot fork'):
                backup.start('repair summary')
        self.assertEqual(backup.status()['status'], 'error')
        with (self.root / 'backup.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_job_path_traversal_is_rejected(self):
        for unsafe in ('../latest', '/tmp/other', 'x' * 32, ''):
            with self.assertRaises(ValueError):
                backup.status(unsafe)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coin-backup-snapshot-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        files = [
            'frontend/src/App.tsx', 'frontend-admin/src/pages/SystemPage.tsx',
            'python-business/app/main.py', 'python-business/engine/main.py',
            'python-business/static/spa/index.html', 'python-business/static/admin-spa/index.html',
            'frontend/dist/assets/live-user.js', 'frontend-admin/dist/assets/live-admin.js',
            'python-business/static/spa/assets/older-but-loaded.js',
            'python-business/static/admin-spa/assets/older-but-loaded-admin.js',
            'rust-engine/src/main.rs', 'rust-engine/Cargo.toml', 'rust-engine/Cargo.lock',
            'deploy/latest-repair-summary.txt', 'docs/regression-ledger.md',
        ]
        for name in files:
            write(self.root / name, ('source ' + name).encode())
        self.originals = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        mock = patch.object(snapshot, 'systemd', return_value={
            'MainPID': str(os.getpid()), 'WorkingDirectory': str(self.root), 'ActiveState': 'active'})
        mock.start()
        self.addCleanup(mock.stop)

    def capture(self, role='python'):
        target = Path(self.temp.name) / (role + '.tar.gz')
        with target.open('wb') as output:
            snapshot.collect(self.root, role, output)
        return target, backup.verify_archive(target, role)

    def test_both_frontends_all_existing_dist_assets_and_sources_roundtrip(self):
        archive, manifest = self.capture()
        paths = {r['path']: r for r in manifest['files']}
        with tarfile.open(archive) as tar:
            for rel, data in self.originals.items():
                self.assertIn('project/' + rel, paths)
                self.assertEqual(tar.extractfile('project/' + rel).read(), data)
                self.assertEqual((self.root / rel).read_bytes(), data, 'Collector modified live input')
                self.assertEqual(paths['project/' + rel]['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest['file_count'], len(paths))

    def test_secret_runtime_database_and_dependency_files_are_excluded(self):
        excluded = [
            'python-business/.env', 'python-business/.env.production',
            'python-business/secrets/api.json', 'python-business/credentials/binance.json',
            'deploy/id_rsa.pem', 'deploy/session.key',
            'python-business/database.db', 'python-business/cache.sqlite',
            'python-business/logs/private.log', 'python-business/__pycache__/main.pyc',
            'frontend/node_modules/pkg/index.js', 'rust-engine/target/release/cex-engine',
            'frontend/.backup-20260910/dist/index.html',
        ]
        for rel in excluded:
            write(self.root / rel, b'MUST NOT BE INCLUDED')
        _, manifest = self.capture()
        paths = {r['path'] for r in manifest['files']}
        for rel in excluded:
            self.assertNotIn('project/' + rel, paths)

    def test_sql_migrations_remain_program_source(self):
        migration = 'python-business/migrations/20260915_backup_jobs.sql'
        write(self.root / migration, b'ALTER TABLE sample ADD COLUMN example integer;')
        _, manifest = self.capture()
        self.assertIn('project/' + migration, {r['path'] for r in manifest['files']})

    def test_missing_live_frontend_entry_fails_closed(self):
        (self.root / 'python-business/static/admin-spa/index.html').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Required'):
            self.capture()

    def test_external_file_symlink_fails_instead_of_leaking_file(self):
        outside = Path(self.temp.name) / 'outside-secret'
        write(outside, b'private external content')
        (self.root / 'frontend/src/external-link').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'External program link'):
            self.capture()

    def test_directory_symlink_fails_instead_of_silently_omitting_assets(self):
        (self.root / 'frontend/public').symlink_to(self.root / 'frontend/dist', target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'directory link'):
            self.capture()

    def test_rust_captures_executing_binary_even_if_target_build_differs(self):
        write(self.root / 'rust-engine/target/release/cex-engine', b'not the executing binary')
        archive, manifest = self.capture('rust')
        with tarfile.open(archive) as tar:
            actual = tar.extractfile('runtime/cex-engine').read()
        self.assertEqual(actual, Path('/proc/self/exe').read_bytes())
        self.assertNotEqual(actual, b'not the executing binary')
        self.assertIn('runtime/cex-engine', [row['path'] for row in manifest['files']])

    def test_corrupted_archive_is_rejected(self):
        archive, _ = self.capture()
        corrupt = Path(self.temp.name) / 'corrupt.tar.gz'
        with tarfile.open(archive) as src, tarfile.open(corrupt, 'w:gz') as dst:
            changed = False
            for member in src:
                content = src.extractfile(member).read()
                if not changed and member.name != 'snapshot-manifest.json':
                    content = bytes([content[0] ^ 1]) + content[1:]
                    changed = True
                dst.addfile(member, io.BytesIO(content))
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            backup.verify_archive(corrupt, 'python')

    def test_archive_parts_reassemble_to_identical_verified_archive(self):
        archive, original_manifest = self.capture()
        parts_dir = Path(self.temp.name) / 'parts'
        parts_dir.mkdir()
        with patch.object(backup, 'PART_SIZE', 128):
            parts = backup.split_archive(archive, parts_dir)
        self.assertGreater(len(parts), 1)
        result = b''
        for row in parts:
            data = (parts_dir / row['name']).read_bytes()
            self.assertLessEqual(len(data), 128)
            self.assertEqual(row['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(row['size'], len(data))
            result += data
        self.assertEqual(result, archive.read_bytes())
        reassembled = Path(self.temp.name) / 'reassembled.tar.gz'
        reassembled.write_bytes(result)
        self.assertEqual(backup.verify_archive(reassembled, 'python'), original_manifest)

    def test_incomplete_archive_is_rejected(self):
        archive, _ = self.capture()
        missing = Path(self.temp.name) / 'incomplete.tar.gz'
        with tarfile.open(archive) as src, tarfile.open(missing, 'w:gz') as dst:
            skipped = False
            for member in src:
                if not skipped and member.name != 'snapshot-manifest.json':
                    skipped = True
                    continue
                dst.addfile(member, io.BytesIO(src.extractfile(member).read()))
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            backup.verify_archive(missing, 'python')


if __name__ == '__main__':
    unittest.main(verbosity=2)
