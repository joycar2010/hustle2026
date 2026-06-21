"""PnL 收益分析 API — 为 www 用户平台提供日/周/月收益图表数据"""
import os
import logging
import math
import time as _time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List

import httpx
from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.database import get_db, AsyncSessionLocal
from app.core.proxy_utils import build_proxy_url
from app.models.user import User
from app.models.account import Account
from app.api.v1.subaccount import get_view_context, ViewContext
from app.services.subaccount_projector import project_response
from app.models.mt5_client import MT5Client
from app.services.binance_client import BinanceFuturesClient
from app.utils.time_utils import mt5_server_ts_to_utc

logger = logging.getLogger(__name__)
router = APIRouter()

# ── 简易内存缓存（60 秒 TTL）──────────────────────────
_cache: Dict[str, Any] = {}
_cache_ts: Dict[str, float] = {}
CACHE_TTL = 300

# SWR(stale-while-revalidate, 20260620 优化项4): 合并视图 daily 取数慢(实测cq002+cq001
# merged 30天=33s, 打5-6桥+币安income分段)。SWR 让缓存过期后【先返回旧值秒回 + 后台异步刷新】,
# 用户永不等33s(除真正冷启动首次)。SOFT 内=新鲜直接返回; SOFT~HARD 之间=返回旧值并触发后台刷新;
# 超 HARD 或无缓存=冷启动需同步算(仅首访)。_inflight 防并发重复算(同 key 只跑一个后台任务)。
_SWR_SOFT_TTL = 300.0     # 5min 内视为新鲜
_SWR_HARD_TTL = 1800.0    # 30min 内可返回旧值(后台刷新), 超过则视为太旧需同步重算
_inflight: set = set()    # 正在后台刷新的 cache_key
# cold-miss 去重(20260621): 同一 cache_key 的并发冷启动(含预热 vs 用户)只算一次, 其余在
# per-key 锁上等待→拿到锁后复检命中已填缓存, 避免重复算+争抢桥 I/O(此前并发冷各算→实测76s)。
_compute_locks: Dict[str, Any] = {}

# 累计真实起算日缓存(20260621): inception 改为【动态查账号集最早成交记录】(币安income最早
# + MT5 deals最早 取较早者), 而非 account_snapshots 快照日(测试库快照4/16晚于真实成交3月,
# 用快照会截断早期对冲腿盈利→累计失真: cq002 从4/16算=-9527, 从真实最早算≈+3283)。
# 查最早成交需打交易所/桥(慢), 故按账号集缓存24h(账号最早成交日是不变量)。
_inception_cache: Dict[str, Any] = {}
_INCEPTION_TTL = 86400.0  # 24h


def _cache_get(key: str):
    if key in _cache and _time.time() - _cache_ts.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None


def _cache_set(key: str, val):
    _cache[key] = val
    _cache_ts[key] = _time.time()


def _swr_get(key: str):
    """返回 (value, freshness): freshness ∈ {'fresh','stale','miss'}。"""
    if key not in _cache:
        return None, 'miss'
    age = _time.time() - _cache_ts.get(key, 0)
    if age < _SWR_SOFT_TTL:
        return _cache[key], 'fresh'
    if age < _SWR_HARD_TTL:
        return _cache[key], 'stale'
    return None, 'miss'


async def _earliest_binance_ms(account, scan_from_ms: int, now_ms: int):
    """币安账户最早成交(非TRANSFER)的 ms 时间戳。从 scan_from_ms 按7天段向前扫, 命中第一个
    有成交的段即返回该段最小时间(币安 income 按时间正序)。无成交返回 None。"""
    client = BinanceFuturesClient(
        account.api_key, account.api_secret, proxy_url=build_proxy_url(account.proxy_config)
    )
    _SEG = 7 * 24 * 60 * 60 * 1000
    try:
        seg = scan_from_ms
        while seg <= now_ms:
            seg_end = min(seg + _SEG - 1, now_ms)
            recs = await client.get_income(start_time=seg, end_time=seg_end, limit=1000)
            times = [int(r.get("time", 0)) for r in recs
                     if r.get("incomeType") != "TRANSFER" and r.get("time")]
            if times:
                return min(times)
            seg = seg_end + 1
        return None
    except Exception as e:
        logger.warning(f"[inception] binance probe failed [{account.account_name}]: {e}")
        return None
    finally:
        await client.close()


async def _find_inception(accounts, scan_from_str: str = "2026-01-01"):
    """动态查账号集最早成交日(北京日期): 币安取 income 最早、MT5 取 deals 最早, 取较早者。
    替代 account_snapshots 快照日(测试库快照晚于真实成交→截断早期对冲腿盈亏致累计失真)。"""
    import datetime as _dtm
    scan_from_ms = int(_dtm.datetime.strptime(scan_from_str, "%Y-%m-%d")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000)
    now_ms = int(_time.time() * 1000)
    earliest_ms = None
    for a in accounts:
        try:
            if a.platform_id == 1:  # 币安
                m = await _earliest_binance_ms(a, scan_from_ms, now_ms)
            elif getattr(a, "is_mt5_account", False):  # MT5(Bybit/IC)
                deals = await _fetch_mt5_deals(a, scan_from_ms, now_ms)
                ts = [mt5_server_ts_to_utc(int(d.get("time", 0))) * 1000 for d in deals if d.get("time")]
                m = min(ts) if ts else None
            else:
                m = None
            if m is not None:
                earliest_ms = m if earliest_ms is None else min(earliest_ms, m)
        except Exception as e:
            logger.warning(f"[inception] probe failed [{getattr(a,'account_name','?')}]: {e}")
    return _utc_ms_to_beijing_date(earliest_ms) if earliest_ms is not None else None


