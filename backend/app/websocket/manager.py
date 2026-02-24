"""WebSocket connection manager for real-time updates"""
from typing import Dict, Set
from fastapi import WebSocket
import json
import asyncio


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        # Store active connections by user_id
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Store all connections (for broadcast)
        self.all_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, user_id: str = None):
        """Accept and register a new WebSocket connection"""
        await websocket.accept()
        self.all_connections.add(websocket)

        if user_id:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str = None):
        """Remove a WebSocket connection"""
        self.all_connections.discard(websocket)

        if user_id and user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific connection"""
        try:
            await websocket.send_json(message)
        except Exception:
            # Connection might be closed
            pass

    async def send_to_user(self, message: dict, user_id: str):
        """Send a message to all connections of a specific user"""
        if user_id in self.active_connections:
            disconnected = set()

            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.add(connection)

            # Clean up disconnected connections
            for connection in disconnected:
                self.disconnect(connection, user_id)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients"""
        disconnected = set()

        for connection in self.all_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected connections
        for connection in disconnected:
            self.all_connections.discard(connection)

    async def broadcast_market_data(self, spread_data: dict):
        """Broadcast market data to all connections"""
        message = {
            "type": "market_data",
            "data": spread_data,
        }
        await self.broadcast(message)

    async def send_risk_alert(self, user_id: str, alert_data: dict):
        """Send risk alert to a specific user"""
        message = {
            "type": "risk_alert",
            "data": alert_data,
        }
        await self.send_to_user(message, user_id)

    async def send_order_update(self, user_id: str, order_data: dict):
        """Send order update to a specific user"""
        message = {
            "type": "order_update",
            "data": order_data,
        }
        await self.send_to_user(message, user_id)

    async def broadcast_strategy_status(self, strategy_data: dict):
        """Broadcast strategy status to all connections"""
        message = {
            "type": "strategy_status",
            "data": strategy_data,
        }
        await self.broadcast(message)

    async def broadcast_account_balance(self, balance_data: dict):
        """Broadcast account balance to all connections"""
        message = {
            "type": "account_balance",
            "data": balance_data,
        }
        await self.broadcast(message)

    async def broadcast_position_update(self, position_data: dict):
        """Broadcast position update to all connections"""
        message = {
            "type": "position_update",
            "data": position_data,
        }
        await self.broadcast(message)

    async def broadcast_risk_metrics(self, risk_data: dict):
        """Broadcast risk metrics to all connections"""
        message = {
            "type": "risk_metrics",
            "data": risk_data,
        }
        await self.broadcast(message)

    def get_connection_count(self) -> int:
        """Get total number of active connections"""
        return len(self.all_connections)

    def get_user_connection_count(self, user_id: str) -> int:
        """Get number of connections for a specific user"""
        return len(self.active_connections.get(user_id, set()))


# Global connection manager instance
manager = ConnectionManager()
