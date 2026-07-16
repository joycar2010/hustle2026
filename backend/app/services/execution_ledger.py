# -*- coding: utf-8 -*-
"""M1 执行事实层双写(V1.1 §8.2 首版, 2026-07-16)。

Shadow 模式铁律:
- 只写不读: V3 之前本层不是任何决策的权威, 权威仍是交易所/桥 + 现有账本;
- fire-and-forget: 所有写入是独立task+3s超时+吞错, 绝不阻塞/破坏交易热路径;
- 开关: config/ledger_v2.json {"dual_write": true}, 30s热读, 关=零开销直接返回。

价值: 执行链重建(execution_id 从 ladder 贯穿下单/成交/对冲/崩溃补腿)、
事故取证(告别 journalctl 考古)、cycle PnL 的数据地基。
"""
import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_CFG = {"ts": 0.0, "cfg": {}}
_TASKS = set()          # 强引用防task被GC
_SHA_CACHE = [None]


def _enabled() -> bool:
    now = time.time()
    if now - _CFG["ts"] > 30.0:
        _CFG["ts"] = now
        try:
            _p = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'ledger_v2.json')
            with open(_p) as f:
                _CFG["cfg"] = json.load(f) or {}
        except Exception:
            pass  # 保留上次缓存
    return bool(_CFG["cfg"].get("dual_write"))


def _release_sha() -> str:
    if _SHA_CACHE[0] is None:
        try:
            import subprocess
            _SHA_CACHE[0] = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=os.path.dirname(os.path.abspath(__file__)), timeout=3,
                stderr=subprocess.DEVNULL).decode().strip()[:40]
        except Exception:
            _SHA_CACHE[0] = 'unknown'
    return _SHA_CACHE[0]


def _fire(coro):
    try:
        t = asyncio.create_task(coro)
        _TASKS.add(t)
        t.add_done_callback(_TASKS.discard)
    except Exception:
        pass  # 无运行中事件循环等 — shadow层绝不上抛


async def _exec_sql(sql: str, params: dict):
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await asyncio.wait_for(db.execute(text(sql), params), timeout=3.0)
            await db.commit()
    except Exception as e:
        logger.debug(f"[LEDGER_V2] shadow write failed (不影响交易): {e!r}")


def log_execution_start(execution_id, strategy_id, user_id, pair_code,
                        strategy_type, ladder_idx, planned_qty):
    if not _enabled() or not execution_id:
        return
    _fire(_exec_sql(
        "INSERT INTO executions (execution_id, strategy_id, user_id, pair_code, strategy_type,"
        " ladder_idx, planned_qty, status, release_sha)"
        " VALUES (:e, :s, :u, :p, :t, :l, :q, 'RUNNING', :sha)"
        " ON CONFLICT (execution_id) DO NOTHING",
        {"e": execution_id, "s": str(strategy_id)[:120] if strategy_id else None,
         "u": str(user_id) if user_id else None, "p": pair_code, "t": strategy_type,
         "l": ladder_idx, "q": planned_qty, "sha": _release_sha()}))


def log_execution_end(execution_id, status, binance_filled=None,
                      hedge_filled_lot=None, error=None):
    if not _enabled() or not execution_id:
        return
    _fire(_exec_sql(
        "UPDATE executions SET status=:st,"
        " binance_filled=COALESCE(:bf, binance_filled),"
        " hedge_filled_lot=COALESCE(:hf, hedge_filled_lot),"
        " error=COALESCE(:er, error), finished_at=now()"
        " WHERE execution_id=:e",
        {"e": execution_id, "st": str(status)[:30],
         "bf": binance_filled, "hf": hedge_filled_lot,
         "er": (str(error)[:2000] if error else None)}))


