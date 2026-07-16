# -*- coding: utf-8 -*-
"""P0-0716 §3.2 FeeResolver 精简版 (2026-07-16)。

账户级真实费率: 后台每12h按活动 user_pair_accounts 的A腿(账户×symbol)调
Binance /fapi/v1/commissionRate, 落 account_symbol_fee_rates 表。

铁律:
- "0"是合法真实费率(maker促销), 与"查不到"是两个状态 — 绝不 value or default;
- first_observed_at=系统首次观察时间, 不伪称交易所生效时间;
- 静态 platform_symbols.maker_fee_rate 仅 legacy_fallback, 不参与本表;
- 查询失败保留上次值(status=STALE), 不写猜测值。
只读服务: 本模块不参与下单决策(准入门禁属后续批次), 先把事实积累起来。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_SYNC_TASK = [None]
_SYNC_INTERVAL_S = 12 * 3600


def ensure_started():
    t = _SYNC_TASK[0]
    if t is not None and not t.done():
        return
    try:
        _SYNC_TASK[0] = asyncio.create_task(_loop())
        logger.info("[FEE_RESOLVER] sync loop started")
    except RuntimeError:
        pass


async def _loop():
    await asyncio.sleep(120)  # 起服2分钟后首跑, 避开启动风暴
    while True:
        try:
            await sync_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[FEE_RESOLVER] sync error: {e!r}")
        await asyncio.sleep(_SYNC_INTERVAL_S)


async def sync_all():
    """同步全部活动绑定的A腿费率。逐个串行+抖动, 不打限频。"""
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT DISTINCT aa.account_id::text, aa.api_key, aa.api_secret, aa.proxy_config,"
            "       sa.id AS symbol_id, sa.symbol"
            " FROM user_pair_accounts upa"
            " JOIN accounts aa ON aa.account_id = upa.account_a_id AND aa.is_active"
            " JOIN hedging_pairs hp ON hp.pair_code = upa.pair_code AND hp.is_active"
            " JOIN platform_symbols sa ON sa.id = hp.symbol_a_id AND sa.platform_id = 1"
        ))).all()
    if not rows:
        return
    logger.info(f"[FEE_RESOLVER] syncing {len(rows)} account×symbol fee rates")
    ok = 0
    for acct_id, key, sec, proxy, sym_id, symbol in rows:
        try:
            await _sync_one(acct_id, key, sec, proxy, sym_id, symbol)
            ok += 1
        except Exception as e:
            logger.warning(f"[FEE_RESOLVER] {symbol}@{acct_id[:8]} failed: {e!r}")
            await _mark_stale(acct_id, sym_id)
        await asyncio.sleep(2.0)  # 限频友好
    logger.info(f"[FEE_RESOLVER] sync done: {ok}/{len(rows)} ok")


async def _sync_one(acct_id, key, sec, proxy, sym_id, symbol):
    import json as _j
    from app.services.continuous_executor import _RECON_BN_CLIENTS
    cli = _RECON_BN_CLIENTS.get(acct_id)
    if cli is None:
        from app.services.binance_client import BinanceFuturesClient
        from app.core.proxy_utils import build_proxy_url
        pc = proxy
        if isinstance(pc, str):
            try:
                pc = _j.loads(pc)
            except Exception:
                pc = None
        cli = BinanceFuturesClient(key, sec, proxy_url=build_proxy_url(pc))
        _RECON_BN_CLIENTS[acct_id] = cli
    data = await asyncio.wait_for(
        cli._request("GET", "/fapi/v1/commissionRate", signed=True, params={"symbol": symbol}),
        timeout=15.0)
    # 响应缺字段=同步失败(不能把缺字段当0); "0"字符串是合法真实费率
    if not isinstance(data, dict) or "makerCommissionRate" not in data or "takerCommissionRate" not in data:
        raise ValueError(f"commissionRate响应缺字段: {data}")
    maker = str(data["makerCommissionRate"])
    taker = str(data["takerCommissionRate"])
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO account_symbol_fee_rates"
            " (account_id, platform_symbol_id, maker_fee_rate, taker_fee_rate, source, raw, status)"
            " VALUES (:a, :s, CAST(:m AS numeric), CAST(:t AS numeric), 'commissionRate', CAST(:r AS jsonb), 'FRESH')"
            " ON CONFLICT (account_id, platform_symbol_id) DO UPDATE SET"
            " maker_fee_rate=EXCLUDED.maker_fee_rate, taker_fee_rate=EXCLUDED.taker_fee_rate,"
            " raw=EXCLUDED.raw, status='FRESH', last_verified_at=now()"),
            {"a": acct_id, "s": sym_id, "m": maker, "t": taker,
             "r": _j.dumps(data, default=str)})
        await db.commit()
    logger.info(f"[FEE_RESOLVER] {symbol}@{acct_id[:8]}: maker={maker} taker={taker}")


async def _mark_stale(acct_id, sym_id):
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(text(
                "UPDATE account_symbol_fee_rates SET status='STALE'"
                " WHERE account_id=:a AND platform_symbol_id=:s"),
                {"a": acct_id, "s": sym_id})
            await db.commit()
    except Exception:
        pass