# ── 时间工具 ──────────────────────────────────────────
def _beijing_date_to_utc_ms(date_str: str, end_of_day=False) -> int:
    """北京时间日期 → UTC 毫秒时间戳"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    utc_dt = dt - timedelta(hours=8)
    return int(utc_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _utc_ms_to_beijing_date(ts_ms: int) -> str:
    """UTC 毫秒 → 北京时间日期字符串 YYYY-MM-DD"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    beijing = dt + timedelta(hours=8)
    return beijing.strftime("%Y-%m-%d")


def _mt5_ts_to_beijing_date(ts_sec: int) -> str:
    """MT5 服务器时间（EET/EEST）→ 北京时间日期（DST-aware）"""
    utc_ts = mt5_server_ts_to_utc(ts_sec)
    dt = datetime.fromtimestamp(utc_ts, tz=timezone.utc)
    beijing = dt + timedelta(hours=8)
    return beijing.strftime("%Y-%m-%d")


# ── 数据获取 ─────────────────────────────────────────

async def _fetch_binance_income(account, start_ms: int, end_ms: int, income_type: str = None) -> list:
    """获取 Binance income 记录。

    20260620 修(收益随查询范围漂移的根因): 原实现单次大跨度 + limit=1000 游标分页,
    当某热点日(如对冲密集日)单日 income 笔数多、且分页边界恰好切在该日时, 会漏取该日
    后续记录(实测 hcz987 6/9: 30天范围只取63笔/581.03, 90天/单日均66笔/913.40)。
    根因: 币安 /fapi/v1/income 大跨度+1000上限分页, 游标 records[-1].time+1 在同毫秒多笔
    或跨度过大时丢数。改为【按7天分段】拉取, 每段内再分页(段内跨度小, 分页边界不会切在
    热点日中间), 跨段用 ticket/tranId 去重。同一区间无论从30/90/全部范围进入, 结果一致。
    """
    client = BinanceFuturesClient(
        account.api_key, account.api_secret,
        proxy_url=build_proxy_url(account.proxy_config)
    )
    _SEG_MS = 7 * 24 * 60 * 60 * 1000  # 7天分段
    all_records = []
    seen = set()
    try:
        seg_start = start_ms
        while seg_start <= end_ms:
            seg_end = min(seg_start + _SEG_MS - 1, end_ms)
            cursor = seg_start
            for _ in range(50):  # 段内分页(7天单段一般远不到, 50页=50000条上限兜底)
                records = await client.get_income(
                    income_type=income_type,
                    start_time=cursor,
                    end_time=seg_end,
                    limit=1000,
                )
                if not records:
                    break
                for r in records:
                    # 去重键: tranId 优先(币安唯一), 退化用 (time,type,income,symbol)
                    k = r.get("tranId") or (r.get("time"), r.get("incomeType"), r.get("income"), r.get("symbol"), r.get("tradeId"))
                    if k not in seen:
                        seen.add(k)
                        all_records.append(r)
                if len(records) < 1000:
                    break
                cursor = int(records[-1].get("time", 0)) + 1
            seg_start = seg_end + 1
    except Exception as e:
        logger.error(f"Binance income ({income_type}) fetch failed [{account.account_name}]: {e}")
    finally:
        await client.close()
    return all_records


async def _get_active_mt5_symbols(db: AsyncSession) -> set:
    """从 hedging_pairs 动态加载所有活跃产品对的 MT5 B 侧符号集合。"""
    _FALLBACK_MT5_SYMBOLS = {"XAUUSD+", "XAUUSD.s", "XAUUSD", "XAGUSD", "UKOUSD", "USOUSD", "NG-C"}
    try:
        result = await db.execute(text("""
            SELECT DISTINCT sb.symbol
            FROM hedging_pairs hp
            JOIN platform_symbols sb ON hp.symbol_b_id = sb.id
            WHERE hp.is_active = true
        """))
        rows = result.fetchall()
        symbols = {row[0] for row in rows if row[0]}
        return symbols if symbols else _FALLBACK_MT5_SYMBOLS
    except Exception as e:
        logger.warning(f"Failed to load MT5 symbols from DB, using fallback: {e}")
        return _FALLBACK_MT5_SYMBOLS


