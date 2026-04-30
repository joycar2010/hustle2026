"""Build MarketState snapshot from live sources.

P1.5 implementation - all data sources wired:
  - Spread        : Go market /api/v1/market/spread?pair=XAU
  - 30m avg       : in-process deque (5s x 360 samples)
  - Funding rate  : Binance /fapi/v1/premiumIndex?symbol=XAUUSDT (60s cache)
  - Funding history: last 3 distinct funding rate values for trend analysis
  - MT5 swap fees : direct mt5.symbol_info('XAUUSD+') (5 min cache)
  - Positions     : account_data_service singleton (60s shared cache)
  - Equity        : same source as positions
  - Conversion    : hedging_pairs.conversion_factor where pair_code='XAU'
  - Daily volume  : SUM(qty) from agent_decisions where verdict='executed' today
"""
import time
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from app.services.agent.guard import MarketState

logger = logging.getLogger(__name__)

_spread_windows: Dict[int, deque] = {}
_spread_window: deque = deque(maxlen=360)

GO_SPREAD_URL_TMPL = 'http://127.0.0.1:8080/api/v1/market/spread?pair={pair}'
BINANCE_PREMIUM_URL_TMPL = 'https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}'
OKX_FUNDING_URL_TMPL = 'https://www.okx.com/api/v5/public/funding-rate?instId={inst_id}'

A_PLATFORM_ID = 1
A_SYMBOL_PREFIXES = ('XAUUSDT',)
B_PLATFORM_ID = 2
B_SYMBOL_PREFIXES = ('XAUUSD+', 'XAUUSD')

_PLATFORM_DISPLAY = {1: 'Binance', 2: 'Bybit', 3: 'IC Markets', 4: 'Gate.io', 5: 'OKX', 6: 'Bitget'}

_funding_cache: Tuple[float, float] = (0.0, 0.0)
_funding_cache_by_target: Dict[int, Tuple[float, float]] = {}
_funding_history: deque = deque(maxlen=3)
_funding_history_by_target: Dict[int, deque] = {}
_swap_cache: Tuple[float, float, float] = (0.0, 0.0, 0.0)
_conversion_cache: Tuple[float, float] = (100.0, 0.0)
FUNDING_TTL = 60
SWAP_TTL = 300
CONV_TTL = 600


async def fetch_spread(pair_code: str = 'XAU') -> Optional[Dict[str, Any]]:
    url = GO_SPREAD_URL_TMPL.format(pair=pair_code)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception as e:
        logger.warning(f'[snapshot] go spread fetch failed for {pair_code}: {e}')
        return None


def push_spread_sample(forward_entry_spread: float, target_id: Optional[int] = None):
    _spread_window.append(forward_entry_spread)
    if target_id is not None:
        if target_id not in _spread_windows:
            _spread_windows[target_id] = deque(maxlen=360)
        _spread_windows[target_id].append(forward_entry_spread)


def spread_30m_avg(target_id: Optional[int] = None) -> float:
    if target_id is not None and target_id in _spread_windows:
        w = _spread_windows[target_id]
        if w:
            return sum(w) / len(w)
    if not _spread_window:
        return 0.0
    return sum(_spread_window) / len(_spread_window)


