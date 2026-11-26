"""Polytest product runner. Imports the strategy selected by the unit's PYTHONPATH."""
import argparse
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import time

from btc5m.book import fetch_book
from btc5m.config import load
from btc5m.engine import Engine
from btc5m.fees import taker_fee_usd
from btc5m.markets import fetch_market_by_slug
from btc5m.risk import beijing_day_start_ts, note_resolution


ROOT = Path('/home/ec2-user/polymarketbot-test')
STATE = ROOT / 'state/products'
LEDGERS = {
    'btc5m': ROOT / 'state/paper-native-a/data/paper.db',
    'btc15m': STATE / 'btc15m/data/paper_btc15m.db',
    'sol5m': ROOT / 'releases/polytest-sol5m-20261121T140426Z/data/paper_sol5m.db',
}
EXTRA = {'daily_profit_limit_usd', 'stop_loss_fraction', 'per_trade_risk_fraction', 'paper_slippage_ticks'}


def read_config(directory):
    base = json.loads((directory / 'base.json').read_text())
    saved = json.loads((directory / 'paper.json').read_text())
    if saved.keys() - base.keys():
        raise ValueError('Unknown Paper parameter')
    config = {**base, **saved}
    for name, value in config.items():
        if isinstance(base[name], bool):
            if type(value) is not bool:
                raise ValueError(name)
        elif type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(name)
        elif type(base[name]) is int and (value != int(value)):
            raise ValueError(name)
        elif type(base[name]) is int:
            config[name] = int(value)
    if not 0 < config['min_entry_price'] <= config['max_entry_price'] < 1:
        raise ValueError('entry price bounds')
    if not 0 < config['min_t_remaining_sec'] < config['entry_window_sec']:
        raise ValueError('entry time bounds')
    for name in ('stop_loss_fraction', 'per_trade_risk_fraction', 'taker_fee_rate'):
        if not 0 <= config[name] <= 1:
            raise ValueError(name)
    if min(config['paper_slippage_ticks'], config['daily_profit_limit_usd']) < 0:
        raise ValueError('negative Paper cost or profit limit')
    return config


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as handle:
        json.dump(value, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)


class Batch:
    """Store methods normally commit individually. The enclosing transaction commits the fill and position."""
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def commit(self):
        pass


@contextmanager
def transaction(store):
    conn = store.conn
    with conn:
        store.conn = Batch(conn)
        try:
            yield conn
        finally:
            store.conn = conn


