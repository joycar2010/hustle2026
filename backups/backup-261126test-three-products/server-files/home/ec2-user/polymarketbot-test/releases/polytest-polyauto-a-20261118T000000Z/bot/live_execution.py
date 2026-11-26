"""Persistent entry intents and authenticated live-wallet reconciliation.

Only the live worker uses this ledger. Paper accounting and historical order
rows are never rewritten. An uncertain submission survives a worker restart.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams, OpenOrderParams, TradeParams

from bot import store
from bot.order_evidence import iter_account_trade_fills
from bot.execution_costs import FeeSchedule
from bot.strategy import TrackedPosition


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            os.chmod(temp, 0o600)
            json.dump(value, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
        if os.name == 'posix':
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(temp).unlink(missing_ok=True)


@contextmanager
def _locked(path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a+') as file:
        os.chmod(path, 0o600)
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def aggregate_positions(fills, balances, *, market, open_orders=(), fee_schedule=None):
    """FIFO the account's actual fills, retaining pending settlement evidence."""
    positions = {}
    buy_ids = set()
    bought_cost = 0.0
    for side, token in (('UP', market.up_token), ('DOWN', market.down_token)):
        token = str(token)
        lots = []
        token_fills = sorted((item for item in fills if str(item['token_id']) == token),
                             key=lambda item: (item['ts'], item['trade_id'], item['order_id']))
        for item in token_fills:
            qty = max(float(item['size']), 0.0)
            if item['side'] == 'BUY':
                role=str(item.get('liquidity_role') or '').upper()
                fee=None;fee_source='fee_schedule_unavailable'
                if role=='MAKER' and isinstance(fee_schedule,FeeSchedule):
                    fee=0.;fee_source='authenticated_maker_zero_protocol'
                elif isinstance(fee_schedule,FeeSchedule):
                    # The trade leg proves price/quantity/role, not the actual
                    # chain fee. Keep protocol computations explicitly labelled
                    # estimates until confirmed per-fill evidence is attached.
                    fee=float(fee_schedule.fee(qty,item['price'],role='TAKER',conservative=True))
                    fee_source=('authenticated_fill_protocol_fee_estimate' if role=='TAKER'
                                else 'unknown_role_conservative_taker_fee_estimate')
                lots.append([qty, float(item['price']), float(item['ts']), item['order_id'],fee,fee_source])
                buy_ids.add(item['order_id'] or item['trade_id'])
                bought_cost += qty * float(item['price'])
            else:
                for lot in lots:
                    consumed = min(lot[0], qty)
                    if lot[0]>0 and lot[4] is not None:
                        lot[4]*=max((lot[0]-consumed)/lot[0],0.)
                    lot[0] -= consumed
                    qty -= consumed
                    if qty <= 1e-9:
                        break
        quantity = sum(lot[0] for lot in lots)
        notional = sum(lot[0] * lot[1] for lot in lots)
        latest = max((float(item['ts']) for item in token_fills), default=0.0)
        pending = any(str(item.get('status') or '').upper() not in ('CONFIRMED', 'MINED') for item in token_fills)
        actual = balances.get(token)
        if actual is None:
            raise ValueError('Conditional token balance unavailable')
        actual = max(float(actual), 0.0)
        # The conditional-balance index and the trade index can lag each
        # other even for CONFIRMED fills. Do not erase bought inventory when
        # the balance temporarily reads zero, or sell the same MATCHED fill
        # twice while its balance decrement is still pending.
        has_buys = any(item['side'] == 'BUY' for item in token_fills)
        mismatch = abs(quantity - actual) > 1e-6
        tracked = quantity if has_buys else actual
        reserved = 0.0
        for order in open_orders:
            if str(order.get('asset_id') or order.get('token_id') or '') != token:
                continue
            if str(order.get('side') or '').upper() == 'SELL':
                original = _number(order.get('original_size'))
                matched = _number(order.get('size_matched'))
                if original is None or matched is None:
                    raise ValueError('Open sell order has no verified remaining quantity')
                if original < 0 or matched < 0 or matched > original + 1e-6:
                    raise ValueError('Open sell reservation has inconsistent quantities')
                reserved += max(original - matched, 0.0)
        average = notional / quantity if quantity > 1e-8 else 0.0
        remaining_lots=[lot for lot in lots if lot[0]>1e-8]
        fee_complete=bool(remaining_lots) and all(lot[4] is not None for lot in remaining_lots)
        entry_fees=sum(lot[4] for lot in remaining_lots) if fee_complete else None
        fee_sources=sorted({lot[5] for lot in remaining_lots})
        if tracked > 1e-8 or actual > 1e-8:
            positions[token] = {'condition_id': market.condition_id, 'token_id': token,
                'side': side, 'size': tracked, 'balance_size': actual,
                'ledger_size': quantity,
                'available_size': max(min(actual, quantity) - reserved, 0.0) if has_buys else max(actual - reserved, 0.0),
                'reserved_size': reserved, 'balance_mismatch': mismatch,
                'price': average, 'entry_ts': min((lot[2] for lot in lots if lot[0] > 1e-8), default=latest),
                'entry_order_id': next((lot[3] for lot in lots if lot[0] > 1e-8), None),
                'entry_cost_remaining_usd': notional,
                'entry_fees_remaining_usd': entry_fees,
                'fee_source': '+'.join(fee_sources) if fee_sources else 'entry_cost_unavailable',
                'fee_estimated': True, 'entry_fee_complete': fee_complete,
                'unpriced': average <= 0, 'settlement_pending': pending}
    return positions, len(buy_ids), bought_cost


