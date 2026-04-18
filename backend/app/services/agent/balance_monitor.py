"""Relay quota/usage pull + RMB balance estimator.

Relay endpoint `/v1/dashboard/billing/usage` returns `total_usage` which on our
new-api deployment is CNY cents (¥ × 100). Convert to CNY = total_usage / 100.

Balance = recharge_total_cny - spent_cny.
When balance < balance_alert_threshold_cny (default ¥20), fire Feishu (once/24h).
"""
import asyncio
import logging
import os
import time
from typing import Dict, Any, Optional
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.agent import config_loader
from app.services.agent.feishu_broadcast import broadcast

logger = logging.getLogger(__name__)

_last_alert_ts = 0.0
TICK_S = 60
ALERT_COOLDOWN_S = 24 * 3600


async def fetch_relay_usage() -> Optional[float]:
    """Return total_usage_raw (relay scale). None if unavailable."""
    base = (os.getenv('OPENCLAW_LLM_BASE_URL') or '').rstrip('/')
    key = os.getenv('OPENCLAW_LLM_API_KEY', '')
    if not base or not key:
        return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.get(f'{base}/v1/dashboard/billing/usage',
                             headers={'Authorization': f'Bearer {key}'}) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                return float(data.get('total_usage', 0))
    except Exception as e:
        logger.debug(f'[balance] relay usage fetch failed: {e}')
        return None


async def compute_balance(db: AsyncSession) -> Dict[str, Any]:
    cfg = await config_loader.load_config(db)
    ls = cfg.get('llm_settings', {}) or {}
    recharge_cny = float(ls.get('recharge_total_cny', 0) or 0)
    threshold = float(ls.get('balance_alert_threshold_cny', 20) or 20)
    # usage_multiplier: raw usage (reported by /v1/dashboard/billing/usage) × multiplier = CNY spent.
    # For this new-api relay the value is ~10.82 (group rate). Operator calibrates in Settings.
    multiplier = float(ls.get('usage_multiplier', 10.82) or 10.82)
    raw = await fetch_relay_usage()
    spent_cny = (raw * multiplier) if raw is not None else None
    balance_cny = (recharge_cny - spent_cny) if spent_cny is not None else None
    currency = ls.get('currency_symbol', '$')
    return {
        'relay_usage_raw': raw,
        'spent_cny': spent_cny,
        'spent': spent_cny,
        'recharge_total_cny': recharge_cny,
        'recharge_total': recharge_cny,
        'balance_cny': balance_cny,
        'balance': balance_cny,
        'alert_threshold_cny': threshold,
        'alert_threshold': threshold,
        'usage_multiplier': multiplier,
        'currency_symbol': currency,
        'low_balance': balance_cny is not None and balance_cny < threshold,
    }


async def _tick():
    global _last_alert_ts
    async with AsyncSessionLocal() as db:
        info = await compute_balance(db)
        if not info['low_balance']:
            return
        if time.time() - _last_alert_ts < ALERT_COOLDOWN_S:
            return
        _last_alert_ts = time.time()
        await broadcast(
            db, level='danger', category='llm_balance_low',
            message=(f'Codex 中转站余额低于阈值 | 已充值 ¥{info["recharge_total_cny"]:.2f} | '
                     f'已消耗 ¥{info["spent_cny"]:.2f} | 剩余 ¥{info["balance_cny"]:.2f} '
                     f'< ¥{info["alert_threshold_cny"]:.0f} 阈值 — 请及时充值'),
            payload=info,
        )


_stop = None
_task = None


async def _loop_main(stop_event: asyncio.Event):
    logger.info('[balance_monitor] loop started')
    while not stop_event.is_set():
        try:
            await _tick()
        except Exception as e:
            logger.error(f'[balance_monitor] tick error: {e}')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_S)
        except asyncio.TimeoutError:
            pass
    logger.info('[balance_monitor] stopped')


def start():
    global _stop, _task
    if _task and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_loop_main(_stop))


async def stop():
    global _stop, _task
    if _stop:
        _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except asyncio.TimeoutError:
            _task.cancel()
