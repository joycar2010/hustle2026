import asyncio
import logging
import json
import hmac
import hashlib
import time
import requests
from datetime import datetime
from typing import Optional, Dict
import os
from dotenv import load_dotenv
from ..core.redis import get_redis
from ..models import OrderRecord, ArbitrageTask
from ..core.database import SessionLocal

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StrategyEngine:
    def __init__(self):
        self.redis_client = get_redis()
        self.db = SessionLocal()
        self.is_running = False
        self.tasks = []

    async def start(self):
        self.is_running = True
        self.tasks.append(asyncio.create_task(self._monitor_spread()))
        logger.info("策略引擎已启动")

    async def stop(self):
        self.is_running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.db.close()
        logger.info("策略引擎已停止")

    async def _monitor_spread(self):
        while self.is_running:
            try:
                spread_data = self.redis_client.hgetall("market:spread:XAU")
                if spread_data:
                    forward_spread = float(spread_data["forward_spread"])
                    reverse_spread = float(spread_data["reverse_spread"])
                    await self._check_arbitrage_opportunity(forward_spread, reverse_spread)
            except Exception as e:
                logger.error(f"监控点差异常: {e}")
            await asyncio.sleep(0.1)

    async def _check_arbitrage_opportunity(self, forward_spread: float, reverse_spread: float):
        try:
            from ..models import StrategyConfig
            configs = self.db.query(StrategyConfig).filter(StrategyConfig.is_enabled == True).all()
            
            for config in configs:
                if config.strategy_type == "forward" and forward_spread > config.target_spread:
                    await self._execute_forward_arbitrage(config, forward_spread)
                elif config.strategy_type == "reverse" and reverse_spread > config.target_spread:
                    await self._execute_reverse_arbitrage(config, reverse_spread)
        except Exception as e:
            logger.error(f"检查套利机会异常: {e}")

    async def _execute_forward_arbitrage(self, config, spread: float):
        logger.info(f"执行正向套利，点差: {spread}")
        try:
            # 1. 获取两边价格
            binance_data = self.redis_client.hgetall("market:binance:XAUUSDT")
            bybit_mt5_data = self.redis_client.hgetall("market:bybit_mt5:XAUUSD.s")
            
            if not binance_data or not bybit_mt5_data:
                logger.error("获取价格数据失败")
                return
            
            # 2. 获取活跃账户
            from ..models import Account
            binance_account = self.db.query(Account).filter(
                Account.platform_id == 1, Account.is_active == True
            ).first()
            bybit_account = self.db.query(Account).filter(
                Account.platform_id == 2, Account.is_active == True
            ).first()
            
            if not binance_account or not bybit_account:
                logger.error("缺少活跃账户")
                return
            
            # 3. 执行套利
            # 在 Binance 买入 XAUUSDT
            binance_order = await self.place_order(
                binance_account, "XAUUSDT", "buy", "market", 
                float(binance_data["ask"]), config.order_qty
            )
            
            # 在 Bybit MT5 卖出 XAUUSD.s
            bybit_order = await self.place_order(
                bybit_account, "XAUUSD.s", "sell", "market", 
                float(bybit_mt5_data["bid"]), config.order_qty
            )
            
            # 4. 记录套利任务
            if "error" not in binance_order and "error" not in bybit_order:
                task = ArbitrageTask(
                    user_id=config.user_id,
                    strategy_type="forward",
                    open_spread=spread,
                    status="open",
                    open_time=datetime.now()
                )
                self.db.add(task)
                self.db.commit()
                self.db.refresh(task)
                
                # 5. 记录订单
                self._record_order(
                    binance_account.account_id, task.task_id, "XAUUSDT", 
                    "buy", "market", float(binance_data["ask"]), 
                    config.order_qty, binance_order.get("orderId")
                )
                self._record_order(
                    bybit_account.account_id, task.task_id, "XAUUSD.s", 
                    "sell", "market", float(bybit_mt5_data["bid"]), 
                    config.order_qty, bybit_order.get("result", {}).get("orderId")
                )
                
                logger.info(f"正向套利执行成功，任务ID: {task.task_id}")
        except Exception as e:
            logger.error(f"执行正向套利异常: {e}")

    async def _execute_reverse_arbitrage(self, config, spread: float):
        logger.info(f"执行反向套利，点差: {spread}")
        try:
            # 1. 获取两边价格
            binance_data = self.redis_client.hgetall("market:binance:XAUUSDT")
            bybit_mt5_data = self.redis_client.hgetall("market:bybit_mt5:XAUUSD.s")
            
            if not binance_data or not bybit_mt5_data:
                logger.error("获取价格数据失败")
                return
            
            # 2. 获取活跃账户
            from ..models import Account
            binance_account = self.db.query(Account).filter(
                Account.platform_id == 1, Account.is_active == True
            ).first()
            bybit_account = self.db.query(Account).filter(
                Account.platform_id == 2, Account.is_active == True
            ).first()
            
            if not binance_account or not bybit_account:
                logger.error("缺少活跃账户")
                return
            
            # 3. 执行套利
            # 在 Binance 卖出 XAUUSDT
            binance_order = await self.place_order(
                binance_account, "XAUUSDT", "sell", "market", 
                float(binance_data["bid"]), config.order_qty
            )
            
            # 在 Bybit MT5 买入 XAUUSD.s
            bybit_order = await self.place_order(
                bybit_account, "XAUUSD.s", "buy", "market", 
                float(bybit_mt5_data["ask"]), config.order_qty
            )
            
            # 4. 记录套利任务
            if "error" not in binance_order and "error" not in bybit_order:
                task = ArbitrageTask(
                    user_id=config.user_id,
                    strategy_type="reverse",
                    open_spread=spread,
                    status="open",
                    open_time=datetime.now()
                )
                self.db.add(task)
                self.db.commit()
                self.db.refresh(task)
                
                # 5. 记录订单
                self._record_order(
                    binance_account.account_id, task.task_id, "XAUUSDT", 
                    "sell", "market", float(binance_data["bid"]), 
                    config.order_qty, binance_order.get("orderId")
                )
                self._record_order(
                    bybit_account.account_id, task.task_id, "XAUUSD.s", 
                    "buy", "market", float(bybit_mt5_data["ask"]), 
                    config.order_qty, bybit_order.get("result", {}).get("orderId")
                )
                
                logger.info(f"反向套利执行成功，任务ID: {task.task_id}")
        except Exception as e:
            logger.error(f"执行反向套利异常: {e}")
            
    def _record_order(self, account_id, task_id, symbol, side, order_type, price, qty, platform_order_id):
        try:
            order = OrderRecord(
                account_id=account_id,
                task_id=task_id,
                symbol=symbol,
                order_side=side,
                order_type=order_type,
                price=price,
                qty=qty,
                status="new",
                platform_order_id=platform_order_id
            )
            self.db.add(order)
            self.db.commit()
        except Exception as e:
            logger.error(f"记录订单异常: {e}")

    def _sign_binance_request(self, params: Dict, api_secret: str) -> str:
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    def _sign_bybit_request(self, params: Dict, api_secret: str) -> str:
        params_string = json.dumps(params, separators=(',', ':'))
        return hmac.new(api_secret.encode('utf-8'), params_string.encode('utf-8'), hashlib.sha256).hexdigest()

    async def place_order(self, account, symbol: str, side: str, order_type: str, price: float, qty: float) -> Dict:
        if account.platform.platform_name == "Binance":
            return await self._place_binance_order(account, symbol, side, order_type, price, qty)
        elif account.platform.platform_name == "Bybit":
            return await self._place_bybit_order(account, symbol, side, order_type, price, qty)
        return {"error": "不支持的平台"}

    async def _place_binance_order(self, account, symbol: str, side: str, order_type: str, price: float, qty: float) -> Dict:
        try:
            timestamp = int(time.time() * 1000)
            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": order_type.upper(),
                "price": f"{price:.2f}",
                "quantity": f"{qty:.6f}",
                "timestamp": timestamp,
                "recvWindow": 5000
            }
            signature = self._sign_binance_request(params, account.api_secret)
            params["signature"] = signature
            
            response = requests.post(
                f"{account.platform.api_base_url}/fapi/v1/order",
                params=params,
                headers={"X-MBX-APIKEY": account.api_key}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Binance下单异常: {e}")
            return {"error": str(e)}

    async def _place_bybit_order(self, account, symbol: str, side: str, order_type: str, price: float, qty: float) -> Dict:
        try:
            timestamp = int(time.time() * 1000)
            params = {
                "api_key": account.api_key,
                "timestamp": timestamp,
                "symbol": symbol,
                "side": side.upper(),
                "orderType": order_type.upper(),
                "qty": f"{qty:.6f}",
                "price": f"{price:.2f}",
                "timeInForce": "GTC"
            }
            if account.passphrase:
                params["passphrase"] = account.passphrase
            signature = self._sign_bybit_request(params, account.api_secret)
            params["sign"] = signature
            
            response = requests.post(
                f"{account.platform.api_base_url}/v5/order/create",
                json=params,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Bybit下单异常: {e}")
            return {"error": str(e)}
