"""WebSocket endpoint handlers"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from app.websocket.manager import manager
from app.core.security import decode_access_token
import asyncio

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None, description="JWT token for authentication"),
):
    """WebSocket endpoint for real-time updates

    Connect with: ws://localhost:8000/ws?token=YOUR_JWT_TOKEN
    """
    user_id = None

    # Authenticate if token provided
    if token:
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
        except Exception:
            await websocket.close(code=1008, reason="Invalid token")
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
    """Get WebSocket connection statistics"""
    return {
        "total_connections": manager.get_connection_count(),
        "user_connections": len(manager.active_connections),
    }
