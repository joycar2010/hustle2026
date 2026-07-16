# -*- coding: utf-8 -*-
"""M2 RecoveryWorker(V1.1 §8.4 首版, 2026-07-16)。

扫描事实层中的非终态 execution(RUNNING 超龄 = 进程重启/协程被杀且终态没落库),
对每条做三件事:
  1. 若 execution_orders 记录了币安单 → REST 查真实终态:
     仍 open → 撤单(挂单孤儿, 25s强杀/重启的直接残留);
     已成交 → 补记 execution_fills(source=recovery) — 敞口处置交给
     GOLD_RECON/崩溃补腿/人工(本worker只回收订单+补全事实, 不自动开新仓)。
  2. executions.status → RECOVERED_* 终态, 事件链记 RECOVERY 事件。
  3. 结果告警到日志(ERROR级, 现有日志监控可见)。

设计边界(V1.1 §8.4):
- 只处理 s- 前缀策略单; m- 手动单绝不碰;
- 单飞: Redis SETNX 锁(TTL 120s), 双机/多进程不重复处置;
- 每轮最多处理 20 条, 15s 一轮; 依赖失败静默下轮再试;
- config/ledger_v2.json {"recovery_worker": true} 开关, 默认关。
"""
import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

_WORKER_TASK = [None]
_STALE_RUNNING_S = 120.0     # RUNNING 超过此秒数 = 泄漏(正常执行25s封顶)
_SCAN_INTERVAL_S = 15.0


def _enabled() -> bool:
    try:
        _p = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'ledger_v2.json')
        with open(_p) as f:
            return bool((json.load(f) or {}).get("recovery_worker"))
    except Exception:
        return False


def ensure_started():
    """幂等拉起后台worker(main.py startup 调用)。"""
    t = _WORKER_TASK[0]
    if t is not None and not t.done():
        return
    try:
        _WORKER_TASK[0] = asyncio.create_task(_loop())
        logger.info("[RECOVERY] worker started")
    except RuntimeError:
        pass  # 无运行中事件循环, 下次调用再试


async def _loop():
    while True:
        try:
            await asyncio.sleep(_SCAN_INTERVAL_S)
            if not _enabled():
                continue
            await _scan_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[RECOVERY] loop error: {e!r}")


async def _try_lock() -> bool:
    """互斥锁TTL=10s(<扫描间隔15s): 每轮自然过期, 正常时各进程轮流拿到;
    持锁进程崩溃最多闷10s。⚠不能设长TTL — 首版120s把自己的后续轮次全锁死。"""
    try:
        import redis.asyncio as _redis
        from app.core.config import settings
        r = _redis.from_url(settings.REDIS_URL)
        try:
            return bool(await r.set("recovery_worker:lock", str(os.getpid()), nx=True, ex=10))
        finally:
            await r.aclose()
    except Exception:
        return True  # Redis不可用时按单机模式继续(该场景本就无双活)


async def _scan_once():
    if not await _try_lock():
        return
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT e.execution_id, e.strategy_type, e.pair_code,"
            "       o.account_id, o.symbol, o.venue_order_id, o.client_order_id"
            " FROM executions e"
            " LEFT JOIN execution_orders o ON o.execution_id = e.execution_id AND o.venue = 'binance'"
            " WHERE e.status = 'RUNNING'"
            "   AND e.created_at < now() - make_interval(secs => :stale)"
            " ORDER BY e.created_at LIMIT 20"),
            {"stale": _STALE_RUNNING_S})).all()
    if not rows:
        return
    logger.warning(f"[RECOVERY] 发现 {len(rows)} 条超龄RUNNING execution")
    for eid, stype, pair, acct_id, symbol, oid, coid in rows:
        try:
            await _recover_one(str(eid), stype, pair, acct_id, symbol, oid, coid)
        except Exception as e:
            logger.error(f"[RECOVERY] recover {eid} failed: {e!r}")


