"""WebSocket endpoint handlers"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from app.websocket.manager import manager
from app.core.security import decode_access_token
from pydantic import BaseModel, Field
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class StreamerConfigUpdate(BaseModel):
    """Model for updating streamer configuration"""
    streamer: str = Field(..., description="Streamer name: market_data, account_balance, risk_metrics, mt5_connection")
    interval: float = Field(..., description="New interval in seconds", gt=0)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication (required)"),
):
    """WebSocket endpoint for real-time updates

    SECURITY: Token authentication is required
    Connect with: ws://localhost:8000/ws?token=YOUR_JWT_TOKEN
    """
    user_id = None

    # Authenticate token (REQUIRED)
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008, reason="Invalid token: missing user_id")
            return
    except Exception as e:
        await websocket.close(code=1008, reason=f"Authentication failed: {str(e)}")
        return

    # Accept connection
    await manager.connect(websocket, user_id)

    try:
        # Send welcome message
        await manager.send_personal_message(
            {
                "type": "connection",
                "message": "Connected to Hustle XAU Arbitrage System",
                "user_id": user_id,
            },
            websocket,
        )

        # Keep connection alive and handle incoming messages
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            # Handle client commands
            try:
                msg = json.loads(data)
                if msg.get("type") == "request_snapshot":
                    asyncio.create_task(_push_initial_snapshot(websocket, user_id))
                    continue
            except (json.JSONDecodeError, AttributeError):
                pass

            # Echo back unknown messages
            await manager.send_personal_message(
                {"type": "echo", "message": data},
                websocket,
            )

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        manager.disconnect(websocket, user_id)


async def _push_initial_snapshot(websocket: WebSocket, user_id: str = None):
    """Push initial position_snapshot to a freshly-connected client.

    Strict per-user isolation:
      - MT5 positions are read from THIS user\'s MT5 bridges only
        (mt5_clients.account_id → accounts.user_id).
      - Binance positions are read from THIS user\'s Binance accounts only.
      - Output payload includes a `pairs` map keyed by pair_code, matching the
        Publisher A format consumed by frontend stores/market.js.
    """
    try:
        from app.models.account import Account
        from app.services.binance_client import BinanceFuturesClient
        from app.services.hedging_pair_service import hedging_pair_service
        from app.core.database import get_db_context
        from sqlalchemy import select, text as _text
        from uuid import UUID as _UUID
        import httpx, os

        if not user_id:
            return

        # 1) Load active hedging pairs (pair_code → sym_a, sym_b)
        pairs_meta = {}
        try:
            for pair in (hedging_pair_service.list_active_pairs() or []):
                if not pair.is_active:
                    continue
                sa = pair.symbol_a.symbol if pair.symbol_a else None
                sb = pair.symbol_b.symbol if pair.symbol_b else None
                if sa and sb:
                    pairs_meta[pair.pair_code] = {"sym_a": sa, "sym_b": sb}
        except Exception as e:
            logger.warning(f"[SNAPSHOT] pairs load failed: {e}")

        if not pairs_meta:
            pairs_meta["XAU"] = {"sym_a": "XAUUSDT", "sym_b": "XAUUSD+"}

        # 2) Read this user\'s Binance positions per-symbol
        bn_by_symbol: dict = {}
        async with get_db_context() as db:
            result = await db.execute(
                select(Account).where(
                    Account.is_active == True,
                    Account.user_id == _UUID(user_id),
                )
            )
            user_accounts = result.scalars().all()

            # Resolve this user\'s MT5 bridge URLs
            mt5_bridges: list = []
            try:
                rows = await db.execute(_text(
                    "SELECT mc.bridge_url, mc.bridge_service_port "
                    "FROM mt5_clients mc JOIN accounts a ON mc.account_id = a.account_id "
                    "WHERE mc.is_active = true AND mc.is_system_service = false "
                    "AND a.user_id = :uid"
                ), {"uid": _UUID(user_id)})
                for row in rows.fetchall():
                    url = row[0] or (f"http://172.31.14.113:{row[1]}" if row[1] else None)
                    if url:
                        mt5_bridges.append(url)
            except Exception as e:
                logger.warning(f"[SNAPSHOT] bridge query failed: {e}")

        # Binance per-symbol query
        for acc in user_accounts:
            if acc.platform_id != 1 or not acc.api_key or not acc.api_secret:
                continue
            try:
                client = BinanceFuturesClient(acc.api_key, acc.api_secret)
                # Query each pair\'s side-A symbol
                for meta in pairs_meta.values():
                    sym_a = meta["sym_a"]
                    try:
                        pos_data = await client.get_position_risk(sym_a)
                    except Exception:
                        continue
                    long_v, short_v = bn_by_symbol.get(sym_a, (0.0, 0.0))
                    for pos in (pos_data or []):
                        amt = float(pos.get("positionAmt", 0))
                        ps = (pos.get("positionSide") or "BOTH").upper()
                        if ps == "LONG" and amt > 0:
                            long_v += amt
                        elif ps == "SHORT" and amt < 0:
                            short_v += abs(amt)
                        else:  # BOTH
                            if amt > 0:
                                long_v += amt
                            elif amt < 0:
                                short_v += abs(amt)
                    bn_by_symbol[sym_a] = (round(long_v, 3), round(short_v, 3))
                await client.close()
            except Exception as e:
                logger.warning(f"[SNAPSHOT] Binance read failed for {acc.account_id}: {e}")

        # 3) MT5 per-symbol query — concurrent across this user\'s bridges
        mt5_by_symbol: dict = {}
        api_key = os.getenv("MT5_API_KEY", os.getenv("MT5_BRIDGE_API_KEY", ""))
        headers = {"X-Api-Key": api_key} if api_key else {}
        if mt5_bridges:
            async with httpx.AsyncClient(timeout=3.0) as cli:
                for url in mt5_bridges:
                    try:
                        resp = await cli.get(f"{url}/mt5/positions", headers=headers)
                        if resp.status_code != 200:
                            continue
                        for p in resp.json().get("positions", []):
                            sym = p.get("symbol", "")
                            if not sym:
                                continue
                            vol = float(p.get("volume", 0))
                            typ = p.get("type", -1)
                            l, s = mt5_by_symbol.get(sym, (0.0, 0.0))
                            if typ == 0:
                                l += vol
                            elif typ == 1:
                                s += vol
                            mt5_by_symbol[sym] = (round(l, 4), round(s, 4))
                    except Exception as e:
                        logger.debug(f"[SNAPSHOT] MT5 bridge {url} read error: {e}")

        # 4) Compose pairs payload
        pairs_out = {}
        for pc, meta in pairs_meta.items():
            sa, sb = meta["sym_a"], meta["sym_b"]
            bn_l, bn_s = bn_by_symbol.get(sa, (0.0, 0.0))
            mt5_l, mt5_s = mt5_by_symbol.get(sb, (0.0, 0.0))
            if mt5_l == 0.0 and mt5_s == 0.0:
                alt = sb.replace("+", ".s")
                mt5_l, mt5_s = mt5_by_symbol.get(alt, (0.0, 0.0))
            pairs_out[pc] = {
                "mt5_long": mt5_l, "mt5_short": mt5_s,
                "binance_long": bn_l, "binance_short": bn_s,
            }

        xau_pd = pairs_out.get("XAU", {})
        await manager.send_personal_message(
            {
                "type": "position_snapshot",
                "data": {
                    "bybit_long_lots":  xau_pd.get("mt5_long", 0.0),
                    "bybit_short_lots": xau_pd.get("mt5_short", 0.0),
                    "binance_long_xau": xau_pd.get("binance_long", 0.0),
                    "binance_short_xau": xau_pd.get("binance_short", 0.0),
                    "pairs": pairs_out,
                },
            },
            websocket,
        )
        logger.info(f"[SNAPSHOT] Initial push for user={user_id} pairs={list(pairs_out.keys())}")
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Initial push failed: {e}")


@router.get("/ws/stats")
async def get_websocket_stats():
    """Get comprehensive WebSocket statistics

    Returns:
        - Connection statistics
        - Broadcast streamer statistics
        - Performance metrics
    """
    from app.tasks.market_data import market_streamer
    from app.tasks.broadcast_tasks import account_balance_streamer, risk_metrics_streamer, mt5_connection_streamer
    from datetime import datetime

    def get_streamer_stats(streamer, name):
        """安全地获取streamer统计信息"""
        try:
            return {
                "running": getattr(streamer, 'running', False),
                "interval_ms": getattr(streamer, 'interval', 1) * 1000,
                "broadcast_count": getattr(streamer, 'broadcast_count', 0),
                "last_broadcast": getattr(streamer, 'last_broadcast_time', None),
                "error_count": getattr(streamer, 'error_count', 0)
            }
        except Exception as e:
            return {
                "running": False,
                "interval_ms": 0,
                "broadcast_count": 0,
                "last_broadcast": None,
                "error_count": 0,
                "error": str(e)
            }

    return {
        "connections": {
            "total": manager.get_connection_count(),
            "by_user": len(manager.active_connections),
            "users": list(manager.active_connections.keys())
        },
        "streamers": {
            "market_data": get_streamer_stats(market_streamer, "market_data"),
            "account_balance": get_streamer_stats(account_balance_streamer, "account_balance"),
            "risk_metrics": get_streamer_stats(risk_metrics_streamer, "risk_metrics"),
            "mt5_connection": get_streamer_stats(mt5_connection_streamer, "mt5_connection")
        },
        "server_time": datetime.now().isoformat()
    }


@router.post("/ws/config")
async def update_streamer_config(config: StreamerConfigUpdate):
    """Update streamer configuration (push frequency)

    Args:
        config: Streamer configuration update

    Returns:
        Updated configuration

    Raises:
        HTTPException: If streamer not found or interval out of range
    """
    from app.tasks.market_data import market_streamer
    from app.tasks.broadcast_tasks import account_balance_streamer, risk_metrics_streamer, mt5_connection_streamer

    streamers = {
        "market_data": market_streamer,
        "account_balance": account_balance_streamer,
        "risk_metrics": risk_metrics_streamer,
        "mt5_connection": mt5_connection_streamer
    }

    if config.streamer not in streamers:
        raise HTTPException(status_code=404, detail=f"Streamer '{config.streamer}' not found")

    streamer = streamers[config.streamer]

    # Update interval with validation
    success = streamer.update_interval(config.interval)

    if not success:
        # Get valid range based on streamer type
        if config.streamer == "market_data":
            valid_range = "0.1s - 10s"
        elif config.streamer == "account_balance":
            valid_range = "5s - 60s"
        else:  # risk_metrics, mt5_connection
            valid_range = "10s - 120s"

        raise HTTPException(
            status_code=400,
            detail=f"Interval out of range. Valid range for {config.streamer}: {valid_range}"
        )

    return {
        "success": True,
        "streamer": config.streamer,
        "interval": streamer.interval,
        "interval_ms": streamer.interval * 1000,
        "message": f"Updated {config.streamer} interval to {streamer.interval}s"
    }
