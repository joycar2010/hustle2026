"""Read-only receipt evidence cache. Fee loading never delays order history."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import threading
import time


class ReceiptFeeCache:
    def __init__(self, directory, load_receipt, decode_receipt, load_trades,
                 resolve_activity, max_workers=6, retry_seconds=30):
        self.directory = Path(directory)
        self.load_receipt = load_receipt
        self.decode_receipt = decode_receipt
        self.load_trades = load_trades
        self.resolve_activity = resolve_activity
        self.retry_seconds = retry_seconds
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="receipt-fees")
        self.lock = threading.RLock()
        self.receipts = {}
        self.pending = set()
        self.retry_at = {}
        self.empty_at = {}
        self.trade_rows = None
        self.trades_at = 0.
        self.trades_wallet = None
        self.trades_loading = False

    @staticmethod
    def _key(wallet, tx):
        wallet, tx = str(wallet).lower(), str(tx).lower()
        if not re.fullmatch(r"0x[0-9a-f]{40}", wallet) or not re.fullmatch(r"0x[0-9a-f]{64}", tx):
            return None
        return wallet, tx

    def _file(self, key):
        # Hash names isolate wallets and cannot traverse the cache directory.
        return self.directory / (hashlib.sha256(":".join(key).encode()).hexdigest() + ".json")

    def _read_disk(self, key):
        try:
            value = json.loads(self._file(key).read_text())
            if value.get("version") == 1 and value.get("wallet") == key[0] and value.get("tx") == key[1]:
                rows = value.get("events")
                if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
                    return rows
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _refresh_receipt(self, key):
        try:
            receipt = self.load_receipt(key[1])
            if (not isinstance(receipt, dict) or str(receipt.get("transactionHash", "")).lower() != key[1]
                    or receipt.get("status") not in (1, "0x1", "0x01")):
                raise ValueError("Receipt is not a confirmed matching transaction")
            events = self.decode_receipt(receipt, key[0])
            if not isinstance(events, list):
                raise ValueError("Invalid receipt fee evidence")
            if not events:
                # Unsupported historical ABI / no own-order event is unknown,
                # not a permanently cached zero. A later decoder can retry.
                with self.lock:
                    self.receipts[key] = []
                    self.empty_at[key] = time.monotonic() + 300.
                return
            with self.lock:
                self.receipts[key] = events
                self.retry_at.pop(key, None)
            # Persist only decoded public evidence. A read-only cache directory
            # must not discard already verified in-memory receipt evidence.
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                target = self._file(key)
                temporary = target.with_suffix(".tmp")
                temporary.write_text(json.dumps(dict(version=1, wallet=key[0], tx=key[1], events=events)))
                temporary.replace(target)
            except OSError:
                pass
        except Exception:
            # An outage is not proof of zero fees. Retry without exposing a URL
            # that may carry a provider API key in an HTTP exception.
            with self.lock:
                self.retry_at[key] = time.monotonic() + self.retry_seconds
        finally:
            with self.lock:
                self.pending.discard(key)

    def _refresh_trades(self, wallet):
        try:
            rows = self.load_trades()
            if not isinstance(rows, list):
                raise ValueError("Invalid authenticated fills")
            with self.lock:
                self.trade_rows, self.trades_wallet = rows, wallet
                self.trades_at = time.monotonic()
        except Exception:
            # Previously verified liquidity roles can still annotate old fills.
            with self.lock:
                self.trades_at = time.monotonic() - 15.
        finally:
            with self.lock:
                self.trades_loading = False

    def snapshot(self, selected, peer_activity, wallet):
        """Queue cold reads and return confirmed evidence or explicit pending."""
        wallet = str(wallet or "").lower()
        now = time.monotonic()
        with self.lock:
            if (self.trades_wallet != wallet or now - self.trades_at > 30.) and not self.trades_loading:
                self.trades_loading = True
                # Metadata is optional: actual fees remain available even if
                # CLOB authentication or liquidity role lookup is unavailable.
                self.pool.submit(self._refresh_trades, wallet)
            trades = list(self.trade_rows or []) if self.trades_wallet == wallet else []
            events_by_tx = {}
            for row in selected:
                if row.get("type") != "TRADE":
                    continue
                key = self._key(wallet, row.get("transaction_hash"))
                if key is None:
                    continue
                if key in self.empty_at and now >= self.empty_at[key]:
                    self.receipts.pop(key, None)
                    self.empty_at.pop(key, None)
                if key not in self.receipts:
                    disk = self._read_disk(key)
                    if disk is not None:
                        self.receipts[key] = disk
                if key in self.receipts:
                    events_by_tx[key[1]] = self.receipts[key]
                elif key not in self.pending and now >= self.retry_at.get(key, 0.):
                    self.pending.add(key)
                    self.pool.submit(self._refresh_receipt, key)
        results = []
        for row in selected:
            if row.get("type") != "TRADE":
                results.append(dict(fee_usd=None, fee_status="not_applicable", fee_source=None,
                                    liquidity_role=None))
                continue
            tx = str(row.get("transaction_hash") or "").lower()
            events = events_by_tx.get(tx)
            evidence = self.resolve_activity(row, events, trades, wallet, peer_activity=peer_activity) if events is not None else None
            results.append(evidence or dict(fee_usd=None, fee_status="pending", fee_source=None,
                                           liquidity_role=None))
        return results
