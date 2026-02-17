import asyncio
import logging
from datetime import datetime, timedelta
from ..core.redis import get_redis
from ..core.database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RiskControlService:
    def __init__(self):
        self.redis_client = get_redis()
        self.db = SessionLocal()
        self.is_running = False
        self.tasks = []

    async def start(self):
        self.is_running = True
        self.tasks.append(asyncio.create_task(self._monitor_mt5_stuck()))
        self.tasks.append(asyncio.create_task(self._monitor_account_risk()))
        self.tasks.append(asyncio.create_task(self._monitor_order_execution()))
        self.tasks.append(asyncio.create_task(self._clean_expired_alerts()))
        logger.info("风控服务已启动")

    async def stop(self):
        self.is_running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.db.close()
        logger.info("风控服务已停止")

    async def _monitor_mt5_stuck(self):
        while self.is_running:
            try:
                counter_key = "market:bybit_mt5:stuck_counter"
                stuck_count = int(self.redis_client.get(counter_key) or 0)
                
                if stuck_count > 0:
                    new_count = stuck_count + 1
                    self.redis_client.set(counter_key, new_count)
                    self.redis_client.expire(counter_key, 10)
                    
                    from ..models import StrategyConfig
                    configs = self.db.query(StrategyConfig).filter(StrategyConfig.is_enabled == True).all()
                    
                    for config in configs:
                        if new_count > config.mt5_stuck_threshold:
                            await self._handle_mt5_stuck(config)
            except Exception as e:
                logger.error(f"监控MT5卡顿异常: {e}")
            await asyncio.sleep(1)

    async def _handle_mt5_stuck(self, config):
        logger.warning(f"MT5行情卡顿，超过阈值: {config.mt5_stuck_threshold}")
        await self._create_risk_alert(
            user_id=config.user_id,
            level="warning",
            message=f"MT5行情卡顿，已停止下单并撤单"
        )
        
        try:
            # 1. 标记策略为暂停状态
            config.is_enabled = False
            self.db.commit()
            
            # 2. 撤单逻辑
            from ..models import OrderRecord
            open_orders = self.db.query(OrderRecord).filter(
                OrderRecord.status.in_(["new", "pending"])
            ).all()
            
            for order in open_orders:
                await self._cancel_order(order)
            
            logger.info("MT5卡顿处理完成：已暂停策略并撤单")
        except Exception as e:
            logger.error(f"处理MT5卡顿异常: {e}")
            self.db.rollback()
    
    async def _cancel_order(self, order):
        try:
            from ..models import Account
            account = self.db.query(Account).filter(
                Account.account_id == order.account_id
            ).first()
            
            if not account:
                return
            
            if account.platform.platform_name == "Binance":
                await self._cancel_binance_order(account, order)
            elif account.platform.platform_name == "Bybit":
                await self._cancel_bybit_order(account, order)
        except Exception as e:
            logger.error(f"撤单异常: {e}")
    
    async def _cancel_binance_order(self, account, order):
        try:
            import requests
            import time
            import hmac
            import hashlib
            
            timestamp = int(time.time() * 1000)
            params = {
                "symbol": order.symbol,
                "orderId": order.platform_order_id,
                "timestamp": timestamp,
                "recvWindow": 5000
            }
            signature = hmac.new(
                account.api_secret.encode('utf-8'),
                f"orderId={order.platform_order_id}&recvWindow=5000&symbol={order.symbol}&timestamp={timestamp}".encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params["signature"] = signature
            
            response = requests.delete(
                f"{account.platform.api_base_url}/fapi/v1/order",
                params=params,
                headers={"X-MBX-APIKEY": account.api_key}
            )
            response.raise_for_status()
            
            order.status = "canceled"
            self.db.commit()
        except Exception as e:
            logger.error(f"取消Binance订单异常: {e}")
    
    async def _cancel_bybit_order(self, account, order):
        try:
            import requests
            import time
            import hmac
            import hashlib
            import json
            
            timestamp = int(time.time() * 1000)
            params = {
                "api_key": account.api_key,
                "timestamp": timestamp,
                "symbol": order.symbol,
                "orderId": order.platform_order_id
            }
            if account.passphrase:
                params["passphrase"] = account.passphrase
            
            params_string = json.dumps(params, separators=(',', ':'))
            signature = hmac.new(
                account.api_secret.encode('utf-8'),
                params_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params["sign"] = signature
            
            response = requests.post(
                f"{account.platform.api_base_url}/v5/order/cancel",
                json=params,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            order.status = "canceled"
            self.db.commit()
        except Exception as e:
            logger.error(f"取消Bybit订单异常: {e}")

    async def _monitor_account_risk(self):
        while self.is_running:
            try:
                from ..models import Account
                accounts = self.db.query(Account).filter(Account.is_active == True).all()
                
                for account in accounts:
                    await self._check_account_risk(account)
            except Exception as e:
                logger.error(f"监控账户风险异常: {e}")
            await asyncio.sleep(5)

    async def _check_account_risk(self, account):
        try:
            if account.platform.platform_name == "Binance":
                await self._check_binance_account_risk(account)
            elif account.platform.platform_name == "Bybit":
                await self._check_bybit_account_risk(account)
        except Exception as e:
            logger.error(f"检查账户风险异常: {e}")

    async def _check_binance_account_risk(self, account):
        try:
            import requests
            import time
            import hmac
            import hashlib
            
            timestamp = int(time.time() * 1000)
            params = {"timestamp": timestamp, "recvWindow": 5000}
            signature = hmac.new(
                account.api_secret.encode('utf-8'),
                f"timestamp={timestamp}&recvWindow=5000".encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params["signature"] = signature
            
            response = requests.get(
                f"{account.platform.api_base_url}/fapi/v2/account",
                params=params,
                headers={"X-MBX-APIKEY": account.api_key}
            )
            response.raise_for_status()
            account_data = response.json()
            
            # 检查风险率
            if "totalMarginBalance" in account_data and "totalMaintMargin" in account_data:
                total_margin = float(account_data["totalMarginBalance"])
                total_maint_margin = float(account_data["totalMaintMargin"])
                if total_margin > 0:
                    risk_ratio = total_maint_margin / total_margin
                    if risk_ratio > 0.9:
                        await self._create_risk_alert(
                            user_id=account.user_id,
                            level="danger",
                            message=f"Binance账户风险率过高: {risk_ratio:.2f}"
                        )
        except Exception as e:
            logger.error(f"检查Binance账户风险异常: {e}")

    async def _check_bybit_account_risk(self, account):
        try:
            import requests
            import time
            import hmac
            import hashlib
            import json
            
            timestamp = int(time.time() * 1000)
            params = {
                "api_key": account.api_key,
                "timestamp": timestamp
            }
            if account.passphrase:
                params["passphrase"] = account.passphrase
            
            params_string = json.dumps(params, separators=(',', ':'))
            signature = hmac.new(
                account.api_secret.encode('utf-8'),
                params_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params["sign"] = signature
            
            response = requests.get(
                f"{account.platform.api_base_url}/v5/account/account-info",
                params=params
            )
            response.raise_for_status()
            account_data = response.json()
            
            if account_data.get("retCode") == 0:
                risk_ratio = float(account_data["result"].get("riskRatio", 0))
                if risk_ratio > 0.9:
                    await self._create_risk_alert(
                        user_id=account.user_id,
                        level="danger",
                        message=f"Bybit账户风险率过高: {risk_ratio:.2f}"
                    )
        except Exception as e:
            logger.error(f"检查Bybit账户风险异常: {e}")

    async def _create_risk_alert(self, user_id, level, message):
        try:
            from ..models import RiskAlert
            alert = RiskAlert(
                user_id=user_id,
                alert_level=level,
                alert_message=message,
                expire_time=datetime.utcnow() + timedelta(minutes=5)
            )
            self.db.add(alert)
            self.db.commit()
        except Exception as e:
            logger.error(f"创建风控提示异常: {e}")
            self.db.rollback()

    async def _monitor_order_execution(self):
        while self.is_running:
            try:
                from ..models import OrderRecord
                # 监控长时间未成交的订单
                pending_orders = self.db.query(OrderRecord).filter(
                    OrderRecord.status.in_(["new", "pending"])
                ).all()
                
                for order in pending_orders:
                    time_diff = datetime.utcnow() - order.create_time
                    if time_diff.total_seconds() > 300:  # 5分钟未成交
                        await self._handle_order_execution_error(order)
            except Exception as e:
                logger.error(f"监控订单执行异常: {e}")
            await asyncio.sleep(10)
    
    async def _handle_order_execution_error(self, order):
        logger.warning(f"订单执行异常，长时间未成交: {order.order_id}")
        
        try:
            from ..models import Account
            account = self.db.query(Account).filter(
                Account.account_id == order.account_id
            ).first()
            
            if account:
                await self._create_risk_alert(
                    user_id=account.user_id,
                    level="warning",
                    message=f"订单 {order.order_id} 长时间未成交，已撤单"
                )
                await self._cancel_order(order)
                logger.info(f"已处理执行异常订单: {order.order_id}")
        except Exception as e:
            logger.error(f"处理订单执行异常: {e}")
    
    async def _clean_expired_alerts(self):
        while self.is_running:
            try:
                from ..models import RiskAlert
                expired_alerts = self.db.query(RiskAlert).filter(
                    RiskAlert.expire_time < datetime.utcnow()
                ).all()
                
                for alert in expired_alerts:
                    self.db.delete(alert)
                self.db.commit()
            except Exception as e:
                logger.error(f"清理过期提示异常: {e}")
                self.db.rollback()
            await asyncio.sleep(60)
