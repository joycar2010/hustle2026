"""Independent event-driven position protection with one order-writing lane.

Book collection and risk detection never wait for entry discovery, probability
inference or an order's Maker TTL. The order lane remains serialized; an urgent
event interrupts passive waiting and prevents new BUY admission. Network/order
finality still has to be proved before another order can be sent.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time


class PriorityOrderGate:
    def __init__(self):
        self.lock = threading.RLock()
        self.urgent = threading.Event()

    @contextmanager
    def entry(self):
        with self.lock:
            yield not self.urgent.is_set()

    @contextmanager
    def exit(self):
        with self.lock:
            yield


def _publish(path, payload):
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name+'.')
    try:
        os.chmod(temp, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(payload, out, allow_nan=False, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


class IndependentExitSupervisor:
    def __init__(self, streams, *, execute, reconcile, urgent_check,
                 gate=None, max_book_age_sec=1.5, reconcile_sec=2.,
                 rest_refresh_sec=.5, health_path=None, authenticated=True, now=time.time):
        self.streams, self.execute, self.reconcile = streams, execute, reconcile
        self.urgent_check = urgent_check
        self.gate = gate or PriorityOrderGate()
        self.max_age = max(.1, float(max_book_age_sec))
        self.reconcile_sec = max(.2, float(reconcile_sec))
        self.rest_refresh_sec = max(.1, min(float(rest_refresh_sec), self.max_age/2.))
        self.health_path, self.authenticated, self.now = health_path, authenticated, now
        self._stop, self._wake = threading.Event(), threading.Event()
        self._mutex = threading.RLock()
        self._markets = {}
        self._latest = {}
        self._threads = []
        self._health = {'mode':'live' if authenticated else 'paper', 'running':False,
                        'executions':0, 'reconciliations':0, 'error_type':None,
                        'rest_refreshes':0, 'rest_error_type':None, 'exit_book_sources':{},
                        'entry_block_reason':'WS_WARMUP'}

    def update_market(self, market):
        with self._mutex:
            self._markets[market.condition_id] = market
            # Expired holdings belong to the settlement path, never a stale
            # book sale. Retain a short overlap for rollover evidence.
            self._markets = {key:m for key,m in self._markets.items()
                             if m.end_ts > self.now()-30.}
            tokens = [token for m in self._markets.values() for token in (m.up_token,m.down_token)]
            conditions = list(self._markets)
            self._health['exit_book_sources'] = {token:source for token,source
                in self._health['exit_book_sources'].items() if token in tokens}
        self.streams.subscribe(tokens, conditions)
        self._wake.set()

    def start(self):
        if self._threads:
            return
        self.streams.start()
        self._stop.clear()
        self._health['running'] = True
        for name,target in (('watch',self._watch),('execute',self._executor),
                            ('inventory',self._inventory),('rest-recovery',self._rest_recovery)):
            thread = threading.Thread(target=target,name='btc-ws-exit-'+name,daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self):
        self._stop.set(); self._wake.set()
        self.streams.stop()
        for thread in self._threads:
            thread.join(timeout=2.)
        self._health['running'] = False
        self._publish()

    def _publish(self):
        with self._mutex:
            payload = {**self._health, 'updated_at':self.now(), 'markets':list(self._markets),
                       'urgent':self.gate.urgent.is_set(), 'stream':self.streams.health()}
        try:
            _publish(self.health_path,payload)
        except OSError:
            pass

    def health(self):
        with self._mutex:
            return {**self._health, 'urgent':self.gate.urgent.is_set()}

    def entry_block_reason(self):
        health = self.health()
        return ('URGENT_EXIT_PENDING' if health['urgent'] else health.get('entry_block_reason'))

    def exit_book(self, token):
        """Cached-only exit price; fresh WS wins over explicit REST recovery.

        This method performs no HTTP calls, including after the order-writing
        lock has been acquired. REST observations never grant BUY admission.
        """
        snapshot = self.streams.snapshot(token,max_age_sec=self.max_age,allow_rest=True)
        with self._mutex:
            self._health['exit_book_sources'][str(token)] = {
                'source':snapshot.source if snapshot else None,
                'event_ts':snapshot.event_ts if snapshot else None,
                'received_ts':snapshot.received_ts if snapshot else None,
            }
        return snapshot.book if snapshot is not None else None

    def rest_refresh_once(self):
        """Blocking recovery reads, called only by the dedicated REST reader."""
        with self._mutex:
            markets = list(self._markets.values())
        refreshed = 0
        for market in markets:
            if market.end_ts <= self.now():
                continue
            for token in (market.up_token,market.down_token):
                if self._stop.is_set():
                    return refreshed
                if self.streams.latest_book(token,max_age_sec=self.max_age) is not None:
                    continue
                snapshot = self.streams.snapshot(token,max_age_sec=self.max_age,allow_rest=True)
                if snapshot is not None and self.now()-snapshot.received_ts < self.rest_refresh_sec:
                    continue
                try:
                    self.streams.refresh_rest(token,market.condition_id)
                    with self._mutex:
                        self._health['rest_refreshes'] += 1
                        self._health['last_rest_refresh_at'] = self.now()
                        self._health['rest_error_type'] = None
                    refreshed += 1
                    self._wake.set()
                except Exception as exc:
                    # Raw network messages may contain URLs or credentials.
                    with self._mutex:
                        self._health['rest_error_type'] = type(exc).__name__
        return refreshed

    def _rest_recovery(self):
        while not self._stop.is_set():
            try:
                self.rest_refresh_once()
            except Exception as exc:
                with self._mutex:
                    self._health['rest_error_type'] = type(exc).__name__
            self._stop.wait(self.rest_refresh_sec)

    def tick(self):
        """Purely collect cached books and detect urgency; never send an order."""
        with self._mutex:
            markets = [market for market in self._markets.values() if market.end_ts > self.now()]
        snapshots, urgent = {}, False
        complete = bool(markets)
        for market in markets:
            if market.end_ts <= self.now():
                continue
            ws_books = [self.streams.latest_book(token,max_age_sec=self.max_age)
                     for token in (market.up_token,market.down_token)]
            if any(book is None for book in ws_books):
                complete = False
            books = [self.exit_book(token) for token in (market.up_token,market.down_token)]
            # A missing unheld-side book must not delay exit on a fresh held
            # side. The callback handles missing sides without inventing bids.
            if any(book is not None for book in books):
                snapshots[market.condition_id] = (market,*books)
                urgent = bool(self.urgent_check(market,*books)) or urgent
        stream = self.streams.health()
        for channel in (('market','user') if self.authenticated else ('market',)):
            status = stream.get(channel) or {}
            received = status.get('received_at')
            if (not status.get('connected',False) or received is None
                    or not -2. <= self.now()-received <= 25.):
                complete = False
        reason = None if complete else 'WS_DATA_UNAVAILABLE'
        with self._mutex:
            self._latest = snapshots
            self._health.update(entry_block_reason=reason,last_watch_at=self.now())
        # When data is missing, stop new entries and interrupt passive entry
        # waits too. There is no permission to sell on an invented price.
        if urgent or reason:
            self.gate.urgent.set()
        else:
            self.gate.urgent.clear()
        self._wake.set()
        return snapshots

    def _watch(self):
        revision = 0
        while not self._stop.is_set():
            try:
                revision = self.streams.wait(revision,timeout=.25)
                self.tick()
            except Exception as exc:
                self.gate.urgent.set()
                self._health.update(error_type=type(exc).__name__,entry_block_reason='WS_WATCH_FAILED')
            self._publish()

    def execute_once(self):
        with self._mutex:
            snapshots = list(self._latest.values())
        for market,up,down in snapshots:
            if market.end_ts <= self.now():
                continue
            with self.gate.exit():
                # Source may have moved while an entry reconciled/cancelled.
                # Read local caches after taking the order lock; the recovery
                # reader owns all blocking REST I/O.
                up = self.exit_book(market.up_token)
                down = self.exit_book(market.down_token)
                if up is None and down is None:
                    continue
                if self.execute(market,up,down):
                    self._health['executions'] += 1
                self._health['last_execution_check_at'] = self.now()

    def _executor(self):
        while not self._stop.is_set():
            self._wake.wait(timeout=.25); self._wake.clear()
            try:
                self.execute_once()
            except Exception as exc:
                self._health['error_type'] = type(exc).__name__

    def _inventory(self):
        while not self._stop.is_set():
            with self._mutex:
                markets = list(self._markets.values())
            for market in markets:
                if market.end_ts <= self.now():
                    continue
                try:
                    self.reconcile(market)
                    self._health['reconciliations'] += 1
                    self._health['last_reconciliation_at'] = self.now()
                except Exception as exc:
                    self._health['inventory_error_type'] = type(exc).__name__
            self._stop.wait(self.reconcile_sec)
