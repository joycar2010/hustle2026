"""PnL 取数持久化层(纯 DB 操作: upsert / read / watermark / 开关)。

背景: 币安 income / MT5 deals 原为实时拉取+内存缓存, 重启即丢、长周期累计(cq002 4个月×5账户)
打爆币安 REST 限频致封 IP, 且失败静默当0→对冲单边假巨亏。持久化后历史只拉一次, 只增量重拉近端。

设计: 本模块只做纯 DB(无业务编排、不 import pnl.py 防循环依赖)。read-through 编排在 pnl.py 的
_fetch_* 内。开关 PNL_PERSIST_ENABLED 默认 OFF(关时 pnl.py 走原实时逻辑, 行为零变化)。
唯一键: binance=ON CONFLICT(account_id,dedup_key) DO NOTHING; mt5=(account_id,ticket) DO UPDATE。
金额全 NUMERIC; 时间 binance 存 ms-UTC 原值 / MT5 存 deal_time_utc(由调用方注入转换)+raw 原值。
"""
import os
import json
import logging
from datetime import datetime as _dt
from sqlalchemy import text

logger = logging.getLogger(__name__)

TAIL_REFETCH_MS = 7 * 24 * 60 * 60 * 1000   # 近端重拉的重叠窗口(7天, 捕获延迟结算)
TAIL_COOLDOWN_SEC = float(__import__('os').getenv('PNL_TAIL_COOLDOWN_SEC', '600'))  # 近端重拉冷却(默认10min): 冷却期内已覆盖到查询终点则跳过实时拉取、直接读DB。把"重拉频率"与"请求量/range数"解耦, 跨worker共享(强于进程内去重)

def is_enabled() -> bool:
    return os.getenv("PNL_PERSIST_ENABLED", "0").lower() in ("1", "true", "on", "yes")

# ---------- watermark ----------
async def get_watermark(db, account_id, source):
    r = (await db.execute(text(
        "SELECT covered_from_ms, covered_to_ms, last_error, "
        "EXTRACT(EPOCH FROM (now() - last_sync_at)) AS age_sec FROM pnl_sync_watermark "
        "WHERE account_id=CAST(:a AS UUID) AND source=:s"
    ), {"a": str(account_id), "s": source})).first()
    if not r:
        return None
    return {"covered_from_ms": r[0], "covered_to_ms": r[1], "last_error": r[2],
            "age_sec": float(r[3]) if r[3] is not None else None}

async def advance_watermark(db, account_id, source, cov_from=None, cov_to=None, error=None):
    """GREATEST/LEAST 单调推进, 防并发回退覆盖。error 非空=该源上次失败(不推进区间)。"""
    await db.execute(text(
        """
        INSERT INTO pnl_sync_watermark(account_id, source, covered_from_ms, covered_to_ms, last_sync_at, last_error, updated_at)
        VALUES (CAST(:a AS UUID), :s, :cf, :ct, now(), :err, now())
        ON CONFLICT (account_id, source) DO UPDATE SET
            covered_from_ms = LEAST(COALESCE(pnl_sync_watermark.covered_from_ms, EXCLUDED.covered_from_ms), COALESCE(EXCLUDED.covered_from_ms, pnl_sync_watermark.covered_from_ms)),
            covered_to_ms   = GREATEST(COALESCE(pnl_sync_watermark.covered_to_ms, EXCLUDED.covered_to_ms), COALESCE(EXCLUDED.covered_to_ms, pnl_sync_watermark.covered_to_ms)),
            last_sync_at    = now(),
            last_error      = EXCLUDED.last_error,
            updated_at      = now()
        """
    ), {"a": str(account_id), "s": source, "cf": cov_from, "ct": cov_to, "err": error})