async def _get_binance_client(account_id):
    """复用 GOLD_RECON 的模块级客户端缓存(防SSL反复重建)。"""
    from app.services.continuous_executor import _RECON_BN_CLIENTS
    cli = _RECON_BN_CLIENTS.get(str(account_id)) or _RECON_BN_CLIENTS.get(account_id)
    if cli is not None:
        return cli
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT api_key, api_secret, proxy_config FROM accounts WHERE account_id = :a"),
            {"a": str(account_id)})).first()
    if not row:
        return None
    from app.services.binance_client import BinanceFuturesClient
    from app.core.proxy_utils import build_proxy_url
    pc = row[2]
    if isinstance(pc, str):
        try:
            pc = json.loads(pc)
        except Exception:
            pc = None
    cli = BinanceFuturesClient(row[0], row[1], proxy_url=build_proxy_url(pc))
    _RECON_BN_CLIENTS[str(account_id)] = cli
    return cli


async def _query_order_status(cli, symbol, order_id):
    """兼容不同客户端方法名, 返回原始订单dict或None。"""
    for meth in ('get_order', 'query_order', 'get_order_status'):
        fn = getattr(cli, meth, None)
        if fn is None:
            continue
        try:
            st = await asyncio.wait_for(fn(symbol=symbol, order_id=int(order_id)), timeout=8.0)
        except TypeError:
            st = await asyncio.wait_for(fn(symbol, int(order_id)), timeout=8.0)
        if st:
            return st
    return None


async def _recover_one(eid, stype, pair, acct_id, symbol, oid, coid):
    from app.services import execution_ledger as ledger
    # 无币安单记录 → 挂单前就死了, 无交易所侧残留
    if not oid or not acct_id:
        ledger.log_execution_end(eid, 'RECOVERED_NO_ORDER', error='stale RUNNING, no venue order recorded')
        ledger.log_event(eid, 'RECOVERY', {"action": "mark_only", "reason": "no venue order"})
        return
    if coid and not str(coid).startswith('s-'):
        ledger.log_execution_end(eid, 'RECOVERED_SKIPPED', error=f'non-strategy clientOrderId {coid!r}')
        logger.error(f"[RECOVERY] {eid} 订单 {oid} clientOrderId={coid!r} 非s-, 只标记不处置")
        return
    cli = await _get_binance_client(acct_id)
    if cli is None:
        logger.warning(f"[RECOVERY] {eid} 账户 {acct_id} 凭证不可得, 下轮再试")
        return
    st = await _query_order_status(cli, symbol, oid)
    if st is None:
        logger.warning(f"[RECOVERY] {eid} 订单状态查询不可用, 下轮再试")
        return
    status = str(st.get('status', ''))
    filled = float(st.get('executedQty', 0) or 0)
    avg = float(st.get('avgPrice', 0) or 0)
    if status in ('NEW', 'PARTIALLY_FILLED'):
        # 交易所侧仍挂着 → 孤儿, 撤掉
        try:
            await asyncio.wait_for(cli.cancel_order(symbol, int(oid)), timeout=8.0)
            logger.error(f"[RECOVERY] {eid} 撤掉孤儿挂单 order={oid} (status={status}, filled={filled})")
        except Exception as ce:
            logger.error(f"[RECOVERY] {eid} 撤孤儿单失败 order={oid}: {ce!r}")
            return  # 下轮重试
    if filled > 0:
        ledger.log_fill(eid, 'binance', oid, filled, avg, 'A', 'recovery')
    ledger.log_execution_end(eid, 'RECOVERED_CANCELLED' if status in ('NEW', 'PARTIALLY_FILLED')
                             else ('RECOVERED_' + status[:20] if status else 'RECOVERED_UNKNOWN'),
                             binance_filled=filled if filled > 0 else None)
    ledger.log_event(eid, 'RECOVERY', {
        "order_id": oid, "venue_status": status, "filled": filled,
        "note": "敞口处置交由GOLD_RECON/补腿/人工, 本worker只回收订单+补全事实"})
    logger.error(f"[RECOVERY] {eid} 收敛完成: venue_status={status} filled={filled}")
