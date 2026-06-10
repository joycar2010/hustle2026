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
from app.core.database import get_db
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


def _cache_get(key: str):
    if key in _cache and _time.time() - _cache_ts.get(key, 0) < CACHE_TTL:
        return _cache[key]
    return None


def _cache_set(key: str, val):
    _cache[key] = val
    _cache_ts[key] = _time.time()


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
    """获取 Binance income 记录（自动分页，limit=1000/次）"""
    client = BinanceFuturesClient(
        account.api_key, account.api_secret,
        proxy_url=build_proxy_url(account.proxy_config)
    )
    all_records = []
    cursor_start = start_ms
    try:
        for _ in range(20):
            records = await client.get_income(
                income_type=income_type,
                start_time=cursor_start,
                end_time=end_ms,
                limit=1000,
            )
            if not records:
                break
            all_records.extend(records)
            if len(records) < 1000:
                break
            cursor_start = int(records[-1].get("time", 0)) + 1
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


async def _fetch_mt5_deals(account, start_ms: int, end_ms: int, db: AsyncSession) -> list:
    """获取 MT5 平仓 deal（entry==1），从该 account 下所有活跃 bridge 聚合并按 ticket 去重"""
    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
    api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", "OQ6bUimHZDmXEZzJKE"))
    headers = {"X-Api-Key": api_key} if api_key else {}

    try:
        result = await db.execute(
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
    days = max(1, int((now_utc - start_dt).total_seconds() / 86400) + 2)
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


async def _fetch_mt5_cashflows(account, start_ms: int, end_ms: int, db: AsyncSession) -> list:
    """获取 MT5 入出金记录，从该 account 下所有活跃 bridge 聚合并按 ticket 去重"""
    bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113")
    api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", "OQ6bUimHZDmXEZzJKE"))
    headers = {"X-Api-Key": api_key} if api_key else {}

    try:
        result = await db.execute(
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
    days = max(1, int((now_utc - start_dt).total_seconds() / 86400) + 2)
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


async def _fetch_daily_closing_nav(account_ids: list, start_date: str, end_date: str, db: AsyncSession) -> dict:
    """从 account_snapshots 查询每天收盘净值（北京时间最后一条快照）
    Returns: {date_str: total_nav_float}
    """
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
    ctx: ViewContext = Depends(get_view_context),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User as _U
    _row = (await db.execute(__import__('sqlalchemy').select(_U).where(_U.user_id == ctx.data_user_id))).scalar_one_or_none()
    current_user = _row

    if ctx.is_sub:
        from sqlalchemy import text as _text
        _row_sub = (await db.execute(_text(
            "SELECT MIN(created_at) FROM sub_account_subscriptions WHERE sub_user_id = CAST(:u AS UUID) AND status='active'"
        ), {"u": ctx.auth_user_id})).first()
        if _row_sub and _row_sub[0]:
            _join_date_str = _row_sub[0].astimezone().strftime('%Y-%m-%d')
            if _join_date_str > start_date:
                start_date = _join_date_str

    cache_key = f"pnl:{current_user.user_id}:{start_date}:{end_date}:{platform}:sub={ctx.is_sub}:v3"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # ── Sub path: per-share NAV replay ──
    if ctx.is_sub:
        from app.services.subaccount_nav import (
            list_parent_daily_navs, list_active_subscriptions_by_sub,
        )
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

    result = await db.execute(select(Account).filter(Account.user_id == current_user.user_id))
    accounts = result.scalars().all()
    if not accounts:
        return {"daily_pnl": [], "summary": _compute_summary([])}

    active_account_ids = [str(a.account_id) for a in accounts if a.is_active]

    # 1) 日期范围 + 分平台 NAV / UPL
    from datetime import date as _date
    d_start = _date.fromisoformat(start_date)
    d_end = _date.fromisoformat(end_date)
    prev_date = (d_start - timedelta(days=1)).isoformat()

    # NAV 计算包含所有活跃 MT5 账户（SUM 天然处理多账户迁移场景）
    mt5_account_ids = [str(a.account_id) for a in accounts if a.is_active and a.is_mt5_account]
    binance_account_ids = [str(a.account_id) for a in accounts if a.is_active and a.platform_id == 1]

    mt5_nav_by_date = await _fetch_daily_closing_nav(
        mt5_account_ids, prev_date, end_date, db
    ) if mt5_account_ids else {}



    # 2) Binance 全量 income（PnL = 所有已结算收入（不含 TRANSFER）+ UPL 变动）
    binance_income_pnl = defaultdict(float)

    # 3) MT5 入出金（entry=0, symbol 为空的 deals）
    mt5_cashflows = defaultdict(float)
    _bound_b_result = await db.execute(text(
        "SELECT DISTINCT account_b_id FROM user_pair_accounts WHERE user_id = :uid AND account_b_id IS NOT NULL"
    ), {"uid": str(current_user.user_id)})
    _bound_b_ids = {str(r[0]) for r in _bound_b_result.fetchall()}

    if platform in ("all", "mt5"):
        for account in accounts:
            if not account.is_mt5_account or not account.is_active:
                continue
            cf_deals = await _fetch_mt5_cashflows(account, start_ms, end_ms, db)
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
            if account.platform_id != 1 or not account.is_active:
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
            if not account.is_mt5_account or not account.is_active:
                continue
            deals = await _fetch_mt5_deals(account, start_ms, end_ms, db)
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
    _cache_set(cache_key, resp)

    logger.info(f"[PnL-NAV] user={current_user.username}, range={start_date}~{end_date}, "
                f"days={len(daily_list)}, cumulative={summary['cumulative_pnl']}")

    if ctx.is_sub:
        scaled = project_response(resp, ctx.multiplier)
        if isinstance(scaled, dict):
            scaled["data_source"] = "parent_raw_x_multiplier"
            scaled["note"] = "历史快照不足，采用父账号原始 PnL × 份额比例近似展示"
        return scaled
    return resp
