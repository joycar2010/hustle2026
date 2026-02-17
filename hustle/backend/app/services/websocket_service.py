import asyncio
import logging
import json
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
import redis
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True
        )
        self.is_running = False
        self.tasks = []

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"WebSocket connected for user: {user_id}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
            logger.info(f"WebSocket disconnected for user: {user_id}")

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Send message error: {e}")
                    disconnected.add(connection)
            
            for connection in disconnected:
                self.active_connections[user_id].discard(connection)

    async def broadcast(self, message: dict):
        disconnected_users = []
        for user_id, connections in self.active_connections.items():
            disconnected = set()
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Broadcast message error: {e}")
                    disconnected.add(connection)
            
            for connection in disconnected:
                connections.discard(connection)
            
            if not connections:
                disconnected_users.append(user_id)
        
        for user_id in disconnected_users:
            del self.active_connections[user_id]

class WebSocketService:
    def __init__(self):
        self.manager = WebSocketManager()
        self.is_running = False
        self.tasks = []

    async def start(self):
        self.is_running = True
        self.tasks.append(asyncio.create_task(self._monitor_market_data()))
        self.tasks.append(asyncio.create_task(self._monitor_risk_alerts()))
        self.tasks.append(asyncio.create_task(self._monitor_operation_notifications()))
        logger.info("WebSocket推送服务已启动")

    async def stop(self):
        self.is_running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("WebSocket推送服务已停止")

    async def _monitor_market_data(self):
        while self.is_running:
            try:
                # 监控行情数据变化
                binance_data = self.manager.redis_client.hgetall("market:binance:XAUUSDT")
                bybit_data = self.manager.redis_client.hgetall("market:bybit_mt5:XAUUSD.s")
                spread_data = self.manager.redis_client.hgetall("market:spread:XAU")
                
                if binance_data and bybit_data and spread_data:
                    message = {
                        "type": "market_data",
                        "data": {
                            "binance": binance_data,
                            "bybit": bybit_data,
                            "spread": spread_data
                        }
                    }
                    await self.manager.broadcast(message)
            except Exception as e:
                logger.error(f"监控行情数据异常: {e}")
            await asyncio.sleep(1)

    async def _monitor_risk_alerts(self):
        while self.is_running:
            try:
                # 监控风控提示
                from ..models import RiskAlert
                from ..core.database import SessionLocal
                
                db = SessionLocal()
                try:
                    recent_alerts = db.query(RiskAlert).order_by(
                        RiskAlert.create_time.desc()
                    ).limit(10).all()
                    
                    for alert in recent_alerts:
                        message = {
                            "type": "risk_alert",
                            "data": {
                                "alert_id": str(alert.alert_id),
                                "user_id": str(alert.user_id),
                                "level": alert.alert_level,
                                "message": alert.alert_message,
                                "create_time": alert.create_time.isoformat()
                            }
                        }
                        await self.manager.send_personal_message(
                            message, str(alert.user_id)
                        )
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"监控风控提示异常: {e}")
            await asyncio.sleep(5)

    async def _monitor_operation_notifications(self):
        while self.is_running:
            try:
                # 监控操作通知
                # 这里可以从 Redis 中读取操作通知队列
                notification = self.manager.redis_client.lpop("notifications:operation")
                if notification:
                    try:
                        message = json.loads(notification)
                        if "user_id" in message:
                            await self.manager.send_personal_message(
                                message, message["user_id"]
                            )
                        else:
                            await self.manager.broadcast(message)
                    except json.JSONDecodeError:
                        logger.error("Invalid notification format")
            except Exception as e:
                logger.error(f"监控操作通知异常: {e}")
            await asyncio.sleep(0.1)

# 全局 WebSocket 服务实例
websocket_service = WebSocketService()
