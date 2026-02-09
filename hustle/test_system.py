import unittest
import asyncio
import json
from unittest.mock import Mock, patch, MagicMock

# 先 mock 导入，避免 pybit 兼容性问题
with patch('arbitrage_system.HTTP', Mock()):
    from arbitrage_system import (
        RiskManager, 
        ConfigManager,
        PerformanceMonitor
    )

class TestRiskManager(unittest.TestCase):
    """测试RiskManager类"""
    
    def setUp(self):
        self.config = {
            'risk_manager': {
                'max_api_failures': 5,
                'max_order_failures': 3
            }
        }
        self.risk_manager = RiskManager(self.config)
    
    def test_is_bybit_trading_hours(self):
        """测试Bybit交易时间检查"""
        # 这个测试可能需要mock datetime来测试不同的时间
        result = self.risk_manager.is_bybit_trading_hours()
        self.assertIsInstance(result, bool)
    
    def test_should_close_weekend_positions(self):
        """测试是否需要关闭周末头寸"""
        # 这个测试可能需要mock datetime来测试不同的时间
        result = self.risk_manager.should_close_weekend_positions()
        self.assertIsInstance(result, bool)
    
    def test_validate_slippage(self):
        """测试滑点验证"""
        # 测试正常情况
        self.assertTrue(self.risk_manager.validate_slippage(100, 100.1))
        # 测试滑点过大
        self.assertFalse(self.risk_manager.validate_slippage(100, 101))
    
    def test_emergency_stop(self):
        """测试紧急停止功能"""
        self.assertFalse(self.risk_manager.is_emergency_stop_active())
        self.risk_manager.trigger_emergency_stop('测试紧急停止')
        self.assertTrue(self.risk_manager.is_emergency_stop_active())
        self.risk_manager.reset_emergency_stop()
        self.assertFalse(self.risk_manager.is_emergency_stop_active())
    
    def test_circuit_breakers(self):
        """测试熔断机制"""
        self.assertFalse(self.risk_manager.is_circuit_broken())
        
        # 测试API失败触发熔断
        for _ in range(6):  # 超过最大失败次数
            self.risk_manager.record_api_failure()
        self.assertTrue(self.risk_manager.is_circuit_broken())
        
        # 重置熔断
        self.risk_manager.reset_failures()
        self.assertFalse(self.risk_manager.is_circuit_broken())

class TestConfigManager(unittest.TestCase):
    """测试ConfigManager类"""
    
    def setUp(self):
        self.config_manager = ConfigManager()
    
    def test_get_default_config(self):
        """测试获取默认配置"""
        min_spread = self.config_manager.get('min_spread')
        self.assertEqual(min_spread, 3.0)
    
    def test_set_config(self):
        """测试设置配置"""
        self.config_manager.set('min_spread', 4.0)
        self.assertEqual(self.config_manager.get('min_spread'), 4.0)
    
    def test_nested_config(self):
        """测试嵌套配置"""
        self.config_manager.set('risk_manager.max_api_failures', 10)
        self.assertEqual(self.config_manager.get('risk_manager.max_api_failures'), 10)

class TestPerformanceMonitor(unittest.TestCase):
    """测试PerformanceMonitor类"""
    
    def setUp(self):
        self.monitor = PerformanceMonitor()
    
    def test_record_api_response(self):
        """测试记录API响应时间"""
        self.monitor.record_api_response('test_endpoint', 0.1)
        report = self.monitor.get_performance_report()
        self.assertIn('test_endpoint', report['api_performance'])
    
    def test_record_order_execution(self):
        """测试记录订单执行时间"""
        self.monitor.record_order_execution('binance', 0.2)
        report = self.monitor.get_performance_report()
        self.assertIn('binance', report['order_performance'])
    
    def test_get_performance_report(self):
        """测试生成性能报告"""
        report = self.monitor.get_performance_report()
        self.assertIn('timestamp', report)
        self.assertIn('api_performance', report)
        self.assertIn('order_performance', report)
        self.assertIn('system_metrics', report)

class TestStrategy(unittest.TestCase):
    """测试Strategy类"""
    
    def setUp(self):
        # 创建mock对象
        self.mock_exchange = Mock()
        self.mock_risk_manager = Mock()
        self.config = {
            'min_spread': 3.0,
            'exit_spread': 0.5,
            'trade_size_xau': 1.0
        }
        self.strategy = Strategy(self.mock_exchange, self.mock_risk_manager, self.config)
    
    async def test_calculate_spread(self):
        """测试点差计算"""
        # Mock exchange方法
        self.mock_exchange.get_binance_price.return_value = asyncio.Future()
        self.mock_exchange.get_binance_price.return_value.set_result({
            'bid': 1000,
            'ask': 1001,
            'last': 1000.5
        })
        
        self.mock_exchange.get_bybit_price.return_value = asyncio.Future()
        self.mock_exchange.get_bybit_price.return_value.set_result({
            'bid': 1003,
            'ask': 1004,
            'last': 1003.5
        })
        
        self.mock_exchange.assess_liquidity.return_value = asyncio.Future()
        self.mock_exchange.assess_liquidity.return_value.set_result({
            'estimated_slippage': 0.1
        })
        
        result = await self.strategy.calculate_spread()
        self.assertIsNotNone(result)
        self.assertIn('spread', result)

# 注意：由于Python 3.8兼容性问题，暂时跳过对ExchangeConnector、Strategy和ArbitrageSystem的测试
# 这些组件依赖于pybit库，而pybit库的最新版本不兼容Python 3.8

# 以下是简化的测试，只测试不依赖外部API的组件

if __name__ == '__main__':
    unittest.main()
