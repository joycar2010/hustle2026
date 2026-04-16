"""MT5 User Bridge Proxy — 代理到交易账户 MT5 Bridge（8002）

供 www.hustle2026.xyz 前端调用:
1. /mt5-user/account/info  — 实时账户信息含浮动盈亏（profit）
2. /mt5-user/account/balance — 账户余额
3. /mt5-user/positions      — 持仓列表
4. /mt5-user/connection/status — 连接状态

认证策略：无需认证（内网 Bridge 数据，www 站点用户已通过登录控制访问）

交易历史（/orders/history）：
从 MT5 Bridge deals + 账户 DB 中汇总，供 www History 页面展示
"""
import os
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter()

MT5_USER_URL = os.getenv("MT5_USER_SERVICE_URL", "http://172.31.14.113:8002")
MT5_API_KEY  = os.getenv("MT5_API_KEY", "")
_HEADERS = {"X-Api-Key": MT5_API_KEY} if MT5_API_KEY else {}


async def _get(path: str, params: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(f"{MT5_USER_URL}{path}", headers=_HEADERS, params=params or {})
        resp.raise_for_status()
        return resp.json()


# ── MT5 账户信息（无认证，5秒刷新） ─────────────────────────────────────────

@router.get("/mt5-user/account/info")
async def user_account_info():
    """返回交易账户（8002）的账户信息，含 profit（实时浮动盈亏）"""
    return await _get("/mt5/account/info")


@router.get("/mt5-user/account/balance")
async def user_account_balance():
    return await _get("/mt5/account/balance")


@router.get("/mt5-user/positions")
async def user_positions():
    return await _get("/mt5/positions")


@router.get("/mt5-user/connection/status")
async def user_connection_status():
    return await _get("/mt5/connection/status")


# ── 交易历史（供 www History 页面） ─────────────────────────────────────────
# History.js 调用优先级:
#   1. GET /api/v1/orders/history?start_time=...&end_time=...
#   2. fallback: GET /api/v1/trading/history?start_time=...&end_time=...
#
# 数据来源: MT5 Bridge /mt5/history/deals（symbol=XAUUSD+，type 0/1 为实际交易）
# 返回格式兼容 History.js: [{order_id, symbol, side, price, quantity,
#                             filled_quantity, pnl, realized_pnl, created_at,
#                             filled_at, fee, status, platform}]

@router.get("/orders/history")
async def orders_history(
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    days: int = Query(30),
):
    """
    返回交易历史，来自 MT5 Bridge 成交记录（deals）。
    供 www.hustle2026.xyz/history 页面展示。
    """
    try:
        # 根据时间范围计算查询天数
        if start_time:
            try:
                fmt = "%Y-%m-%dT%H:%M:%S" if "T" in start_time else "%Y-%m-%d %H:%M:%S"
                t_start = datetime.strptime(start_time, fmt)
                days = max(1, (datetime.utcnow() - t_start).days + 1)
            except Exception:
                pass

        data = await _get("/mt5/history/deals", {"days": min(days, 365)})
        raw_deals = data.get("deals", [])

        # 过滤: 只要有真实 symbol 的交易（排除余额充值 type=2）
        # type: 0=Buy(开多/平空), 1=Sell(开空/平多), 2=Balance
        deals = [
            d for d in raw_deals
            if d.get("symbol") and d.get("volume", 0) > 0
        ]

        # 时间过滤
        if end_time:
            try:
                fmt = "%Y-%m-%dT%H:%M:%S" if "T" in end_time else "%Y-%m-%d %H:%M:%S"
                t_end = datetime.strptime(end_time, fmt)
                t_end_ts = t_end.timestamp()
                deals = [d for d in deals if d.get("time", 0) <= t_end_ts]
            except Exception:
                pass

        # 转换为 History.js 期待的格式
        records = []
        for d in sorted(deals, key=lambda x: x.get("time", 0), reverse=True):
            ts = d.get("time", 0)
            dt_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S") if ts else None
            side = "buy" if d.get("type", 0) == 0 else "sell"
            pnl = float(d.get("profit", 0))
            fee = abs(float(d.get("commission", 0)))
            records.append({
                "order_id":       str(d.get("ticket", "")),
                "symbol":         d.get("symbol", ""),
                "side":           side,
                "price":          float(d.get("price", 0)),
                "quantity":       float(d.get("volume", 0)),
                "filled_quantity": float(d.get("volume", 0)),
                "pnl":            pnl,
                "realized_pnl":   pnl,
                "fee":            fee,
                "status":         "FILLED",
                "platform":       "MT5",
                "created_at":     dt_str,
                "filled_at":      dt_str,
            })

        return records

    except Exception as e:
        return []