class LiveExecutionGuard:
    def __init__(self, cfg, client, *, directory=None):
        self.cfg, self.client = cfg, client
        self.wallet = (cfg.deposit_wallet_address or cfg.funder_address).lower()
        root = Path(__file__).resolve().parent.parent
        self.directory = Path(directory or os.getenv('LIVE_EXECUTION_STATE_DIR', str(root / 'state' / 'execution')))
        self.owners = tuple(str(value).lower() for value in
            (cfg.wallet_address, cfg.funder_address, cfg.deposit_wallet_address) if value)
        self.snapshot = {}
        self.last_error = None

    def _path(self, condition):
        digest = hashlib.sha256((self.wallet + ':' + condition).encode()).hexdigest()
        return self.directory / (digest + '.json')

    def _read(self, condition):
        try:
            value = json.loads(self._path(condition).read_text(encoding='utf-8'))
            if value.get('wallet') != self.wallet or value.get('condition_id') != condition:
                raise ValueError('Entry intent belongs to a different wallet or market')
            return value
        except FileNotFoundError:
            return {}

    def conditional_balance(self, token):
        raw = self.client.get_balance_allowance(BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL, token_id=str(token), signature_type=self.cfg.signature_type))
        amount = _number(raw.get('balance')) if isinstance(raw, dict) else None
        if amount is None or amount < 0:
            raise ValueError('Missing conditional token balance')
        return amount / 1_000_000.0

    def sync(self, current, strategy_state):
        """Rebuild current-window positions; never trust a missing local BUY."""
        fetched = time.time()
        raw = self.client.get_trades(TradeParams(market=current.condition_id,
                        after=int(current.start_ts) - 10), only_first_page=False)
        orders = self.client.get_open_orders(OpenOrderParams(market=current.condition_id), only_first_page=False)
        if not isinstance(raw, list) or not isinstance(orders, list):
            raise ValueError('Incomplete authenticated account snapshot')
        fills = iter_account_trade_fills(raw, owner_addresses=self.owners,
            api_owner=getattr(self.cfg, 'api_key', None), condition_id=current.condition_id)
        balances = {str(token): self.conditional_balance(token) for token in (current.up_token, current.down_token)}
        try:
            fee_schedule=FeeSchedule.from_market(getattr(current,'fee_metadata',None) or {})
        except (ValueError,TypeError):
            fee_schedule=None
        positions, count, cost = aggregate_positions(fills, balances, market=current, open_orders=orders,
                                                     fee_schedule=fee_schedule)
        ambiguous = self._resolve_intent(current.condition_id, fills, orders)
        for side, token in (('UP', current.up_token), ('DOWN', current.down_token)):
            key = (current.condition_id, str(token), side)
            old = strategy_state.local_positions.get(key)
            item = positions.get(str(token))
            token_fills = [fill for fill in fills if str(fill['token_id']) == str(token)]
            if item is None and old is not None and old.remaining_size > 1e-8 and not token_fills:
                # A freshly acknowledged fill may precede BOTH read indexes.
                # Keep its cost/risk tracked until positive contradictory
                # execution evidence arrives; zero/empty reads alone cannot
                # prove that this position disappeared.
                item = {'condition_id': current.condition_id, 'token_id': str(token),
                    'side': side, 'size': old.remaining_size, 'ledger_size': old.remaining_size,
                    'balance_size': balances[str(token)], 'available_size': 0.0,
                    'reserved_size': 0.0, 'balance_mismatch': True, 'local_pending': True,
                    'price': old.entry_price, 'entry_ts': old.entry_ts,
                    'entry_order_id': old.entry_order_id, 'unpriced': old.entry_price <= 0,
                    'entry_cost_remaining_usd':old.remaining_size*old.entry_price,
                    'entry_fees_remaining_usd':getattr(old,'entry_fees_remaining_usd',None),
                    'fee_source':getattr(old,'fee_source','pending_entry_fee_unavailable'),
                    'fee_estimated':True,
                    'settlement_pending': True}
                positions[str(token)] = item
            if item is None or item['size'] <= 1e-8:
                strategy_state.local_positions.pop(key, None)
                continue
            average = item['price']
            if average <= 0 and old is not None:
                average = old.entry_price
            # An unexpected live balance with no cost proof is treated as an
            # exposure needing exit review, never silently discarded as zero.
            unpriced = average <= 0
            strategy_state.local_positions[key] = TrackedPosition(
                market_slug=current.market_slug, condition_id=current.condition_id,
                token_id=str(token), side=side, entry_size=max(item['size'], old.entry_size if old else 0.0),
                remaining_size=item['size'], entry_price=average,
                entry_notional=item['size'] * average, entry_order_id=item['entry_order_id'],
                entry_ts=item['entry_ts'], stop_loss_pending=unpriced or bool(old and old.stop_loss_pending),
                last_exit_attempt_ts=old.last_exit_attempt_ts if old else 0.0,
                last_exit_order_id=old.last_exit_order_id if old else None)
            tracked=strategy_state.local_positions[key]
            tracked.entry_fees_remaining_usd=item.get('entry_fees_remaining_usd')
            tracked.entry_cost_remaining_usd=item.get('entry_cost_remaining_usd')
            tracked.fee_source=item.get('fee_source','entry_fee_unavailable')
            tracked.entry_fee_estimated=True
        strategy_state.live_authoritative = True
        self.snapshot = {'wallet': self.wallet, 'condition_id': current.condition_id,
            'as_of': fetched, 'complete': True, 'positions': positions,
            'buy_count': count, 'bought_cost_usd': cost,
            'has_resting_orders': bool(orders), 'ambiguous_entry': ambiguous,
            'open_order_ids': [str(order.get('id') or '') for order in orders]}
        self.last_error = None
        _atomic(self.directory / 'positions-current.json', self.snapshot)
        return self.snapshot

    def _resolve_intent(self, condition, fills, orders):
        path = self._path(condition)
        with _locked(path.with_suffix('.lock')):
            intent = self._read(condition)
            if not intent or intent.get('state') not in ('submitted', 'ambiguous'):
                return False
            ids = set(intent.get('order_ids') or [])
            seen = [fill for fill in fills if fill['side'] == 'BUY' and
                    (fill['order_id'] in ids if ids else fill['ts'] >= intent['submitted_at'] - 3)]
            if seen:
                intent.update(state='filled', confirmed_fill_size=sum(fill['size'] for fill in seen),
                              updated_at=time.time())
                _atomic(path, intent)
                return False
            # No order hash after a submit timeout cannot be proved absent by
            # a temporarily empty trade index. Retain the block across restart.
            if not ids:
                return True
            from bot.order_evidence import order_snapshot
            live_ids = {str(order.get('id') or '') for order in orders}
            proven_zero = True
            for order_id in ids:
                try:
                    if order_id in live_ids:
                        # The exact intent identifies our own stale request;
                        # cancel it, but require a subsequent terminal read.
                        self.client.cancel_orders([order_id])
                    raw_order = self.client.get_order(order_id)
                    original = _number(raw_order.get('original_size')) if isinstance(raw_order, dict) else None
                    evidence = order_snapshot(raw_order, order_id=order_id,
                        token_id=intent['token_id'], side='BUY',
                        requested_size=original if original is not None else intent['requested_size'])
                    if not evidence or not evidence.get('terminal') or evidence.get('filled_size', 0) > 0:
                        proven_zero = False
                except Exception:
                    proven_zero = False
            if proven_zero:
                intent.update(state='cancelled_zero', updated_at=time.time())
                _atomic(path, intent)
                return False
            return True

    def entry_reason(self, current):
        value = self.snapshot
        if value.get('condition_id') != current.condition_id or not value.get('complete'):
            return 'Live wallet reconciliation unavailable; entries blocked'
        if time.time() - value.get('as_of', 0) > 15:
            return 'Live wallet reconciliation stale; entries blocked'
        if value.get('ambiguous_entry') or value.get('has_resting_orders'):
            return 'Unresolved live order remains; reconcile before another entry'
        maximum = max(int(getattr(self.cfg, 'max_buys_per_market', 1)), 1)
        if value.get('buy_count', 0) >= maximum:
            return 'Live market buy budget already used; exits remain enabled'
        if any(item.get('unpriced') for item in value.get('positions', {}).values()):
            return 'Unpriced live holding requires reconciliation'
        if any(item.get('balance_mismatch') or item.get('settlement_pending')
               for item in value.get('positions', {}).values()):
            return 'Live fill and balance indexes have not converged; entries blocked'
        return None

    def claim_entry(self, current, token, side, size, price):
        reason = self.entry_reason(current)
        if reason:
            return False, reason
        path = self._path(current.condition_id)
        with _locked(path.with_suffix('.lock')):
            old = self._read(current.condition_id)
            if old.get('state') in ('submitted', 'ambiguous', 'filled'):
                return False, 'Persistent entry intent blocks duplicate submission'
            now = time.time()
            _atomic(path, {'wallet': self.wallet, 'condition_id': current.condition_id,
                'market_slug': current.market_slug, 'token_id': str(token), 'side': side,
                'state': 'submitted', 'submitted_at': now, 'updated_at': now,
                'requested_size': float(size), 'limit_price': float(price), 'order_ids': []})
        return True, None

    def record_result(self, current, result, *, order_ids=()):
        path = self._path(current.condition_id)
        with _locked(path.with_suffix('.lock')):
            value = self._read(current.condition_id)
            ids = sorted({str(item) for item in (*(value.get('order_ids') or []), *order_ids, result.order_id) if item})
            filled = float(result.filled_size or 0.0)
            confirmed = max(filled, float(value.get('confirmed_fill_size') or 0.0))
            state = ('ambiguous' if result.ambiguous else 'filled' if confirmed > 0 else
                     'cancelled_zero' if (getattr(result, 'fallback_safe', False) or
                                         not result.submitted or getattr(result, 'terminal', False)) else 'ambiguous')
            value.update(order_ids=ids, confirmed_fill_size=confirmed, state=state,
                         result_status=str(result.status), updated_at=time.time())
            _atomic(path, value)

    def available_to_sell(self, current, token):
        balance = self.conditional_balance(token)
        raw = self.client.get_trades(TradeParams(market=current.condition_id,
                        after=int(current.start_ts) - 10), only_first_page=False)
        if not isinstance(raw, list):
            raise ValueError('Execution evidence unavailable before sell')
        fills = iter_account_trade_fills(raw, owner_addresses=self.owners,
            api_owner=getattr(self.cfg, 'api_key', None), condition_id=current.condition_id,
            token_id=str(token))
        buys = sum(item['size'] for item in fills if item['side'] == 'BUY')
        sells = sum(item['size'] for item in fills if item['side'] == 'SELL')
        # MATCHED sells reserve exposure even before the balance index catches
        # up; all sells cannot be repeated just because that balance is stale.
        if buys > 0:
            balance = min(balance, max(buys - sells, 0.0))
        elif sells > 0:
            raise ValueError('Sell history has no complete buy inventory evidence')
        orders = self.client.get_open_orders(OpenOrderParams(market=current.condition_id,
                                           asset_id=str(token)), only_first_page=False)
        if not isinstance(orders, list):
            raise ValueError('Open-order reservations unavailable')
        reserved = 0.0
        for order in orders:
            if str(order.get('asset_id') or order.get('token_id') or '') != str(token):
                continue
            if str(order.get('side') or '').upper() != 'SELL':
                continue
            original, matched = _number(order.get('original_size')), _number(order.get('size_matched'))
            if original is None or matched is None:
                raise ValueError('Sell reservation quantity unavailable')
            if original < 0 or matched < 0 or matched > original + 1e-6:
                raise ValueError('Sell reservation quantity inconsistent')
            reserved += max(original - matched, 0.0)
        return max(balance - reserved, 0.0)