def log_order(execution_id, venue, account_id, symbol, side, requested_qty,
              venue_order_id, client_order_id, status='NEW'):
    if not _enabled():
        return
    _fire(_exec_sql(
        "INSERT INTO execution_orders (execution_id, venue, account_id, symbol, side,"
        " requested_qty, venue_order_id, client_order_id, status)"
        " VALUES (:e, :v, :a, :sym, :sd, :q, :oid, :cid, :st)",
        {"e": execution_id, "v": venue, "a": str(account_id) if account_id else None,
         "sym": symbol, "sd": side, "q": requested_qty,
         "oid": str(venue_order_id)[:64] if venue_order_id else None,
         "cid": str(client_order_id)[:64] if client_order_id else None, "st": status}))


def log_fill(execution_id, venue, venue_order_id, fill_qty, avg_price,
             qty_unit, source):
    if not _enabled():
        return
    _fire(_exec_sql(
        "INSERT INTO execution_fills (execution_id, venue, venue_order_id, fill_qty,"
        " avg_price, qty_unit, source)"
        " VALUES (:e, :v, :oid, :q, :p, :u, :src)",
        {"e": execution_id, "v": venue,
         "oid": str(venue_order_id)[:64] if venue_order_id else None,
         "q": fill_qty, "p": avg_price, "u": qty_unit, "src": source}))


_MARKOUT_HORIZONS_MS = (250, 1000, 5000, 30000)


def sample_markout(execution_id, venue_order_id, symbol, side, fill_price, fill_qty):
    """M1c(V1.1 §11.2): A腿成交后按4个时间窗采样mid漂移, 度量maker逆向选择成本。
    fire-and-forget独立task, 读WS内存价(零REST成本); markout_bps符号约定:
    正=价格向持仓不利方向移动(SELL后跌/BUY后涨为负收益方向的镜像) — 统一"正=成本"。"""
    if not _enabled() or not fill_price or fill_price <= 0:
        return

    async def _sampler():
        try:
            from app.services.market_service import market_data_service as _mds
            t0 = asyncio.get_event_loop().time()
            for h_ms in _MARKOUT_HORIZONS_MS:
                delay = h_ms / 1000.0 - (asyncio.get_event_loop().time() - t0)
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    q = await _mds.get_binance_quote(symbol)
                    mid = (q.bid_price + q.ask_price) / 2.0
                    spread = q.ask_price - q.bid_price
                except Exception:
                    continue  # 行情不可得跳过该窗(不写假值)
                # SELL: 成交后mid上涨=卖便宜了=成本为正; BUY: mid下跌=买贵了=成本为正
                drift = (mid - float(fill_price)) / float(fill_price) * 10000.0
                markout_bps = drift if str(side).upper() == "SELL" else -drift
                await _exec_sql(
                    "INSERT INTO fill_markouts (execution_id, venue_order_id, symbol, side,"
                    " fill_price, fill_qty, horizon_ms, mid_at_horizon, markout_bps, spread_at_horizon)"
                    " VALUES (:e, :oid, :sym, :sd, :fp, :fq, :h, :mid, :mo, :sp)",
                    {"e": execution_id, "oid": str(venue_order_id)[:64] if venue_order_id else None,
                     "sym": symbol, "sd": str(side).upper()[:8], "fp": fill_price, "fq": fill_qty,
                     "h": h_ms, "mid": mid, "mo": round(markout_bps, 6), "sp": round(spread, 6)})
        except Exception as e:
            logger.debug(f"[LEDGER_V2] markout sampler failed: {e!r}")

    _fire(_sampler())


def log_event(execution_id, event, detail=None):
    if not _enabled():
        return
    try:
        _dj = json.dumps(detail, ensure_ascii=False, default=str)[:4000] if detail is not None else None
    except Exception:
        _dj = None
    _fire(_exec_sql(
        "INSERT INTO execution_events (execution_id, event, detail)"
        " VALUES (:e, :ev, CAST(:d AS jsonb))",
        {"e": execution_id, "ev": str(event)[:40], "d": _dj}))