async def _fetch_mt5_deals(account, start_ms: int, end_ms: int) -> list:
    """获取 MT5 平仓 deal（entry==1），从该 account 下所有活跃 bridge 聚合并按 ticket 去重"""
    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
    api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", "OQ6bUimHZDmXEZzJKE"))
    headers = {"X-Api-Key": api_key} if api_key else {}

    # 短会话仅做 bridge 端口快查，随即归还连接；下面的 httpx 打桥(可达15s超时)不再占 DB 连接。
    try:
        async with AsyncSessionLocal() as _db:
            result = await _db.execute(
                select(MT5Client.bridge_service_port).where(
                    MT5Client.account_id == account.account_id,
                    MT5Client.is_active == True,
                    MT5Client.is_system_service == False,
                    MT5Client.bridge_service_port.isnot(None),
                ).order_by(MT5Client.priority)
            )
            bridge_ports = [row[0] for row in result.fetchall()]
    except Exception:
        bridge_ports = []

    if not bridge_ports:
        return []

    start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    now_utc = datetime.now(tz=timezone.utc)
    # MT5桥 days 参数实测按"最近N条/交易日"截断而非N个日历日(8002 days=32 实际只回~12天),
    # 直接用(now-start)天数会漏掉早段平仓→收益虚高(单腿假象)。故 ×3+7 大幅冗余覆盖;
    # 下方已用真实时间戳 start_ts<=ts<=end_ts 二次精确过滤, 多取无害(只是多拉后丢弃)。
    _span_days = int((now_utc - start_dt).total_seconds() / 86400)
    days = max(1, _span_days * 3 + 7)
    days = min(days, 365)

    seen_tickets = set()
    all_deals = []
    for port in bridge_ports:
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.get(
                    f"{bridge_host}:{port}/mt5/history/deals",
                    headers=headers, params={"days": days},
                )
                resp.raise_for_status()
                for d in resp.json().get("deals", []):
                    ticket = d.get("ticket")
                    if ticket and ticket not in seen_tickets:
                        seen_tickets.add(ticket)
                        all_deals.append(d)
        except Exception as e:
            logger.warning(f"MT5 deals fetch from port {port} failed [{account.account_name}]: {e}")

    start_ts = start_ms / 1000
    end_ts = end_ms / 1000
    return [
        d for d in all_deals
        if d.get("symbol")
        and start_ts <= mt5_server_ts_to_utc(int(d.get("time", 0))) <= end_ts
        and d.get("entry", 0) == 1
    ]


async def _fetch_mt5_cashflows(account, start_ms: int, end_ms: int) -> list:
    """获取 MT5 入出金记录，从该 account 下所有活跃 bridge 聚合并按 ticket 去重"""
    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
    api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", "OQ6bUimHZDmXEZzJKE"))
    headers = {"X-Api-Key": api_key} if api_key else {}

    # 短会话仅做 bridge 端口快查，随即归还连接；下面的 httpx 打桥(可达15s超时)不再占 DB 连接。
    try:
        async with AsyncSessionLocal() as _db:
            result = await _db.execute(
                select(MT5Client.bridge_service_port).where(
                    MT5Client.account_id == account.account_id,
                    MT5Client.is_active == True,
                    MT5Client.is_system_service == False,
                    MT5Client.bridge_service_port.isnot(None),
                ).order_by(MT5Client.priority)
            )
            bridge_ports = [row[0] for row in result.fetchall()]
    except Exception:
        bridge_ports = []

    if not bridge_ports:
        return []

    start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    now_utc = datetime.now(tz=timezone.utc)
    # MT5桥 days 参数实测按"最近N条/交易日"截断而非N个日历日(8002 days=32 实际只回~12天),
    # 直接用(now-start)天数会漏掉早段平仓→收益虚高(单腿假象)。故 ×3+7 大幅冗余覆盖;
    # 下方已用真实时间戳 start_ts<=ts<=end_ts 二次精确过滤, 多取无害(只是多拉后丢弃)。
    _span_days = int((now_utc - start_dt).total_seconds() / 86400)
    days = max(1, _span_days * 3 + 7)
    days = min(days, 365)

    seen_tickets = set()
    all_deals = []
    for port in bridge_ports:
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.get(
                    f"{bridge_host}:{port}/mt5/history/deals",
                    headers=headers, params={"days": days},
                )
                resp.raise_for_status()
                for d in resp.json().get("deals", []):
                    ticket = d.get("ticket")
                    if ticket and ticket not in seen_tickets:
                        seen_tickets.add(ticket)
                        all_deals.append(d)
        except Exception as e:
            logger.warning(f"MT5 cashflow fetch from port {port} failed [{account.account_name}]: {e}")

    start_ts = start_ms / 1000
    end_ts = end_ms / 1000
    return [
        d for d in all_deals
        if d.get("entry") == 0
        and (d.get("symbol") or "") == ""
        and float(d.get("profit", 0)) != 0
        and start_ts <= mt5_server_ts_to_utc(int(d.get("time", 0))) <= end_ts
    ]


async def _fetch_gateio_income(account, start_ms: int, end_ms: int) -> list:
    """Fetch Gate.io realized PnL records from position close history."""
    from app.services.gateio_client import GateioFuturesClient
    from app.core.proxy_utils import build_proxy_url

    client = GateioFuturesClient(
        api_key=account.api_key,
        api_secret=account.api_secret,
        proxy_url=build_proxy_url(account.proxy_config),
    )
    records = []
    try:
        closes = await client.get_position_close(limit=200)
        start_sec = start_ms / 1000
        end_sec = end_ms / 1000
        for c in closes:
            ts = float(c.get("time", 0))
            if start_sec <= ts <= end_sec:
                records.append({
                    "time": int(ts * 1000),
                    "pnl": float(c.get("pnl", 0)),
                    "pnl_fund": float(c.get("pnl_fund", 0)),
                    "contract": c.get("contract", ""),
                })
    except Exception as e:
        logger.error(f"Gate.io income fetch failed [{account.account_name}]: {e}")
    finally:
        await client.close()
    return records


async def _fetch_daily_closing_nav(account_ids: list, start_date: str, end_date: str) -> dict:
    """从 account_snapshots 查询每天收盘净值（北京时间最后一条快照）
    Returns: {date_str: total_nav_float}
    """
    if not account_ids:
        return {}
    from datetime import date as _d
    sd = _d.fromisoformat(start_date)
    ed = _d.fromisoformat(end_date)
    async with AsyncSessionLocal() as _db:
        result = await _db.execute(text("""
            WITH ranked AS (
                SELECT
                    CAST(timestamp + interval '8 hours' AS date) as bj_date,
                    account_id,
                    net_assets,
                    ROW_NUMBER() OVER (
                        PARTITION BY account_id, CAST(timestamp + interval '8 hours' AS date)
                        ORDER BY timestamp DESC
                    ) as rn
                FROM account_snapshots
                WHERE account_id = ANY(CAST(:aids AS uuid[]))
                AND CAST(timestamp + interval '8 hours' AS date) BETWEEN :sd AND :ed
            )
            SELECT bj_date, SUM(net_assets) as total_nav
            FROM ranked WHERE rn = 1
            GROUP BY bj_date ORDER BY bj_date
        """), {"aids": account_ids, "sd": sd, "ed": ed})
        return {row[0].isoformat(): float(row[1]) for row in result.fetchall()}


