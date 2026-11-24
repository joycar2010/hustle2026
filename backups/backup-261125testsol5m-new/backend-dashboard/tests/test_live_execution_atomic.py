"""The main/independent inventory writers may publish at the same instant."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AtomicInventoryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Validate concurrent rename/fsync on the Linux deployment filesystem')
    def test_concurrent_writes_publish_one_complete_private_snapshot(self):
        tree = ast.parse((ROOT/'bot/live_execution.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_atomic')
        barrier = threading.Barrier(8)
        def overlapping_dump(value, file, **kwargs):
            # Make every writer hold its temporary file simultaneously. The
            # former shared .tmp path deterministically failed this scenario.
            barrier.wait(timeout=5.)
            return json.dump(value, file, **kwargs)
        namespace = {'Path':Path, 'tempfile':tempfile, 'os':os,
                     'json':SimpleNamespace(dump=overlapping_dump)}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'bot/live_execution.py','exec'),namespace)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'positions-current.json'
            records = [{'writer':i,'positions':[i]*500} for i in range(8)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(namespace['_atomic'],target,value) for value in records]
                for future in futures: future.result(timeout=10.)
            actual = json.loads(target.read_text(encoding='utf-8'))
            self.assertIn(actual,records)
            self.assertEqual(list(Path(folder).iterdir()),[target])
            if os.name == 'posix':
                self.assertEqual(target.stat().st_mode & 0o777,0o600)


if __name__=='__main__': unittest.main()