# ---------- binance_income ----------
async def upsert_binance_income(db, account_id, raw_rows) -> int:
    """raw_rows = 币安原始 income dict 列表。ON CONFLICT DO NOTHING(币安不可变)。"""
    n = 0
    for r in raw_rows:
        try:
            tran_id = r.get("tranId")
            tran_id = int(tran_id) if tran_id not in (None, "") else None
            trade_id = r.get("tradeId")
            trade_id = int(trade_id) if trade_id not in (None, "") else None
            await db.execute(text(
                """
                INSERT INTO binance_income(account_id, tran_id, trade_id, income_type, income, asset, symbol, income_time_ms, info, raw)
                VALUES (CAST(:a AS UUID), :tran, :trade, :itype, :inc, :asset, :sym, :t, :info, CAST(:raw AS JSONB))
                ON CONFLICT (account_id, dedup_key) DO NOTHING
                """
            ), {
                "a": str(account_id), "tran": tran_id, "trade": trade_id,
                "itype": r.get("incomeType", ""), "inc": str(r.get("income", "0")),
                "asset": r.get("asset"), "sym": r.get("symbol") or None,
                "t": int(r.get("time", 0)), "info": (r.get("info") or None),
                "raw": json.dumps(r, ensure_ascii=False),
            })
            n += 1
        except Exception as e:
            logger.warning(f"upsert_binance_income skip 1 row: {e}")
    return n

async def read_binance_income(db, account_id, start_ms, end_ms) -> list:
    """返回与币安原结构一致的 dict 列表(直接吐 raw 列, 字段100%一致, 调用方无感)。"""
    rows = (await db.execute(text(
        "SELECT raw FROM binance_income WHERE account_id=CAST(:a AS UUID) "
        "AND income_time_ms BETWEEN :s AND :e ORDER BY income_time_ms"
    ), {"a": str(account_id), "s": int(start_ms), "e": int(end_ms)})).fetchall()
    return [row[0] for row in rows]

# ---------- mt5_deals ----------
async def upsert_mt5_deals(db, account_id, std_rows) -> int:
    """std_rows = [{raw, ticket, order_id, symbol, deal_type, entry, volume, price, profit,
    swap, commission, comment, deal_time_raw, deal_time_utc(ISO str), bridge_port}].
    deal_time_utc 由调用方用 mt5_server_ts_to_utc 算好注入(本模块不依赖 pnl.py)。
    ON CONFLICT DO UPDATE 金额项(跨桥/迟到修正兜底)。"""
    n = 0
    for d in std_rows:
        try:
            await db.execute(text(
                """
                INSERT INTO mt5_deals(account_id, ticket, order_id, symbol, deal_type, entry,
                    volume, price, profit, swap, commission, comment, deal_time_raw, deal_time_utc, bridge_port, raw)
                VALUES (CAST(:a AS UUID), :tk, :oid, :sym, :dtype, :entry,
                    :vol, :price, :profit, :swap, :comm, :cmt, :traw, :tutc, :bport, CAST(:raw AS JSONB))
                ON CONFLICT (account_id, ticket) DO UPDATE SET
                    profit=EXCLUDED.profit, swap=EXCLUDED.swap, commission=EXCLUDED.commission,
                    comment=EXCLUDED.comment, deal_time_utc=EXCLUDED.deal_time_utc
                """
            ), {
                "a": str(account_id), "tk": int(d["ticket"]), "oid": d.get("order_id"),
                "sym": d.get("symbol"), "dtype": d.get("deal_type"), "entry": d.get("entry"),
                "vol": str(d.get("volume", "0")), "price": str(d.get("price", "0")),
                "profit": str(d.get("profit", "0")), "swap": str(d.get("swap", "0")),
                "comm": str(d.get("commission", "0")), "cmt": (d.get("comment") or None),
                "traw": int(d.get("deal_time_raw", 0)), "tutc": _dt.fromisoformat(d["deal_time_utc"]),
                "bport": d.get("bridge_port"), "raw": json.dumps(d.get("raw", {}), ensure_ascii=False),
            })
            n += 1
        except Exception as e:
            logger.warning(f"upsert_mt5_deals skip ticket={d.get('ticket')}: {e}")
    return n

async def read_mt5_deals(db, account_id, start_ms, end_ms) -> list:
    """按 deal_time_utc 区间返回 raw(全量 deal, 不过滤 entry; 消费侧各自分流平仓/现金流)。"""
    rows = (await db.execute(text(
        "SELECT raw FROM mt5_deals WHERE account_id=CAST(:a AS UUID) "
        "AND deal_time_utc BETWEEN to_timestamp(:s/1000.0) AND to_timestamp(:e/1000.0) "
        "ORDER BY deal_time_utc"
    ), {"a": str(account_id), "s": int(start_ms), "e": int(end_ms)})).fetchall()
    return [row[0] for row in rows]