async def fetch_funding_rate(ctx=None) -> float:
    global _funding_cache
    tid = ctx.target_id if ctx else 0
    if tid and tid in _funding_cache_by_target:
        val, ts = _funding_cache_by_target[tid]
        if time.time() - ts < FUNDING_TTL:
            return val
    elif not tid:
        val, ts = _funding_cache
        if time.time() - ts < FUNDING_TTL:
            return val

    prev_val = (_funding_cache_by_target.get(tid, (0.0, 0.0))[0] if tid
                else _funding_cache[0])
    hist = _funding_history_by_target.setdefault(tid, deque(maxlen=3)) if tid else _funding_history

    platform_id = ctx.a_platform_id if ctx else 1
    a_symbol = ctx.a_symbol if ctx else 'XAUUSDT'
    new_val = prev_val

    try:
        if platform_id == 6:
            from app.services.bitget_client import BitgetClient
            async with BitgetClient() as bg:
                r = await bg.get_funding_rate(a_symbol)
                if bg._ok(r) and r.get('data'):
                    new_val = float(r['data'][0].get('fundingRate', 0) or 0)
        elif platform_id == 5:
            inst_id = a_symbol.replace('USDT', '-USDT-SWAP')
            url = OKX_FUNDING_URL_TMPL.format(inst_id=inst_id)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data.get('data'):
                            new_val = float(data['data'][0].get('fundingRate', 0) or 0)
        else:
            url = BINANCE_PREMIUM_URL_TMPL.format(symbol=a_symbol)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.json()
                        new_val = float(data.get('lastFundingRate', 0) or 0)
    except Exception as e:
        logger.warning(f'[snapshot] funding fetch failed (platform={platform_id}): {e}')

    if not hist or abs(new_val - (hist[-1] if hist else 0)) > 1e-8:
        hist.append(new_val)

    if tid:
        _funding_cache_by_target[tid] = (new_val, time.time())
    else:
        _funding_cache = (new_val, time.time())
    return new_val


def funding_rate_trend(ctx=None) -> str:
    tid = ctx.target_id if ctx else 0
    hist = _funding_history_by_target.get(tid, _funding_history) if tid else _funding_history
    if len(hist) < 2:
        return 'insufficient_data'
    vals = list(hist)
    if all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
        return 'rising'
    if all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)):
        return 'falling'
    return 'stable'


MT5_BRIDGE_URL = 'http://172.31.14.113:8001'
import os as _os


async def fetch_mt5_swap() -> Tuple[float, float]:
    global _swap_cache
    long_v, short_v, ts = _swap_cache
    if time.time() - ts < SWAP_TTL:
        return long_v, short_v
    try:
        api_key = _os.getenv('MT5_API_KEY', '')
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(f'{MT5_BRIDGE_URL}/mt5/symbol_info/XAUUSD%2B',
                             headers={'x-api-key': api_key}) as r:
                if r.status == 200:
                    d = await r.json()
                    long_v = round(float(d.get('swap_long', 0)) / 100, 4)
                    short_v = round(float(d.get('swap_short', 0)) / 100, 4)
                    _swap_cache = (long_v, short_v, time.time())
                    return long_v, short_v
                else:
                    logger.warning(f'[snapshot] mt5 bridge swap status {r.status}')
    except Exception as e:
        logger.debug(f'[snapshot] mt5 swap fetch failed (non-fatal): {e}')
    return long_v, short_v


async def fetch_conversion_factor(db: AsyncSession, ctx=None) -> float:
    if ctx is not None:
        return ctx.conversion_factor
    from app.services.agent.scope import list_active_contexts
    active = await list_active_contexts(db)
    return active[0].conversion_factor if active else 100.0


