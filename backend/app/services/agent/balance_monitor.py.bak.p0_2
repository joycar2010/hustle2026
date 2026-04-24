"""balance_monitor.py — P3: Direct chesspnt /api/user/self quota read.

Priority cascade (first successful wins):
  1. chesspnt /api/user/self  — real-time quota field, exact match with wallet page
  2. relay  /v1/dashboard/billing/usage — fallback raw usage estimate

The chesspnt session cookie expires periodically. If it returns 401/403 or
success=false, we fall back to relay usage automatically and log a warning so the
operator knows to refresh the cookie in Settings.

Quota unit calibration: 1 USD = 675410 quota units (derived from
quota=50648984 matching console balance $74.99 on 2026-04-19).
Operators can override via chesspnt_auth.units_per_usd in agent_active_config.
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

# ───── chesspnt API ─────

async def fetch_chesspnt_balance(auth: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call chesspnt /api/user/self and return normalized balance dict.

    Returns None on any error so caller can fall back to relay estimate.
    """
    base = auth.get('api_base', 'https://api.chesspnt.com').rstrip('/')
    cookie = auth.get('session_cookie', '')
    user_hdr = auth.get('new_api_user', '')
    units_per_usd = float(auth.get('units_per_usd', 675410))

    if not cookie:
        return None

    headers = {
        'accept': 'application/json, text/plain, */*',
        'cookie': f'session={cookie}',
    }
    if user_hdr:
        headers['new-api-user'] = str(user_hdr)

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(f'{base}/api/user/self', headers=headers) as resp:
                if resp.status not in (200, 201):
                    logger.warning(
                        f'[balance] chesspnt /api/user/self returned HTTP {resp.status}'
                    )
                    return None
                data = await resp.json()
                if not data.get('success'):
                    logger.warning(
                        f'[balance] chesspnt self returned success=false: {data.get("message")}'
                    )
                    return None
                user = data.get('data', {})
                quota = float(user.get('quota', 0))
                balance_usd = quota / units_per_usd
                return {
                    'source': 'chesspnt_self',
                    'quota_units': quota,
                    'balance_usd': balance_usd,
                    'units_per_usd': units_per_usd,
                    'username': user.get('username', ''),
                    'display_name': user.get('display_name', ''),
                }
    except Exception as e:
        logger.warning(f'[balance] chesspnt fetch failed: {e}')
        return None


# ───── relay usage fallback ─────

async def fetch_relay_usage() -> Optional[float]:
    """Return total_usage (USD) from relay billing endpoint. None if unavailable."""
    base = (os.getenv('OPENCLAW_LLM_BASE_URL') or '').rstrip('/')
    key = os.getenv('OPENCLAW_LLM_API_KEY', '')
    if not base or not key:
        return None
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as s:
            async with s.get(
                f'{base}/v1/dashboard/billing/usage',
                headers={'Authorization': f'Bearer {key}'}
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                return float(data.get('total_usage', 0))
    except Exception as e:
        logger.debug(f'[balance] relay usage fetch failed: {e}')
        return None


# ───── unified compute_balance ─────

async def compute_balance(db: AsyncSession) -> Dict[str, Any]:
    """Unified balance: chesspnt direct → relay fallback.

    Returns dict compatible with existing frontend fields:
      balance_cny, spent_cny, recharge_total_cny, balance_usd, relay_usage_raw,
      currency_symbol, low_balance, alert_threshold_cny, usage_multiplier,
      source ('chesspnt_self' | 'relay_estimate')
    """
    cfg = await config_loader.load_config(db)
    ls = cfg.get('llm_settings', {}) or {}
    auth = cfg.get('chesspnt_auth', {}) or {}

    threshold_cny = float(ls.get('balance_alert_threshold_cny', 20) or 20)
    usd_to_cny = float(ls.get('usd_to_cny_rate', 7.3) or 7.3)
    currency_symbol = ls.get('currency_symbol', '$')

    # ── Priority 1: chesspnt real-time quota ──
    cp = await fetch_chesspnt_balance(auth)
    if cp:
        balance_usd = cp['balance_usd']
        balance_cny = balance_usd * usd_to_cny
        low = balance_cny < threshold_cny
        return {
            'source': 'chesspnt_self',
            'quota_units': cp['quota_units'],
            'balance_usd': balance_usd,
            'balance_cny': balance_cny,
            'balance': balance_cny,
            # legacy fields (no spent/recharge concept in chesspnt quota)
            'spent_cny': None,
            'recharge_total_cny': None,
            'relay_usage_raw': None,
            'currency_symbol': '¥',
            'alert_threshold_cny': threshold_cny,
            'alert_threshold': threshold_cny,
            'usage_multiplier': None,
            'usd_to_cny_rate': usd_to_cny,
            'low_balance': low,
            'chesspnt_username': cp.get('username'),
        }

    # ── Priority 2: relay billing/usage estimate ──
    multiplier = float(ls.get('usage_multiplier', 1.0) or 1.0)
    recharge_cny = float(ls.get('recharge_total_cny', 0) or 0)
    raw = await fetch_relay_usage()
    spent_cny = (raw * multiplier) if raw is not None else None
    balance_cny = (recharge_cny - spent_cny) if spent_cny is not None else None
    low = balance_cny is not None and balance_cny < threshold_cny
    return {
        'source': 'relay_estimate',
        'relay_usage_raw': raw,
        'spent_cny': spent_cny,
        'spent': spent_cny,
        'recharge_total_cny': recharge_cny,
        'recharge_total': recharge_cny,
        'balance_cny': balance_cny,
        'balance_usd': (balance_cny / usd_to_cny) if balance_cny else None,
        'balance': balance_cny,
        'alert_threshold_cny': threshold_cny,
        'alert_threshold': threshold_cny,
        'usage_multiplier': multiplier,
        'currency_symbol': currency_symbol,
        'low_balance': low,
    }


# ───── background tick ─────

async def _tick():
    global _last_alert_ts
    async with AsyncSessionLocal() as db:
        info = await compute_balance(db)
        logger.debug(
            f'[balance] source={info["source"]} balance_cny={info.get("balance_cny")}'
        )
        if not info['low_balance']:
            return
        if time.time() - _last_alert_ts < ALERT_COOLDOWN_S:
            return
        _last_alert_ts = time.time()
        bal = info.get('balance_cny')
        src = info.get('source')
        await broadcast(
            db, level='danger', category='llm_balance_low',
            message=(
                f'Codex 中转站余额告警 [{src}] | '
                f'当前余额 ¥{bal:.2f} < ¥{info["alert_threshold_cny"]:.0f} 阈值 — 请及时充值'
            ),
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