async def _fetch_daily_closing_upnl(account_ids: list, start_date: str, end_date: str, db) -> dict:
    """从 account_snapshots 查询 Binance 账户每天收盘 unrealized_pnl"""
    if not account_ids:
        return {}
    from datetime import date as _d
    sd = _d.fromisoformat(start_date)
    ed = _d.fromisoformat(end_date)
    result = await db.execute(text("""
        WITH ranked AS (
            SELECT
                CAST(timestamp + interval '8 hours' AS date) as bj_date,
                account_id,
                unrealized_pnl,
                ROW_NUMBER() OVER (
                    PARTITION BY account_id, CAST(timestamp + interval '8 hours' AS date)
                    ORDER BY timestamp DESC
                ) as rn
            FROM account_snapshots
            WHERE account_id = ANY(CAST(:aids AS uuid[]))
            AND CAST(timestamp + interval '8 hours' AS date) BETWEEN :sd AND :ed
        )
        SELECT bj_date, SUM(unrealized_pnl) as total_upnl
        FROM ranked WHERE rn = 1
        GROUP BY bj_date ORDER BY bj_date
    """), {"aids": account_ids, "sd": sd, "ed": ed})
    return {row[0].isoformat(): float(row[1]) for row in result.fetchall()}


# ── 统计计算 ─────────────────────────────────────────