async def collect_xau_positions_and_equity(db: AsyncSession, ctx=None) -> Dict[str, float]:
    try:
        from app.services.account_service import account_data_service
        from app.models.account import Account
        if ctx is None:
            from app.services.agent.scope import list_active_contexts
            active = await list_active_contexts(db)
            if not active:
                return {'a_size': 0.0, 'b_size': 0.0, 'total_equity': 0.0, 'a_equity': 0.0, 'b_equity': 0.0}
            agg = {'a_size': 0.0, 'b_size': 0.0, 'total_equity': 0.0, 'a_equity': 0.0, 'b_equity': 0.0}
            for c in active:
                one = await collect_xau_positions_and_equity(db, c)
                for k in agg:
                    agg[k] += one[k]
            return agg

        all_accs = (await db.execute(select(Account).where(Account.is_active == True))).scalars().all()
        in_scope = [a for a in all_accs if ctx.is_scope_match_account(a)]
        if not in_scope:
            return {'a_size': 0.0, 'b_size': 0.0, 'total_equity': 0.0, 'a_equity': 0.0, 'b_equity': 0.0}

        agg = await account_data_service.get_aggregated_account_data(list(in_scope))
        a_long = a_short = 0.0
        b_long = b_short = 0.0
        a_equity = b_equity = 0.0
        a_sym_upper = ctx.a_symbol.upper()
        b_sym_upper = ctx.b_symbol.upper()

        for acc in agg.get('accounts', []):
            pid = acc.get('platform_id')
            bal = acc.get('balance', {}) or {}
            net = float(bal.get('net_assets', 0) or bal.get('total_assets', 0) or 0)
            if pid == ctx.a_platform_id:
                a_equity += net
            elif pid == ctx.b_platform_id:
                b_equity += net
            for pos in acc.get('positions', []):
                sym = (pos.get('symbol') or '').upper()
                side = (pos.get('side') or '').upper()
                size = float(pos.get('size', 0) or 0)
                if pid == ctx.a_platform_id and sym == a_sym_upper:
                    if side in ('LONG', 'BUY'):
                        a_long += size
                    elif side in ('SHORT', 'SELL'):
                        a_short += size
                elif pid == ctx.b_platform_id and (sym == b_sym_upper or sym.rstrip('+') == b_sym_upper.rstrip('+')):
                    if side in ('LONG', 'BUY'):
                        b_long += size
                    elif side in ('SHORT', 'SELL'):
                        b_short += size

        return {
            'a_size': a_long - a_short, 'b_size': b_long - b_short,
            'total_equity': a_equity + b_equity,
            'a_equity': a_equity, 'b_equity': b_equity,
        }
    except Exception as e:
        logger.warning(f'[snapshot] positions fetch failed: {e}')
        return {'a_size': 0.0, 'b_size': 0.0, 'total_equity': 0.0, 'a_equity': 0.0, 'b_equity': 0.0}


async def daily_traded_volume(db: AsyncSession, ctx=None) -> float:
    today_utc = datetime.now(timezone.utc).date()
    if ctx is not None:
        row = (await db.execute(text(
            "SELECT COALESCE(SUM(CAST(proposal->>'qty' AS NUMERIC)), 0) "
            "FROM agent_decisions "
            "WHERE verdict = 'executed' AND created_at >= :d AND scope_target_id = :t"
        ), {'d': today_utc, 't': ctx.target_id})).first()
    else:
        row = (await db.execute(text(
            "SELECT COALESCE(SUM(CAST(proposal->>'qty' AS NUMERIC)), 0) "
            "FROM agent_decisions "
            "WHERE verdict = 'executed' AND created_at >= :d"
        ), {'d': today_utc})).first()
    return float(row[0]) if row else 0.0


def _compute_position_direction(a_size: float, b_size: float, conv: float) -> str:
    a_net = a_size
    b_net_oz = b_size * conv
    if abs(a_net) < 0.01 and abs(b_net_oz) < 0.01:
        return 'flat'
    if a_net > 0.01 and b_net_oz < -0.01:
        return 'forward'
    if a_net < -0.01 and b_net_oz > 0.01:
        return 'reverse'
    return 'mixed'


async def build_snapshot(db: AsyncSession, ctx=None) -> Optional[MarketState]:
    pair_code = ctx.pair_code if ctx else 'XAU'
    tid = ctx.target_id if ctx else None
    spread = await fetch_spread(pair_code)
    if not spread:
        return None
    push_spread_sample(spread.get('forward_entry_spread', 0.0), target_id=tid)

    funding = await fetch_funding_rate(ctx)
    swap_long, swap_short = await fetch_mt5_swap()
    conv = await fetch_conversion_factor(db, ctx)
    pos_eq = await collect_xau_positions_and_equity(db, ctx)
    vol = await daily_traded_volume(db, ctx)

    direction = _compute_position_direction(pos_eq['a_size'], pos_eq['b_size'], conv)

    return MarketState(
        spread_now=spread.get('forward_entry_spread', 0.0),
        spread_30m_avg=spread_30m_avg(target_id=tid),
        funding_rate=funding,
        swap_fee_long=swap_long,
        swap_fee_short=swap_short,
        a_size=pos_eq['a_size'],
        b_size=pos_eq['b_size'],
        conversion_factor=conv,
        total_equity=pos_eq['total_equity'],
        a_equity=pos_eq['a_equity'],
        b_equity=pos_eq['b_equity'],
        daily_traded_volume=vol,
        now_utc_ms=int(time.time() * 1000),
        funding_rate_history=list(_funding_history),
        position_direction=direction,
        funding_rate_trend=funding_rate_trend(ctx),
    )


