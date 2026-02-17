import asyncio
import websockets
import json
import logging
import requests
from datetime import datetime
from typing import Dict
from ..core.redis import get_redis
from ..core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MarketDataService:
    def __init__(self):
        self.redis_client = get_redis()
        self.is_running = False
        self.tasks = []
        self.bybit_mt5_credentials = {
            "account_id": settings.MT5_ACCOUNT_ID or "5229471",
            "password": settings.MT5_PASSWORD or "Lk106504!",
            "server": settings.MT5_SERVER or "Bybit-Live-2"
        }
        self.platform_config = {
            "binance": {
                "api_base_url": settings.BINANCE_API_BASE,
                "time_api": "/fapi/v1/time",
                "market_api": "/fapi/v1/ticker/price",
                "ws_url": f"{settings.BINANCE_WS_URL}/xauusdt@ticker",
                "symbol": "XAUUSDT",
                "redis_key": "market:binance:XAUUSDT",
                "time_redis_key": "market:binance:server_time"
            },
            "bybit_mt5": {
                "api_base_url": settings.BYBIT_API_BASE,
                "market_api": "/v5/market/ticker",
                "ws_url": settings.BYBIT_MT5_WS_URL,
                "symbol": "XAUUSD.s",
                "redis_key": "market:bybit_mt5:XAUUSD.s",
                "subscribe_msg": {
                    "op": "subscribe",
                    "args": ["tickers.XAUUSD.s"]
                }
            }
        }

    async def start(self):
        self.is_running = True
        self.tasks.append(asyncio.create_task(self._binance_market_service()))
        self.tasks.append(asyncio.create_task(self._bybit_mt5_market_service()))
        self.tasks.append(asyncio.create_task(self._calculate_spread()))
        logger.info("行情服务已启动（适配MT5 API与Binance时间校准，已加载MT5账户凭证）")

    async def stop(self):
        self.is_running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("行情服务已停止")

    async def _binance_time_calibration(self):
        config = self.platform_config["binance"]
        while self.is_running:
            try:
                response = requests.get(f"{config['api_base_url']}{config['time_api']}")
                response.raise_for_status()
                time_data = response.json()
                server_time = time_data["serverTime"]
                self.redis_client.set(config["time_redis_key"], server_time)
                self.redis_client.expire(config["time_redis_key"], 10)
                logger.debug(f"Binance时间校准完成，服务器时间：{server_time}")
            except Exception as e:
                logger.error(f"Binance时间校准异常: {e}")
            await asyncio.sleep(5)

    async def _subscribe_binance_market(self):
        config = self.platform_config["binance"]
        while self.is_running:
            try:
                async with websockets.connect(config["ws_url"]) as websocket:
                    while self.is_running:
                        response = await websocket.recv()
                        data = json.loads(response)
                        ticker_data = {
                            "bid": data["b"],
                            "ask": data["a"],
                            "last_price": data["c"],
                            "timestamp": data["E"],
                            "server_time": self.redis_client.get(config["time_redis_key"]) or data["E"],
                            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        self.redis_client.hset(config["redis_key"], mapping=ticker_data)
                        self.redis_client.expire(config["redis_key"], 5)
            except Exception as e:
                logger.error(f"Binance行情订阅异常: {e}")
                await asyncio.sleep(3)

    async def _binance_market_service(self):
        await asyncio.gather(
            self._binance_time_calibration(),
            self._subscribe_binance_market()
        )

    async def _bybit_mt5_market_service(self):
        config = self.platform_config["bybit_mt5"]
        while self.is_running:
            try:
                headers = {
                    "X-MT5-Account-Id": self.bybit_mt5_credentials["account_id"],
                    "X-MT5-Password": self.bybit_mt5_credentials["password"],
                    "X-MT5-Server": self.bybit_mt5_credentials["server"]
                }
                params = {"symbol": config["symbol"]}
                response = requests.get(
                    f"{config['api_base_url']}{config['market_api']}",
                    params=params,
                    headers=headers
                )
                response.raise_for_status()
                init_data = response.json()
                if init_data["retCode"] == 0 and len(init_data["result"]["list"]) > 0:
                    init_ticker = init_data["result"]["list"][0]
                    init_ticker_data = {
                        "bid": init_ticker["bid1Price"],
                        "ask": init_ticker["ask1Price"],
                        "last_price": init_ticker["lastPrice"],
                        "timestamp": init_ticker["ts"],
                        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "mt5_server": self.bybit_mt5_credentials["server"],
                        "mt5_account_id": self.bybit_mt5_credentials["account_id"]
                    }
                    self.redis_client.hset(config["redis_key"], mapping=init_ticker_data)
                    self.redis_client.expire(config["redis_key"], 5)

                async with websockets.connect(config["ws_url"]) as websocket:
                    subscribe_msg = config["subscribe_msg"].copy()
                    subscribe_msg["params"] = {
                        "accountId": self.bybit_mt5_credentials["account_id"],
                        "server": self.bybit_mt5_credentials["server"]
                    }
                    await websocket.send(json.dumps(subscribe_msg))

                    while self.is_running:
                        response = await websocket.recv()
                        data = json.loads(response)

                        if "data" in data and len(data["data"]) > 0:
                            ticker = data["data"][0]
                            ticker_data = {
                                "bid": ticker["bid1Price"],
                                "ask": ticker["ask1Price"],
                                "last_price": ticker["lastPrice"],
                                "timestamp": ticker["ts"],
                                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "mt5_server": self.bybit_mt5_credentials["server"],
                                "mt5_account_id": self.bybit_mt5_credentials["account_id"]
                            }
                            self.redis_client.hset(config["redis_key"], mapping=ticker_data)
                            self.redis_client.expire(config["redis_key"], 5)
                            self._update_mt5_stuck_counter()

            except Exception as e:
                logger.error(f"Bybit TRADFI MT5行情订阅异常: {e}")
                await asyncio.sleep(3)

    def _update_mt5_stuck_counter(self):
        counter_key = "market:bybit_mt5:stuck_counter"
        self.redis_client.set(counter_key, 0)
        self.redis_client.expire(counter_key, 10)

    async def _calculate_spread(self):
        spread_key = "market:spread:XAU"
        binance_key = self.platform_config["binance"]["redis_key"]
        bybit_mt5_key = self.platform_config["bybit_mt5"]["redis_key"]

        while self.is_running:
            try:
                binance_data = self.redis_client.hgetall(binance_key)
                bybit_mt5_data = self.redis_client.hgetall(bybit_mt5_key)

                if binance_data and bybit_mt5_data:
                    forward_spread = float(bybit_mt5_data["ask"]) - float(binance_data["bid"])
                    reverse_spread = float(binance_data["ask"]) - float(bybit_mt5_data["bid"])

                    spread_data = {
                        "forward_spread": f"{forward_spread:.4f}",
                        "reverse_spread": f"{reverse_spread:.4f}",
                        "binance_price": binance_data["last_price"],
                        "bybit_mt5_price": bybit_mt5_data["last_price"],
                        "mt5_account_id": bybit_mt5_data.get("mt5_account_id"),
                        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    self.redis_client.hset(spread_key, mapping=spread_data)
                    self.redis_client.expire(spread_key, 5)
                    logger.debug(f"点差计算完成：正向{forward_spread:.4f}，反向{reverse_spread:.4f}")
            except Exception as e:
                logger.error(f"点差计算异常: {e}")
            await asyncio.sleep(0.5)
