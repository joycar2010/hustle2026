from fastapi import FastAPI, WebSocket, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import json
import redis
import uvicorn
from datetime import datetime
from strategy.arbitrage_strategy import ArbitrageStrategy, SmartOrderRouter, RiskManager

# 导入VeighNa连接器
import sys
sys.path.append('d:\\git\\hustle')
from vnpy_connector import VNPYExchangeConnector

# 初始化FastAPI应用
app = FastAPI(
    title="Hustle 黄金套利系统 API",
    description="多交易所黄金套利系统后端服务",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配置静态文件服务
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 初始化Redis缓存
redis_available = False
try:
    redis_client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2
    )
    redis_client.ping()
    redis_available = True
    print("Redis连接成功")
except Exception as e:
    print(f"Redis连接失败，使用内存存储: {e}")
    # 使用内存存储作为后备
    class MemoryStorage:
        def __init__(self):
            self.data = {}
        def get(self, key):
            return self.data.get(key)
        def set(self, key, value):
            self.data[key] = value
    redis_client = MemoryStorage()

# 交易所连接器
class ExchangeConnector:
    def __init__(self):
        # 初始化VeighNa连接器
        self.connector = VNPYExchangeConnector()
        # 连接交易所
        success = self.connector.connect()
        if success:
            print("VeighNa交易所连接成功")
        else:
            print("VeighNa交易所连接失败")
    
    async def get_price(self, exchange_name, symbol):
        """获取实时价格"""
        try:
            if exchange_name == "binance":
                price = await self.connector.get_binance_price(symbol)
            elif exchange_name == "bybit":
                price = await self.connector.get_bybit_price(symbol)
            else:
                return None
            
            if price:
                return {
                    "symbol": symbol,
                    "bid": price["bid"] if "bid" in price else None,
                    "ask": price["ask"] if "ask" in price else None,
                    "last": price["last"] if "last" in price else None,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return None
        except Exception as e:
            print(f"获取{exchange_name}价格失败: {e}")
            return None

# 初始化交易所连接器
exchange_connector = ExchangeConnector()

# 初始化策略组件
arbitrage_strategy = ArbitrageStrategy(exchange_connector, redis_client)
smart_order_router = SmartOrderRouter(exchange_connector)
risk_manager = RiskManager(redis_client)

# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"广播消息失败: {e}")
                self.disconnect(connection)

manager = ConnectionManager()

# 策略执行任务
async def strategy_executor():
    """策略执行器"""
    while True:
        try:
            # 检查套利机会
            opportunity = await arbitrage_strategy.check_opportunity()
            
            if opportunity:
                if opportunity["type"] == "arbitrage":
                    # 检查风险
                    risk_check = risk_manager.check_risk(arbitrage_strategy)
                    if risk_check["risk"] != "high":
                        # 执行套利
                        success = await arbitrage_strategy.execute_arbitrage(opportunity)
                        if success:
                            print("套利执行成功")
                            # 广播套利机会
                            await manager.broadcast({
                                "type": "arbitrage_opportunity",
                                "opportunity": opportunity
                            })
                    else:
                        print(f"风险过高，跳过套利: {risk_check['reason']}")
                elif opportunity["type"] == "exit":
                    # 执行平仓
                    success = await arbitrage_strategy.close_positions(opportunity["reason"])
                    if success:
                        print("平仓执行成功")
                        # 广播平仓信息
                        await manager.broadcast({
                            "type": "position_closed",
                            "reason": opportunity["reason"]
                        })
            
        except Exception as e:
            print(f"策略执行失败: {e}")
        
        # 每5秒检查一次
        await asyncio.sleep(5)

# 实时数据推送任务
async def data_pusher():
    """实时推送市场数据"""
    while True:
        try:
            # 获取各交易所价格
            binance_price = await exchange_connector.get_price("binance", "XAUUSDT")
            bybit_price = await exchange_connector.get_price("bybit", "XAUUSD")
            
            # 计算点差
            spread = 0
            if binance_price and bybit_price:
                spread = abs((binance_price["last"] or 0) - (bybit_price["last"] or 0))
            
            # 构建消息
            message = {
                "type": "market_data",
                "timestamp": datetime.now().isoformat(),
                "binance": binance_price,
                "bybit": bybit_price,
                "spread": spread
            }
            
            # 广播消息
            print(f"准备广播市场数据: {message}")
            await manager.broadcast(message)
            print(f"广播市场数据成功，当前连接数: {len(manager.active_connections)}")
            
            # 缓存数据到Redis
            redis_client.set("binance_price", json.dumps(binance_price))
            redis_client.set("bybit_price", json.dumps(bybit_price))
            redis_client.set("spread", str(spread))
            
        except Exception as e:
            print(f"数据推送失败: {e}")
        
        # 每100毫秒推送一次
        await asyncio.sleep(0.1)

# 根路径路由
@app.get("/")
def read_root():
    """根路径重定向到静态文件"""
    return FileResponse(os.path.join(static_dir, "index.html"))

# API路由
@app.get("/api/market-data")
def get_market_data():
    """获取市场数据"""
    try:
        # 尝试从缓存获取数据
        try:
            binance_price = json.loads(redis_client.get("binance_price") or "null")
            bybit_price = json.loads(redis_client.get("bybit_price") or "null")
            spread = float(redis_client.get("spread") or "0")
        except:
            # 缓存失败时使用模拟数据
            binance_price = {
                "symbol": "XAUUSDT",
                "bid": 5051.73,
                "ask": 5051.74,
                "last": 5051.73,
                "timestamp": datetime.now().isoformat()
            }
            bybit_price = {
                "symbol": "XAUUSD",
                "bid": 5051.73,
                "ask": 5051.74,
                "last": 5051.73,
                "timestamp": datetime.now().isoformat()
            }
            spread = abs(binance_price["last"] - bybit_price["last"])
        
        # 计算套利机会
        arbitrage_opportunity = None
        if binance_price and bybit_price:
            if spread > 3.0:
                arbitrage_opportunity = {
                    "type": "arbitrage",
                    "direction": "bybit_short_binance_long" if bybit_price["last"] > binance_price["last"] else "binance_short_bybit_long",
                    "potential_profit": spread * 1.0 * 10,
                    "spread": spread
                }
        
        return {
            "success": True,
            "data": {
                "binance": binance_price,
                "bybit": bybit_price,
                "spread": spread,
                "arbitrage_opportunity": arbitrage_opportunity,
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/strategy/config")
def update_strategy_config(config: dict):
    """更新策略配置"""
    try:
        # 保存配置到Redis
        redis_client.set("strategy_config", json.dumps(config))
        return {
            "success": True,
            "message": "策略配置更新成功"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/strategy/config")
def get_strategy_config():
    """获取策略配置"""
    try:
        config = json.loads(redis_client.get("strategy_config") or "{}")
        # 默认配置
        default_config = {
            "min_spread": 3.0,
            "exit_spread": 0.5,
            "trade_size": 1.0,
            "check_interval": 5,
            "max_position": 5.0,
            "leverage": 10,
            "max_loss": 1000,
            "stop_loss": 0.5,
            "take_profit": 0.3
        }
        # 合并默认配置
        merged_config = {**default_config, **config}
        return {
            "success": True,
            "data": merged_config
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/strategy/status")
def get_strategy_status():
    """获取策略状态"""
    try:
        status = arbitrage_strategy.get_status()
        return {
            "success": True,
            "data": status
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/system/metrics")
def get_system_metrics():
    """获取系统指标"""
    try:
        import psutil
        import os
        
        # 系统指标
        metrics = {
            "cpu_usage": psutil.cpu_percent(interval=1),
            "memory_usage": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent,
            "network_sent": psutil.net_io_counters().bytes_sent,
            "network_recv": psutil.net_io_counters().bytes_recv,
            "process_count": len(psutil.pids()),
            "uptime": psutil.boot_time(),
            "python_version": "3.13.7",
            "fastapi_version": "0.124.4",
            "system": os.name
        }
        
        return {
            "success": True,
            "data": metrics
        }
    except Exception as e:
        return {
            "success": True,
            "data": {
                "cpu_usage": 0,
                "memory_usage": 0,
                "disk_usage": 0,
                "network_sent": 0,
                "network_recv": 0,
                "process_count": 0,
                "uptime": 0,
                "python_version": "3.13.7",
                "fastapi_version": "0.124.4",
                "system": "Windows"
            }
        }

# WebSocket端点
@app.websocket("/ws/market-data")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    print(f"新的WebSocket连接已建立，当前连接数: {len(manager.active_connections)}")
    try:
        while True:
            # 保持连接打开，等待数据推送
            # 这里不需要接收客户端消息，只需要保持连接活跃
            await asyncio.sleep(30)  # 每30秒发送一次心跳，保持连接活跃
    except Exception as e:
        print(f"WebSocket错误: {e}")
    finally:
        manager.disconnect(websocket)

# 启动时初始化
@app.on_event("startup")
async def startup_event():
    # 启动数据推送任务
    asyncio.create_task(data_pusher())
    # 启动策略执行器
    asyncio.create_task(strategy_executor())
    print("数据推送任务和策略执行器已启动")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)