def snapshot_to_user_prompt(s: MarketState, ctx=None) -> str:
    a_name = _PLATFORM_DISPLAY.get(ctx.a_platform_id, 'A腿') if ctx else 'Binance'
    b_name = _PLATFORM_DISPLAY.get(ctx.b_platform_id, 'B腿') if ctx else 'MT5'
    a_sym = ctx.a_symbol if ctx else 'XAUUSDT'
    b_sym = ctx.b_symbol if ctx else 'XAUUSD+'

    from datetime import timedelta, timezone as tz
    bjt = tz(timedelta(hours=8))
    bjt_str = datetime.fromtimestamp(s.now_utc_ms / 1000, tz=tz.utc).astimezone(bjt).strftime('%Y-%m-%d %H:%M:%S BJT')
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    bjt_dt = datetime.fromtimestamp(s.now_utc_ms / 1000, tz=tz.utc).astimezone(bjt)
    weekday_str = weekday_names[bjt_dt.weekday()]

    direction_label = {
        'forward': '正向套利(A多B空)',
        'reverse': '反向套利(A空B多)',
        'flat': '无持仓',
        'mixed': '混合/异常',
    }.get(s.position_direction, '未知')

    fr_trend = funding_rate_trend(ctx)
    fr_trend_label = {'rising': '上升', 'falling': '下降', 'stable': '稳定',
                      'insufficient_data': '数据不足'}.get(fr_trend, fr_trend)
    fr_history_str = ', '.join(f'{v * 100:.4f}%' for v in s.funding_rate_history) if s.funding_rate_history else '无'

    is_wed = bjt_dt.weekday() == 2
    triple_swap_note = ''
    if is_wed and bjt_dt.hour >= 20:
        triple_cost_short = abs(s.swap_fee_short) * 3
        triple_cost_long = abs(s.swap_fee_long) * 3
        triple_swap_note = (
            f'\n- [周三三倍过夜费提醒] 正向持仓隔夜掉期成本: {triple_cost_short:.4f} USD/lot '
            f'| 反向持仓隔夜掉期成本: {triple_cost_long:.4f} USD/lot'
        )

    return (
        f'当前市场快照({bjt_str} {weekday_str}):\n'
        f'- 实时点差(forward_entry): {s.spread_now:.3f}\n'
        f'- 半小时均值点差: {s.spread_30m_avg:.3f}\n'
        f'- {a_name} {a_sym} 资金费率(本期): {s.funding_rate * 100:.4f}%\n'
        f'- 资金费率趋势: {fr_trend_label} (近3期: {fr_history_str})\n'
        f'- {b_name} {b_sym} 多头掉期: {s.swap_fee_long} USD/lot/day  空头掉期: {s.swap_fee_short} USD/lot/day'
        f'{triple_swap_note}\n'
        f'- 当前持仓方向: {direction_label}\n'
        f'- A 腿 {a_name} 净仓位: {s.a_size} 张(per oz)\n'
        f'- B 腿 {b_name} 净仓位: {s.b_size} 手(每手 {s.conversion_factor} oz)\n'
        f'- 双腿偏差(oz 折算): {abs(s.a_size - s.b_size * s.conversion_factor):.2f}\n'
        f'- 总权益: {s.total_equity:.2f} USDT  A 腿: {s.a_equity:.2f}  B 腿: {s.b_equity:.2f}\n'
        f'- 今日累计交易量(agent 已执行): {s.daily_traded_volume:.2f}\n\n'
        f'请按规范输出 JSON 决策。'
    )