class ProductEngine(Engine):
    def __init__(self, cfg, settings):
        self.settings = settings
        super().__init__(cfg, live=False)

    def _hydrate_risk(self):
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(beijing_day_start_ts())
        self.risk.open_positions = len(self.store.open_rows())

    def _execute(self, market, decision):
        self.risk.roll_day()
        limit = self.settings['daily_profit_limit_usd']
        if limit and self.risk.realized_pnl_usd >= limit:
            self.store.log('risk_block', {'reason': 'daily profit limit', 'pnl_usd': self.risk.realized_pnl_usd}, market.market_slug)
            return
        if self.store.conn.execute('SELECT 1 FROM positions WHERE condition_id=? LIMIT 1', (market.condition_id,)).fetchone():
            return
        quoted = decision.price
        price = round(quoted + self.settings['paper_slippage_ticks'] * market.tick_size, 8)
        entry_cap = self.cfg.max_entry_price
        if decision.phase == 'opening_gap':
            entry_cap = min(entry_cap, self.cfg.opening_gap_max_entry_price)
        if price > entry_cap or price >= self.cfg.late_edge_hard_ban_price:
            self.store.log('risk_block', {'reason': 'simulated fill exceeds entry cap', 'fill_price': price}, market.market_slug)
            return
        risk_fraction = self.settings['per_trade_risk_fraction']
        cap = self.cfg.max_order_usd
        if risk_fraction:
            cap = min(cap, self.cfg.paper_bankroll_usd * risk_fraction)
        size = min(decision.size, math.floor((cap + 1e-9) / price))
        if size < market.min_size:
            self.store.log('risk_block', {'reason': 'size below minimum at risk cap'}, market.market_slug)
            return
        with transaction(self.store) as conn:
            previous_fill = conn.execute('SELECT coalesce(max(id),0) FROM fills').fetchone()[0]
            super()._execute(market, replace(decision, price=price, size=size))
            conn.execute("""UPDATE fills SET execution_side='BUY', fee_source='paper_fee_model',
                slippage_source='paper_ticks', slippage_usd=? WHERE id>? AND condition_id=?""",
                (max(0, price - quoted) * size, previous_fill, market.condition_id))

    def _resolve_open(self, market=None):
        super()._resolve_open(market)
        fraction = self.settings['stop_loss_fraction']
        if not fraction:
            return
        for row in self.store.open_rows():
            active = fetch_market_by_slug(self.cfg.gamma_host, row['market_slug'])
            if active is None or active.t_remaining() <= 0:
                continue
            book = fetch_book(self.cfg.clob_host, row['token_id'])
            if book.best_bid is None or book.bid_size < row['size'] or book.best_bid > row['entry_price'] * (1 - fraction):
                continue
            triggered = time.perf_counter()
            price = round(max(0, book.best_bid - self.settings['paper_slippage_ticks'] * active.tick_size), 8)
            size = row['size']
            fee = taker_fee_usd(price, size, self.cfg.taker_fee_rate)
            total_fee = (row['fee_usd'] or 0) + fee
            gross = (price - row['entry_price']) * size
            net = gross - total_fee
            with transaction(self.store):
                self.store.record_fill(market_slug=row['market_slug'], condition_id=row['condition_id'],
                    side=row['side'], token_id=row['token_id'], size=size, price=price, fee_usd=fee,
                    liquidity='taker', strategy='late_edge', dry_run=True, execution_side='SELL',
                    slippage_usd=(book.best_bid-price)*size, fee_source='paper_fee_model',
                    slippage_source='paper_ticks', note='stop_loss')
                self.store.close_position(row['id'], exit_price=price, pnl_usd=gross, fee_usd=total_fee, pnl_net_usd=net)
                self.store.log('stop_exit', {'position_id': row['id'], 'price': price, 'fee_usd': fee, 'pnl_net_usd': net,
                                             'exit_latency_ms': round((time.perf_counter()-triggered)*1000, 3)}, row['market_slug'])
            note_resolution(self.risk, net)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('product', choices=LEDGERS)
    parser.add_argument('--settle-only', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    key = args.product
    directory = STATE / key
    ledger = LEDGERS[key]
    settings = read_config(directory)
    identity = json.loads((directory / 'identity.json').read_text())
    cfg = load(series='btc15m_le' if key == 'btc15m' else key)
    if any(getattr(cfg, field) != identity[field] for field in ('product_key', 'series_slug', 'crypto_asset', 'late_edge_db_name')):
        raise ValueError('product strategy/ledger identity mismatch')
    cfg = replace(cfg, **{k:v for k,v in settings.items() if k not in EXTRA}, data_dir=ledger.parent,
                  paper_bankroll_usd=identity['paper_bankroll_usd'], poll_interval_sec=identity['poll_interval_sec'],
                  price_hosts=identity['price_hosts'], live_trading_enabled=False)
    if any(getattr(cfg,k) for k in ('private_key','api_key','api_secret','api_passphrase')):
        raise ValueError('Paper process received a wallet credential')
    if ledger.name != cfg.late_edge_db_name:
        raise ValueError('ledger mismatch')
    if args.check:
        print(key, cfg.series_slug, ledger)
        return
    if key == 'btc5m':
        os.environ['PAPER_CALIBRATION_FROM_TS'] = str(json.loads((directory / 'cutover.json').read_text())['from_ts'])
    with (directory / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if args.settle_only:
                return
            fcntl.flock(lock, fcntl.LOCK_EX)
        engine = ProductEngine(cfg, settings)
        conn = engine.store.conn
        attributes = {'product_key': key, 'series_slug': cfg.series_slug, 'market_window': cfg.window_sec,
                      'paper_or_live': 'paper', 'mode': cfg.mode}
        with conn:
            for table in ('positions', 'fills', 'events'):
                columns = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
                for name, value in attributes.items():
                    if name not in columns:
                        conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {"INTEGER" if type(value) is int else "TEXT"} DEFAULT {value!r}')
        if args.settle_only:
            Engine._resolve_open(engine)
            return
        atomic_json(directory / 'effective.json', dict(product_key=key, series_slug=cfg.series_slug,
                    pid=os.getpid(), loaded_at=time.time(), config=settings, ledger=str(ledger), mode='paper',
                    live_enabled=False, paper_bankroll_usd=cfg.paper_bankroll_usd, strategy=cfg.mode))
        engine.run()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    main()