def _compute_summary(daily_list: list) -> dict:
    """根据每日 PnL 数组计算汇总统计"""
    if not daily_list:
        return {
            "cumulative_pnl": 0, "max_drawdown": 0, "max_drawdown_pct": 0,
            "win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0,
            "best_day": None, "worst_day": None, "avg_daily_pnl": 0,
            "total_trade_count": 0, "profitable_days": 0, "losing_days": 0,
        }

    pnls = [d["net_pnl"] for d in daily_list]
    cumulative = []
    s = 0
    for p in pnls:
        s += p
        cumulative.append(s)

    peak = 0
    max_dd = 0
    for c in cumulative:
        peak = max(peak, c)
        dd = c - peak
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0

    profit_days = [p for p in pnls if p > 0]
    loss_days = [p for p in pnls if p < 0]
    total_days = len([p for p in pnls if p != 0])
    win_rate = len(profit_days) / total_days if total_days > 0 else 0

    sum_profit = sum(profit_days) if profit_days else 0
    sum_loss = abs(sum(loss_days)) if loss_days else 0
    profit_factor = round(sum_profit / sum_loss, 2) if sum_loss > 0 else (99.9 if sum_profit > 0 else 0)

    if len(pnls) >= 2:
        mean_pnl = sum(pnls) / len(pnls)
        std_pnl = (sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5
        sharpe = (mean_pnl / std_pnl * math.sqrt(365)) if std_pnl > 0 else 0
    else:
        sharpe = 0

    best_idx = pnls.index(max(pnls))
    worst_idx = pnls.index(min(pnls))

    return {
        "cumulative_pnl": round(cumulative[-1], 2) if cumulative else 0,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "win_rate": round(win_rate, 4),
        "profit_factor": profit_factor,
        "sharpe_ratio": round(sharpe, 2),
        "best_day": {"date": daily_list[best_idx]["date"], "pnl": round(pnls[best_idx], 2)},
        "worst_day": {"date": daily_list[worst_idx]["date"], "pnl": round(pnls[worst_idx], 2)},
        "avg_daily_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
        "total_trade_count": sum(d.get("trade_count", 0) for d in daily_list),
        "profitable_days": len(profit_days),
        "losing_days": len(loss_days),
    }


# ── API 端点 ─────────────────────────────────────────

@router.get("/daily")
async def get_daily_pnl(
    start_date: str = Query(..., description="开始日期（北京时间 YYYY-MM-DD）"),
    end_date: str = Query(..., description="结束日期（北京时间 YYYY-MM-DD）"),
    platform: str = Query("all", description="平台过滤: all/binance/mt5"),
    view: str = Query("merged", description="收益视图: merged(合并全部关联)/<user_id>(单用户)"),
    ctx: ViewContext = Depends(get_view_context),
    _bg: bool = False,   # 内部: 后台刷新调用时 True, 跳过 SWR 短路直接全量计算
):
    # 不再用 Depends(get_db) 全程持连接：所有 DB 读放进短会话块，慢的交易所/MT5 桥拉取在会话外执行。
    from app.models.user import User as _U
    async with AsyncSessionLocal() as db:
        _row = (await db.execute(select(_U).where(_U.user_id == ctx.data_user_id))).scalar_one_or_none()
        current_user = _row

        if ctx.is_sub:
            # 子账户收益起点(20260620): 优先用投入时间 invested_at, 回退订阅 created_at。
            _row_sub = (await db.execute(text(
                "SELECT MIN(COALESCE(invested_at, created_at)) FROM sub_account_subscriptions WHERE sub_user_id = CAST(:u AS UUID) AND status='active'"
            ), {"u": ctx.auth_user_id})).first()
            if _row_sub and _row_sub[0]:
                _join_date_str = _row_sub[0].astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
                if _join_date_str > start_date:
                    start_date = _join_date_str

    cache_key = f"pnl:{ctx.auth_user_id}:{current_user.user_id}:{start_date}:{end_date}:{platform}:sub={ctx.is_sub}:view={view}:v5"
    # SWR(优化项4): 后台刷新调用(_bg)跳过短路, 直接全量算并写缓存。
    if not _bg:
        _val, _fresh = _swr_get(cache_key)
        if _fresh == 'fresh':
            return _val
        if _fresh == 'stale':
            # 返回旧值秒回, 同时后台异步刷新(同 key 只跑一个)。
            if cache_key not in _inflight:
                _inflight.add(cache_key)
                async def _refresh(_ck=cache_key):
                    try:
                        await get_daily_pnl(start_date=start_date, end_date=end_date,
                                            platform=platform, view=view, ctx=ctx, _bg=True)
                    except Exception as _e:
                        logger.warning(f"[PnL-SWR] bg refresh failed {_ck}: {_e}")
                    finally:
                        _inflight.discard(_ck)
                try:
                    import asyncio as _aio
                    _aio.create_task(_refresh())
                except RuntimeError:
                    _inflight.discard(cache_key)
            return _val
        # miss: 冷启动。单飞锁去重(20260621): 同 cache_key 的并发冷启动(含预热 vs 用户)
        # 只算一次, 其余在锁上等待→拿到锁后复检命中已填的缓存, 不重复算+不争抢桥 I/O。
        import asyncio as _aio
        _lock = _compute_locks.get(cache_key)
        if _lock is None:
            _lock = _aio.Lock()
            _compute_locks[cache_key] = _lock
        async with _lock:
            _val2, _fresh2 = _swr_get(cache_key)
            if _val2 is not None and _fresh2 in ('fresh', 'stale'):
                return _val2  # 别的请求已算完, 直接复用
            # 仍冷 → 本请求触发一次 _bg 全量计算(写缓存), 其余同 key 请求在锁上等待复用
            return await get_daily_pnl(start_date=start_date, end_date=end_date,
                                       platform=platform, view=view, ctx=ctx, _bg=True)

    # ── Sub path: per-share NAV replay ──
    if ctx.is_sub:
        from app.services.subaccount_nav import (
            list_parent_daily_navs, list_active_subscriptions_by_sub,
        )
        async with AsyncSessionLocal() as db:
            subs = await list_active_subscriptions_by_sub(db, ctx.auth_user_id)
            if not subs:
                return {"daily_pnl": [], "summary": _compute_summary([])}

            date_pnl: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
            total_snapshots = 0
            for _sid, parent_uid, shares, _inv_u, _inv_c, nav_at_join, _created in subs:
                navs = await list_parent_daily_navs(db, parent_uid, start_date, end_date)
                total_snapshots += len(navs)
                prev_nav = nav_at_join
                for snap_date, nav, _ta, _ass in navs:
                    pnl = shares * (nav - prev_nav)
                    date_pnl[snap_date.isoformat()] += pnl
                    prev_nav = nav

        if total_snapshots >= 3:
            daily_list = [
                {
                    "date": dk,
                    "realized_pnl": round(float(v), 2),
                    "funding_fee": 0,
                    "net_pnl": round(float(v), 2),
                    "mt5_pnl": 0,
                    "binance_pnl": 0,
                    "trade_count": 0,
                    "win_count": 0,
                    "platform_breakdown": {
                        "binance": {"realized_pnl": 0, "funding_fee": 0},
                        "mt5": {"realized_pnl": 0, "swap": 0, "commission": 0},
                    },
                }
                for dk, v in sorted(date_pnl.items())
            ]
            resp = {
                "daily_pnl": daily_list,
                "summary": _compute_summary(daily_list),
                "data_source": "per_share_replay",
                "note": None,
            }
            _cache_set(cache_key, resp)
            logger.info(
                f"[PnL-sub] sub={ctx.auth_user_id} range={start_date}~{end_date} "
                f"parents={len(subs)} days={len(daily_list)} source=per_share"
            )
            return resp

        logger.info(
            f"[PnL-sub] sub={ctx.auth_user_id} sparse snapshots "
            f"(n={total_snapshots}); falling back to parent raw PnL x multiplier"
        )

    # ── Parent path: NAV-based PnL from account_snapshots ──

    try:
        start_ms = _beijing_date_to_utc_ms(start_date)
        end_ms = _beijing_date_to_utc_ms(end_date, end_of_day=True)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，需 YYYY-MM-DD")

    async with AsyncSessionLocal() as db:
        # 收益关联(20260620): 账号集 = data_user_id 自己 ∪ 关联用户(view=merged) 或单用户(view=<uid>)。
        from app.api.v1.subaccount import resolve_pnl_account_ids as _resolve_aids
        _aids = await _resolve_aids(db, str(current_user.user_id), view=view, is_sub=ctx.is_sub)
        if not _aids:
            return {"daily_pnl": [], "summary": _compute_summary([])}
        result = await db.execute(select(Account).filter(Account.account_id.in_(_aids)))
        accounts = result.scalars().all()
    if not accounts:
        return {"daily_pnl": [], "summary": _compute_summary([])}

    # 口径(20260620修): 收益不按 account.is_active 过滤(account.is_active 仅控 testgo 左侧列表
    # 显隐, 收益是历史交易事实应全计入)。accounts 已是 resolve_pnl_account_ids 解析的目标集。
    # 对冲腿计入与否由 MT5客户端(MT5Client.is_active)独立开关决定(_fetch_mt5_deals 选桥处)。
    active_account_ids = [str(a.account_id) for a in accounts]

    # 1) 日期范围 + 分平台 NAV / UPL
    from datetime import date as _date
    d_start = _date.fromisoformat(start_date)
    d_end = _date.fromisoformat(end_date)
    prev_date = (d_start - timedelta(days=1)).isoformat()

    # NAV 计算包含所有 MT5 账户（SUM 天然处理多账户迁移场景）
    mt5_account_ids = [str(a.account_id) for a in accounts if a.is_mt5_account]
    binance_account_ids = [str(a.account_id) for a in accounts if a.platform_id == 1]

    mt5_nav_by_date = await _fetch_daily_closing_nav(
        mt5_account_ids, prev_date, end_date
    ) if mt5_account_ids else {}



    # 2) Binance 全量 income（PnL = 所有已结算收入（不含 TRANSFER）+ UPL 变动）
    binance_income_pnl = defaultdict(float)

    # 3) MT5 入出金（entry=0, symbol 为空的 deals）
    mt5_cashflows = defaultdict(float)

    if platform in ("all", "mt5"):
        for account in accounts:
            if not account.is_mt5_account:
                continue
            cf_deals = await _fetch_mt5_cashflows(account, start_ms, end_ms)
            for d in cf_deals:
                dk = _mt5_ts_to_beijing_date(int(d.get("time", 0)))
                mt5_cashflows[dk] += float(d.get("profit", 0))

    # 4) Binance 全量 income 拆分（PnL + breakdown）
    binance_rpnl = defaultdict(float)
    binance_ff = defaultdict(float)
    binance_trades = defaultdict(int)
    binance_wins = defaultdict(int)
    if platform in ("all", "binance"):
        for account in accounts:
            if account.platform_id != 1:
                continue
            all_income = await _fetch_binance_income(account, start_ms, end_ms)
            for r in all_income:
                dk = _utc_ms_to_beijing_date(int(r.get("time", 0)))
                income = float(r.get("income", 0))
                itype = r.get("incomeType", "")
                if itype != "TRANSFER":
                    binance_income_pnl[dk] += income
                if itype == "REALIZED_PNL":
                    binance_rpnl[dk] += income
                    binance_trades[dk] += 1
                    if income > 0:
                        binance_wins[dk] += 1
                elif itype == "FUNDING_FEE":
                    binance_ff[dk] += income

    # 5) MT5 deals（仅用于 platform_breakdown 展示和 trade_count）
    mt5_rpnl = defaultdict(float)
    mt5_swap = defaultdict(float)
    mt5_comm = defaultdict(float)
    mt5_trades = defaultdict(int)
    mt5_wins = defaultdict(int)
    if platform in ("all", "mt5"):
        for account in accounts:
            if not account.is_mt5_account:
                continue
            deals = await _fetch_mt5_deals(account, start_ms, end_ms)
            for d in deals:
                dk = _mt5_ts_to_beijing_date(int(d.get("time", 0)))
                profit = float(d.get("profit", 0))
                mt5_rpnl[dk] += profit
                mt5_swap[dk] += float(d.get("swap", 0))
                mt5_comm[dk] += float(d.get("commission", 0))
                mt5_trades[dk] += 1
                if profit > 0:
                    mt5_wins[dk] += 1

    # 6) 按日组装：Binance(income-based) + MT5(NAV-based)
    #    Binance PnL = 纯 income-based（已结算收入，不含 TRANSFER 和 UPnL）
    #    MT5 PnL = deals-based (profit + swap + commission per closed trade)
    daily_list = []
    current = d_start
    while current <= d_end:
        dk = current.isoformat()

        # Binance: pure income-based PnL (no UPnL)
        binance_pnl = binance_income_pnl.get(dk, 0)

        # MT5: deals-based PnL (profit + swap + commission from closed trades)
        mt5_pnl = mt5_rpnl.get(dk, 0) + mt5_swap.get(dk, 0) + mt5_comm.get(dk, 0)

        net_pnl = binance_pnl + mt5_pnl

        daily_list.append({
            "date": dk,
            "realized_pnl": round(binance_rpnl.get(dk, 0) + mt5_rpnl.get(dk, 0), 2),
            "funding_fee": round(binance_ff.get(dk, 0), 2),
            "net_pnl": round(net_pnl, 2),
            "mt5_pnl": round(mt5_pnl, 2),
            "binance_pnl": round(binance_pnl, 2),
            "trade_count": binance_trades.get(dk, 0) + mt5_trades.get(dk, 0),
            "win_count": binance_wins.get(dk, 0) + mt5_wins.get(dk, 0),
            "platform_breakdown": {
                "binance": {
                    "realized_pnl": round(binance_rpnl.get(dk, 0), 2),
                    "funding_fee": round(binance_ff.get(dk, 0), 2),
                },
                "mt5": {
                    "realized_pnl": round(mt5_rpnl.get(dk, 0), 2),
                    "swap": round(mt5_swap.get(dk, 0), 2),
                    "commission": round(mt5_comm.get(dk, 0), 2),
                },
            },
        })

        current += timedelta(days=1)

    summary = _compute_summary(daily_list)
    resp = {"daily_pnl": daily_list, "summary": summary, "data_source": "income_deals_based"}

    logger.info(f"[PnL-NAV] user={current_user.username}, range={start_date}~{end_date}, "
                f"days={len(daily_list)}, cumulative={summary['cumulative_pnl']}")

    if ctx.is_sub:
        # 子账户: 按份额投影后再缓存(此前 bug: L646 缓存了未投影的父账号原始 resp,
        # 子账户第二次请求命中缓存→拿到未缩放值, 柱形图=父账号原值。改为缓存 scaled)。
        scaled = project_response(resp, ctx.multiplier)
        if isinstance(scaled, dict):
            scaled["data_source"] = "parent_raw_x_multiplier"
            scaled["note"] = "历史快照不足，采用父账号原始 PnL × 份额比例近似展示"
        _cache_set(cache_key, scaled)
        return scaled
    _cache_set(cache_key, resp)
    return resp


# 累计端点专用缓存(30min): 累计是慢变量, 全周期取数慢(实测365天~135s, 打交易所+多桥),
# 不需实时。首次慢、之后30min内秒回。与 /daily 的300s缓存分开。
_CUM_CACHE_TTL = 1800
# SWR 硬上限(6h): SOFT(30min)~HARD 之间返回旧值秒回+后台刷新, 超 HARD 才冷算。
_CUM_HARD_TTL = 21600


@router.get("/cumulative")
async def get_cumulative_pnl(
    platform: str = Query("all", description="平台过滤: all/binance/mt5"),
    view: str = Query("merged", description="收益视图: merged/<user_id>"),
    ctx: ViewContext = Depends(get_view_context),
    _bg: bool = False,   # 内部: 后台刷新调用时 True, 跳过 SWR 短路直接全量算
):
    """真正的"开户至今累计收益"(固定起点=账号首笔快照日, 不随前端范围/日期滚动变化)。

    背景: 前端累计卡片原先用"滚动N天窗口求和", 每天0点会因N天前那天滑出窗口而跳变
    (hcz987: 昨天1378今天639, 因5/21的+739滑出30天窗), 且"本月>累计"反直觉。
    本端点固定从 inception(account_snapshots 最早日)累加到今天, 给出稳定的总累计。
    内部复用 get_daily_pnl(start=inception, end=today) 求和; 带30min缓存抵消全周期取数慢。
    收益关联(20260620): inception 取账号集(view决定)最早快照日, 累计随 view 合并/单用户。
    """
    from app.models.user import User as _U
    async with AsyncSessionLocal() as db:
        _row = (await db.execute(select(_U).where(_U.user_id == ctx.data_user_id))).scalar_one_or_none()
        if not _row:
            return {"cumulative_pnl": 0, "inception_date": None, "end_date": None}
        uid = _row.user_id

    _ck = f"pnlcum:{uid}:{platform}:sub={ctx.is_sub}:view={view}:v3"
    # SWR(20260621): cumulative 冷启动慢(动态inception+全周期取数, cq002实测~6min)。过 SOFT
    # 后返回旧值秒回 + 后台刷新, 用户首次之后永不等。_bg 跳过短路直接全量算。
    if not _bg:
        _hit = _cache.get(_ck)
        if _hit is not None:
            _age = _time.time() - _cache_ts.get(_ck, 0)
            if _age < _CUM_CACHE_TTL:          # fresh(30min)
                return _hit
            if _age < _CUM_HARD_TTL:           # stale: 返回旧值 + 后台刷新(同key一个)
                _sk = "cum:" + _ck
                if _sk not in _inflight:
                    _inflight.add(_sk)
                    async def _refresh(_s=_sk):
                        try:
                            await get_cumulative_pnl(platform=platform, view=view, ctx=ctx, _bg=True)
                        except Exception as _e:
                            logger.warning(f"[PnL-CUM-SWR] bg refresh failed: {_e}")
                        finally:
                            _inflight.discard(_s)
                    try:
                        import asyncio as _aio
                        _aio.create_task(_refresh())
                    except RuntimeError:
                        _inflight.discard(_sk)
                return _hit
        # miss 或太旧: 冷启动同步算(下方)

    import datetime as _dtm
    today_bj = _dtm.datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    # 1) inception 计算
    if ctx.is_sub:
        # 子账号(20260620): 起点=首次入金登记时刻(订阅 created_at 最早), 而非父账号快照日。
        # daily 的 sub-path(per_share_replay)会自动按份额回放, 这里只需给对的起点。
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text(
                "SELECT MIN(COALESCE(invested_at, created_at)) FROM sub_account_subscriptions "
                "WHERE sub_user_id = CAST(:u AS UUID) AND status='active'"
            ), {"u": str(ctx.auth_user_id)})).first()
        inception = row[0].astimezone(timezone(timedelta(hours=8))).date().isoformat() if row and row[0] else None
    else:
        # 普通用户(20260621): inception = 账号集(view决定)的【最早真实成交日】(动态查交易所/桥),
        # 不再用 account_snapshots 快照日(快照晚于成交→截断早期对冲腿盈亏致累计失真)。
        # 账号集最早成交日是不变量, 缓存24h(查交易所慢)。
        from app.api.v1.subaccount import resolve_pnl_account_ids as _resolve_aids
        async with AsyncSessionLocal() as db:
            _aids = await _resolve_aids(db, str(uid), view=view, is_sub=ctx.is_sub)
            accounts = []
            if _aids:
                _r = await db.execute(select(Account).filter(Account.account_id.in_(_aids)))
                accounts = _r.scalars().all()
        if not accounts:
            inception = None
        else:
            _ick = f"incep:{uid}:view={view}"
            _icv = _inception_cache.get(_ick)
            if _icv is not None and _time.time() - _icv[1] < _INCEPTION_TTL:
                inception = _icv[0]
            else:
                inception = await _find_inception(accounts)
                _inception_cache[_ick] = (inception, _time.time())

    if not inception:
        out = {"cumulative_pnl": 0, "inception_date": None, "end_date": today_bj}
        _cache[_ck] = out; _cache_ts[_ck] = _time.time()
        return out

    # 2) 复用 /daily 全周期取数(inception→today), 求和 net_pnl = 真实总累计
    daily_resp = await get_daily_pnl(
        start_date=inception, end_date=today_bj, platform=platform, view=view, ctx=ctx
    )
    dl = daily_resp.get("daily_pnl", []) if isinstance(daily_resp, dict) else []
    cum = round(sum(float(x.get("net_pnl", 0)) for x in dl), 2)
    # 展示用起算日 = 首个有收益的真实成交日(inception 为探测下限, 之前可能有空白天)
    _nz = [x.get("date") for x in dl if abs(float(x.get("net_pnl", 0))) > 0.001]
    disp_inception = _nz[0] if _nz else inception

    out = {
        "cumulative_pnl": cum,
        "inception_date": disp_inception,
        "end_date": today_bj,
        "days": len(dl),
    }
    _cache[_ck] = out
    _cache_ts[_ck] = _time.time()
    logger.info(f"[PnL-CUM] user={uid} inception={inception} cumulative={cum} days={len(dl)}")
    return out


