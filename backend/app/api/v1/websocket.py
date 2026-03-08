"""WebSocket endpoint handlers"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from app.websocket.manager import manager
from app.core.security import decode_access_token
from pydantic import BaseModel, Field
import asyncio

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

            # Echo back (can be extended for client commands)
            await manager.send_personal_message(
                {"type": "echo", "message": data},
                websocket,
            )

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        manager.disconnect(websocket, user_id)


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
