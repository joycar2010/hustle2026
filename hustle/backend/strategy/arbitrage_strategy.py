from datetime import datetime
import asyncio
import json
from typing import Dict, List, Optional, Tuple

class ArbitrageStrategy:
    """黄金套利策略核心类"""
    
    def __init__(self, exchange_connector, redis_client):
        self.exchange_connector = exchange_connector
        self.redis_client = redis_client
        self.config = {
            "min_spread": 3.0,  # 最小点差阈值
            "exit_spread": 0.5,  # 退出点差阈值
            "trade_size": 1.0,  # 交易大小（XAU）
            "check_interval": 5,  # 检查间隔（秒）
            "max_position": 5.0,  # 最大持仓
            "leverage": 10,  # 杠杆
            "max_loss": 1000,  # 最大亏损限制
            "stop_loss": 0.5,  # 止损比例
            "take_profit": 0.3,  # 止盈比例
        }
        self.positions = []  # 持仓记录
        self.total_pnl = 0  # 总盈亏
        self.last_check_time = datetime.now()
    
    def load_config(self):
        """从Redis加载配置"""
        try:
            config_str = self.redis_client.get("strategy_config")
            if config_str:
                self.config.update(json.loads(config_str))
                print("策略配置加载成功")
        except Exception as e:
            print(f"加载策略配置失败: {e}")
    
    async def check_opportunity(self):
        """检查套利机会"""
        try:
            # 加载最新配置
            self.load_config()
            
            # 获取实时价格
            binance_price = await self.exchange_connector.get_price("binance", "XAUUSDT")
            bybit_price = await self.exchange_connector.get_price("bybit", "XAUUSD")
            
            if not binance_price or not bybit_price:
                print("获取价格失败，跳过套利检查")
                return None
            
            # 计算点差
            binance_last = binance_price["last"]
            bybit_last = bybit_price["last"]
            spread = abs(binance_last - bybit_last)
            
            print(f"当前点差: {spread:.2f}, 最小点差阈值: {self.config['min_spread']}")
            
            # 检查是否有套利机会
            if spread >= self.config["min_spread"]:
                # 确定套利方向
                if binance_last > bybit_last:
                    # 币安价格 > Bybit价格，在币安做空，Bybit做多
                    opportunity = {
                        "type": "arbitrage",
                        "direction": "binance_short_bybit_long",
                        "binance_price": binance_last,
                        "bybit_price": bybit_last,
                        "spread": spread,
                        "potential_profit": spread * self.config["trade_size"] * self.config["leverage"],
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    # Bybit价格 > 币安价格，在Bybit做空，币安做多
                    opportunity = {
                        "type": "arbitrage",
                        "direction": "bybit_short_binance_long",
                        "binance_price": binance_last,
                        "bybit_price": bybit_last,
                        "spread": spread,
                        "potential_profit": spread * self.config["trade_size"] * self.config["leverage"],
                        "timestamp": datetime.now().isoformat()
                    }
                
                return opportunity
            
            # 检查是否需要平仓
            if spread <= self.config["exit_spread"] and self.positions:
                return {
                    "type": "exit",
                    "reason": "spread_too_small",
                    "spread": spread,
                    "timestamp": datetime.now().isoformat()
                }
            
        except Exception as e:
            print(f"检查套利机会失败: {e}")
        
        return None
    
    async def execute_arbitrage(self, opportunity):
        """执行套利操作"""
        try:
            if opportunity["type"] != "arbitrage":
                return False
            
            direction = opportunity["direction"]
            trade_size = self.config["trade_size"]
            
            print(f"执行套利操作: {direction}, 交易大小: {trade_size}")
            
            # 这里应该调用交易所API执行实际交易
            # 由于是演示，我们只记录持仓
            position = {
                "id": len(self.positions) + 1,
                "direction": direction,
                "size": trade_size,
                "entry_price_binance": opportunity["binance_price"],
                "entry_price_bybit": opportunity["bybit_price"],
                "entry_time": datetime.now().isoformat(),
                "status": "open",
                "pnl": 0
            }
            
            self.positions.append(position)
            
            # 记录到Redis
            self.redis_client.set("positions", json.dumps(self.positions))
            
            return True
            
        except Exception as e:
            print(f"执行套利操作失败: {e}")
            return False
    
    async def close_positions(self, reason="normal"):
        """平仓所有持仓"""
        try:
            for position in self.positions:
                if position["status"] == "open":
                    # 获取当前价格
                    binance_price = await self.exchange_connector.get_price("binance", "XAUUSDT")
                    bybit_price = await self.exchange_connector.get_price("bybit", "XAUUSD")
                    
                    if binance_price and bybit_price:
                        # 计算盈亏
                        if position["direction"] == "binance_short_bybit_long":
                            # 币安做空，Bybit做多
                            binance_pnl = (position["entry_price_binance"] - binance_price["last"]) * position["size"]
                            bybit_pnl = (bybit_price["last"] - position["entry_price_bybit"]) * position["size"]
                        else:
                            # Bybit做空，币安做多
                            binance_pnl = (binance_price["last"] - position["entry_price_binance"]) * position["size"]
                            bybit_pnl = (position["entry_price_bybit"] - bybit_price["last"]) * position["size"]
                        
                        total_pnl = binance_pnl + bybit_pnl
                        position["pnl"] = total_pnl
                        position["exit_price_binance"] = binance_price["last"]
                        position["exit_price_bybit"] = bybit_price["last"]
                        position["exit_time"] = datetime.now().isoformat()
                        position["status"] = "closed"
                        position["exit_reason"] = reason
                        
                        self.total_pnl += total_pnl
                        print(f"平仓持仓 {position['id']}, 盈亏: {total_pnl:.2f}")
            
            # 更新Redis
            self.redis_client.set("positions", json.dumps(self.positions))
            self.redis_client.set("total_pnl", str(self.total_pnl))
            
            return True
            
        except Exception as e:
            print(f"平仓操作失败: {e}")
            return False
    
    def get_status(self):
        """获取策略状态"""
        return {
            "config": self.config,
            "positions_count": len([p for p in self.positions if p["status"] == "open"]),
            "total_positions": len(self.positions),
            "total_pnl": self.total_pnl,
            "last_check_time": self.last_check_time.isoformat(),
            "open_positions": [p for p in self.positions if p["status"] == "open"]
        }

class SmartOrderRouter:
    """智能订单路由"""
    
    def __init__(self, exchange_connector):
        self.exchange_connector = exchange_connector
        self.exchanges = ["binance", "bybit"]
    
    async def find_best_price(self, symbol, side, amount):
        """寻找最优价格"""
        try:
            prices = {}
            
            # 获取各交易所价格
            for exchange in self.exchanges:
                if exchange == "binance":
                    price = await self.exchange_connector.get_price(exchange, "XAUUSDT")
                else:
                    price = await self.exchange_connector.get_price(exchange, "XAUUSD")
                
                if price:
                    if side == "buy":
                        # 买入看ask价格
                        prices[exchange] = price["ask"] if price["ask"] else price["last"]
                    else:
                        # 卖出看bid价格
                        prices[exchange] = price["bid"] if price["bid"] else price["last"]
            
            if not prices:
                return None
            
            # 选择最优价格
            if side == "buy":
                # 买入选择最低价格
                best_exchange = min(prices, key=prices.get)
            else:
                # 卖出选择最高价格
                best_exchange = max(prices, key=prices.get)
            
            return {
                "exchange": best_exchange,
                "price": prices[best_exchange],
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"寻找最优价格失败: {e}")
            return None
    
    async def split_order(self, symbol, side, amount):
        """拆分订单"""
        try:
            # 根据流动性拆分订单
            split_orders = []
            remaining_amount = amount
            
            # 简单的等分策略
            for exchange in self.exchanges:
                order_amount = remaining_amount / len(self.exchanges)
                best_price = await self.find_best_price(symbol, side, order_amount)
                if best_price:
                    split_orders.append({
                        "exchange": exchange,
                        "amount": order_amount,
                        "price": best_price["price"]
                    })
                    remaining_amount -= order_amount
            
            return split_orders
            
        except Exception as e:
            print(f"拆分订单失败: {e}")
            return []

class RiskManager:
    """风险管理器"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.max_loss = 1000
        self.max_position = 5.0
        self.leverage_limit = 10
        self.risk_level = "medium"  # low, medium, high
    
    def check_risk(self, strategy):
        """检查风险"""
        try:
            # 检查总盈亏
            if strategy.total_pnl <= -self.max_loss:
                return {
                    "risk": "high",
                    "reason": "total_loss_exceeded",
                    "action": "stop_trading"
                }
            
            # 检查持仓大小
            open_positions = [p for p in strategy.positions if p["status"] == "open"]
            total_position = sum(p["size"] for p in open_positions)
            
            if total_position >= self.max_position:
                return {
                    "risk": "medium",
                    "reason": "max_position_exceeded",
                    "action": "reduce_position"
                }
            
            # 检查杠杆
            if strategy.config["leverage"] > self.leverage_limit:
                return {
                    "risk": "medium",
                    "reason": "leverage_exceeded",
                    "action": "reduce_leverage"
                }
            
            return {
                "risk": "low",
                "reason": "safe",
                "action": "continue"
            }
            
        except Exception as e:
            print(f"风险检查失败: {e}")
            return {
                "risk": "high",
                "reason": "risk_check_failed",
                "action": "stop_trading"
            }
    
    def calculate_margin(self, size, price, leverage):
        """计算保证金需求"""
        try:
            margin = (size * price) / leverage
            return margin
        except Exception as e:
            print(f"计算保证金失败: {e}")
            return 0