@router.get("/link-options")
async def get_pnl_view_options(ctx: ViewContext = Depends(get_view_context)):
    """收益视图下拉数据源(20260620): 返回当前登录用户(A)的 self + 关联用户(linked)。
    前端据此渲染"合并全部数据 / 各用户"下拉; 无 linked 时前端隐藏下拉。
    20260620修: 子账号(is_sub)按份额看父账号, 不应看到父账号的收益关联下拉, 故直接返回
    空 linked(前端据此屏蔽下拉)。普通用户用 data_user_id=自己。"""
    if ctx.is_sub:
        return {"self": None, "linked": []}
    from app.api.v1.subaccount import get_pnl_link_options as _opts
    async with AsyncSessionLocal() as db:
        return await _opts(db, str(ctx.data_user_id))


# ── 缓存预热(优化项4-加强, 20260621): 消除"首访35s" ────────────────────────
# 合并视图(有 user_pnl_links 的 owner)daily 冷启动要 30-70s。后台定时(< SOFT_TTL)为这些
# 用户预算 merged 视图的 daily(默认30天)+ cumulative, 让缓存常 fresh → 用户首次打开即秒回。
# 只预热"有关联的 owner"(merged 慢的根源); 普通无关联用户 daily 快, 不必预热。
_PREWARM_INTERVAL = 240   # 4min(< SOFT 300s, 保证缓存不掉出 fresh 窗)
_PREWARM_RANGE_DAYS = 30  # 前端默认范围


