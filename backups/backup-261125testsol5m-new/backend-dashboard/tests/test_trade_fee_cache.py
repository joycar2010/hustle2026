import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from server.trade_fee_cache import ReceiptFeeCache


WALLET = '0x' + '12' * 20
OTHER = '0x' + '34' * 20
TX = '0x' + 'ab' * 32
ROW = dict(type='TRADE', transaction_hash=TX, token_id='123', side='BUY', size=5.)


def resolve(row, events, trades, wallet, **kwargs):
    return dict(fee_usd=-.08085, fee_status='confirmed') if events else None


class FeeCacheTests(unittest.TestCase):
    def cache(self, folder, loader, decoder=None, trades=None):
        cache = ReceiptFeeCache(folder, loader, decoder or (lambda receipt, wallet: [{'wallet': wallet}]),
                                trades or (lambda: []), resolve, retry_seconds=30)
        self.addCleanup(cache.pool.shutdown, wait=True)
        return cache

    def test_cold_page_returns_pending_without_waiting_for_rpc_then_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            gate = threading.Event()
            self.addCleanup(gate.set)
            def load(tx):
                gate.wait(2)
                return dict(transactionHash=tx, status='0x1')
            cache = self.cache(folder, load)
            started = time.monotonic()
            cold = cache.snapshot([ROW], [ROW], WALLET)
            self.assertLess(time.monotonic() - started, .1)
            self.assertEqual(cold[0]['fee_status'], 'pending')
            gate.set()
            cache.pool.shutdown(wait=True)
            warm = cache.snapshot([ROW], [ROW], WALLET)
            self.assertEqual(warm[0]['fee_usd'], -.08085)
            data = json.loads(next(Path(folder).glob('*.json')).read_text())
            self.assertEqual(data['wallet'], WALLET)

    def test_outage_or_wrong_receipt_cannot_become_zero_fee(self):
        with tempfile.TemporaryDirectory() as folder:
            attempts = []
            def load(tx):
                attempts.append(tx)
                return dict(transactionHash='0x' + 'cd' * 32, status='0x1')
            cache = self.cache(folder, load)
            cache.snapshot([ROW, ROW], [ROW], WALLET)
            cache.pool.shutdown(wait=True)
            rows = cache.snapshot([ROW], [ROW], WALLET)
            self.assertEqual(attempts, [TX])
            self.assertIsNone(rows[0]['fee_usd'])
            self.assertEqual(rows[0]['fee_status'], 'pending')
            self.assertFalse(list(Path(folder).glob('*.json')))

    def test_disk_cache_survives_dashboard_restart_and_is_wallet_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = self.cache(folder, lambda tx: dict(transactionHash=tx, status='0x1'))
            cache.snapshot([ROW], [ROW], WALLET)
            cache.pool.shutdown(wait=True)
            reads = []
            def unavailable(tx):
                reads.append(tx)
                raise ValueError('Provider offline')
            restarted = self.cache(folder, unavailable)
            rows = restarted.snapshot([ROW], [ROW], WALLET)
            self.assertEqual(rows[0]['fee_usd'], -.08085)
            self.assertEqual(reads, [])
            other = restarted.snapshot([ROW], [ROW], OTHER)
            self.assertIsNone(other[0]['fee_usd'])
            restarted.pool.shutdown(wait=True)
            self.assertEqual(reads, [TX])

    def test_redemption_is_not_a_zero_taker_fee_and_invalid_hash_is_not_fetched(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            cache = self.cache(folder, lambda tx: calls.append(tx))
            redemption = dict(ROW, type='REDEEM')
            invalid = dict(ROW, transaction_hash='not-a-hash')
            result = cache.snapshot([redemption, invalid], [redemption, invalid], WALLET)
            cache.pool.shutdown(wait=True)
            self.assertEqual(result[0]['fee_status'], 'not_applicable')
            self.assertIsNone(result[0]['fee_usd'])
            self.assertEqual(result[1]['fee_status'], 'pending')
            self.assertEqual(calls, [])

    def test_persistence_failure_keeps_verified_memory_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            file_instead_of_dir = Path(folder) / 'read-only-cache'
            file_instead_of_dir.write_text('not a directory')
            cache = self.cache(file_instead_of_dir, lambda tx: dict(transactionHash=tx, status='0x1'))
            cache.snapshot([ROW], [ROW], WALLET)
            cache.pool.shutdown(wait=True)
            self.assertEqual(cache.snapshot([ROW], [ROW], WALLET)[0]['fee_usd'], -.08085)


if __name__ == '__main__':
    unittest.main()