async def _prewarm_one(owner_uid: str):
    """为一个 owner 预热 merged 视图的 daily(30天) + cumulative。复用 _bg=True 全量算并写缓存。"""
    try:
        from app.api.v1.subaccount import get_view_context as _gvc
        ctx = await _gvc(owner_uid)
        if ctx.is_sub:
            return  # 子账户不预热(走份额路径, 另算)
        import datetime as _d
        end = _d.datetime.now(timezone(timedelta(hours=8))).date()
        start = end - _d.timedelta(days=_PREWARM_RANGE_DAYS)
        # _bg=False: 预热走与用户相同的 SWR+单飞锁路径 → 预热与并发用户冷启动共享同一次计算
        # (此前 _bg=True 绕过锁, 预热与用户会各算一次, 实测撞上76s)。fresh 时 noop, stale 时
        # 触发后台刷新, cold 时持锁计算一次。
        await get_daily_pnl(start_date=start.isoformat(), end_date=end.isoformat(),
                            platform="all", view="merged", ctx=ctx, _bg=False)
        # 累计用 _bg=True 强制重算写缓存(绕过SWR短路), 保持常热; 但仅在缓存接近过期时才真算,
        # 否则 30min内反复算太重 → 先看缓存年龄, fresh 则跳过。
        _cum_ck = f"pnlcum:{ctx.data_user_id}:all:sub=False:view=merged:v3"
        # 缺失(default 0→age极大)或接近过期(24min+)才刷新, 保持常热不空转
        _cum_age = _time.time() - _cache_ts.get(_cum_ck, 0)
        if _cum_ck not in _cache or _cum_age > _CUM_CACHE_TTL * 0.8:
            await get_cumulative_pnl(platform="all", view="merged", ctx=ctx, _bg=True)
    except Exception as e:
        logger.warning(f"[PnL-prewarm] owner={owner_uid[:8]} failed: {e}")


async def prewarm_loop():
    """每 _PREWARM_INTERVAL 秒为所有有收益关联的 owner 预热缓存(串行+间隔, 不打爆桥)。"""
    import asyncio as _aio
    logger.info("[PnL-prewarm] loop started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(text(
                    "SELECT DISTINCT owner_user_id::text FROM user_pnl_links"
                ))).fetchall()
            owners = [r[0] for r in rows]
            if owners:
                logger.info(f"[PnL-prewarm] warming {len(owners)} owner(s)")
                for uid in owners:
                    await _prewarm_one(uid)
                    await _aio.sleep(2)  # 间隔, 避免连续打桥
        except Exception as e:
            logger.warning(f"[PnL-prewarm] cycle error: {e}")
        await _aio.sleep(_PREWARM_INTERVAL)


