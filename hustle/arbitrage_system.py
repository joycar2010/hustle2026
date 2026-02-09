import time
import logging
import pytz
import asyncio
import json
from datetime import datetime, timedelta
from functools import wraps
import statistics

# 导入VeighNa连接器
from vnpy_connector import VNPYExchangeConnector

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('arbitrage.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """系统性能监控"""
    def __init__(self):
        self.metrics = {
            'api_responses': {},  # API响应时间
            'order_execution': {},  # 订单执行时间
            'spread_calculation': [],  # 点差计算时间
            'liquidity_assessment': [],  # 流动性评估时间
            'system_throughput': [],  # 系统吞吐量（每秒处理的请求数）
            'error_rates': {'total': 0, 'api': 0, 'order': 0},  # 错误率
            'success_rates': {'api': 0, 'order': 0},  # 成功率
            'last_reset_time': datetime.now(pytz.UTC)
        }
        self.request_count = 0  # 请求计数
        self.last_request_time = datetime.now(pytz.UTC)  # 上次请求时间
    
    def record_api_response(self, endpoint, response_time):
        """记录API响应时间"""
        if endpoint not in self.metrics['api_responses']:
            self.metrics['api_responses'][endpoint] = []
        self.metrics['api_responses'][endpoint].append(response_time)
        
        # 限制每个端点的记录数量
        if len(self.metrics['api_responses'][endpoint]) > 100:
            self.metrics['api_responses'][endpoint] = self.metrics['api_responses'][endpoint][-100:]
    
    def record_order_execution(self, exchange, order_time):
        """记录订单执行时间"""
        if exchange not in self.metrics['order_execution']:
            self.metrics['order_execution'][exchange] = []
        self.metrics['order_execution'][exchange].append(order_time)
        
        # 限制每个交易所的记录数量
        if len(self.metrics['order_execution'][exchange]) > 100:
            self.metrics['order_execution'][exchange] = self.metrics['order_execution'][exchange][-100:]
    
    def record_spread_calculation(self, calculation_time):
        """记录点差计算时间"""
        self.metrics['spread_calculation'].append(calculation_time)
        if len(self.metrics['spread_calculation']) > 100:
            self.metrics['spread_calculation'] = self.metrics['spread_calculation'][-100:]
    
    def record_liquidity_assessment(self, assessment_time):
        """记录流动性评估时间"""
        self.metrics['liquidity_assessment'].append(assessment_time)
        if len(self.metrics['liquidity_assessment']) > 100:
            self.metrics['liquidity_assessment'] = self.metrics['liquidity_assessment'][-100:]
    
    def record_request(self):
        """记录请求，用于计算系统吞吐量"""
        self.request_count += 1
        now = datetime.now(pytz.UTC)
        time_diff = (now - self.last_request_time).total_seconds()
        
        if time_diff > 0:
            throughput = 1 / time_diff
            self.metrics['system_throughput'].append(throughput)
            if len(self.metrics['system_throughput']) > 100:
                self.metrics['system_throughput'] = self.metrics['system_throughput'][-100:]
        
        self.last_request_time = now
    
    def record_error(self, error_type):
        """记录错误"""
        self.metrics['error_rates']['total'] += 1
        if error_type in self.metrics['error_rates']:
            self.metrics['error_rates'][error_type] += 1
    
    def record_success(self, operation_type):
        """记录成功操作"""
        if operation_type in self.metrics['success_rates']:
            self.metrics['success_rates'][operation_type] += 1
    
    def get_performance_report(self):
        """生成性能报告"""
        report = {
            'timestamp': datetime.now(pytz.UTC).isoformat(),
            'api_performance': {},
            'order_performance': {},
            'system_metrics': {}
        }
        
        # API性能
        for endpoint, times in self.metrics['api_responses'].items():
            if times:
                report['api_performance'][endpoint] = {
                    'avg': statistics.mean(times) if times else 0,
                    'min': min(times) if times else 0,
                    'max': max(times) if times else 0,
                    'count': len(times)
                }
        
        # 订单执行性能
        for exchange, times in self.metrics['order_execution'].items():
            if times:
                report['order_performance'][exchange] = {
                    'avg': statistics.mean(times) if times else 0,
                    'min': min(times) if times else 0,
                    'max': max(times) if times else 0,
                    'count': len(times)
                }
        
        # 系统指标
        report['system_metrics'] = {
            'spread_calculation_avg': statistics.mean(self.metrics['spread_calculation']) if self.metrics['spread_calculation'] else 0,
            'liquidity_assessment_avg': statistics.mean(self.metrics['liquidity_assessment']) if self.metrics['liquidity_assessment'] else 0,
            'system_throughput_avg': statistics.mean(self.metrics['system_throughput']) if self.metrics['system_throughput'] else 0,
            'error_rate': self.metrics['error_rates']['total'] / (self.request_count + 1) * 100,
            'request_count': self.request_count
        }
        
        return report
    
    def log_performance_report(self):
        """记录性能报告到日志"""
        report = self.get_performance_report()
        logger.info('系统性能报告:')
        logger.info(f'时间戳: {report["timestamp"]}')
        logger.info('API性能:')
        for endpoint, metrics in report['api_performance'].items():
            logger.info(f'  {endpoint}: 平均={metrics["avg"]:.4f}s, 最小={metrics["min"]:.4f}s, 最大={metrics["max"]:.4f}s, 计数={metrics["count"]}')
        logger.info('订单执行性能:')
        for exchange, metrics in report['order_performance'].items():
            logger.info(f'  {exchange}: 平均={metrics["avg"]:.4f}s, 最小={metrics["min"]:.4f}s, 最大={metrics["max"]:.4f}s, 计数={metrics["count"]}')
        logger.info('系统指标:')
        logger.info(f'  点差计算平均时间: {report["system_metrics"]["spread_calculation_avg"]:.4f}s')
        logger.info(f'  流动性评估平均时间: {report["system_metrics"]["liquidity_assessment_avg"]:.4f}s')
        logger.info(f'  系统平均吞吐量: {report["system_metrics"]["system_throughput_avg"]:.2f} req/s')
        logger.info(f'  错误率: {report["system_metrics"]["error_rate"]:.2f}%')
        logger.info(f'  请求计数: {report["system_metrics"]["request_count"]}')
    
    def reset_metrics(self):
        """重置性能指标"""
        self.metrics = {
            'api_responses': {},
            'order_execution': {},
            'spread_calculation': [],
            'liquidity_assessment': [],
            'system_throughput': [],
            'error_rates': {'total': 0, 'api': 0, 'order': 0},
            'success_rates': {'api': 0, 'order': 0},
            'last_reset_time': datetime.now(pytz.UTC)
        }
        self.request_count = 0
        self.last_request_time = datetime.now(pytz.UTC)


performance_monitor = PerformanceMonitor()

class ConfigManager:
    """配置管理器"""
    def __init__(self, config_file=None):
        self.config_file = config_file
        self.config = {}
        self.last_updated = datetime.now(pytz.UTC)
        
        # 加载默认配置
        self._load_default_config()
        
        # 如果指定了配置文件，从文件加载配置
        if config_file:
            self.load_from_file(config_file)
    
    def _load_default_config(self):
        """加载默认配置"""
        self.config = {
            'binance': {
                'api_key': 'YOUR_BINANCE_KEY',
                'api_secret': 'YOUR_BINANCE_SECRET'
            },
            'bybit': {
                'server': 'Bybit-Live-2',
                'username': '5229471',
                'password': 'Lk106504!'
            },
            'min_spread': 3.0,
            'exit_spread': 0.5,
            'trade_size_xau': 1.0,
            'max_slippage': 0.1,
            'binance_taker_fee': 0.0004,
            'bybit_spread_cost': 0.5,
            'interval': 5,
            'risk_manager': {
                'max_api_failures': 5,
                'max_order_failures': 3,
                'max_network_failures': 4,
                'max_rate_limit_failures': 2
            }
        }
    
    def load_from_file(self, config_file):
        """从文件加载配置"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                # 合并配置
                self._merge_config(file_config)
                logger.info(f'从文件 {config_file} 加载配置成功')
                self.last_updated = datetime.now(pytz.UTC)
        except Exception as e:
            logger.error(f'从文件加载配置失败: {e}')
    
    def _merge_config(self, new_config):
        """合并配置"""
        def merge_dict(target, source):
            for key, value in source.items():
                if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                    merge_dict(target[key], value)
                else:
                    target[key] = value
        
        merge_dict(self.config, new_config)
    
    def save_to_file(self, config_file=None):
        """保存配置到文件"""
        target_file = config_file or self.config_file
        if target_file:
            try:
                with open(target_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                logger.info(f'配置保存到文件 {target_file} 成功')
            except Exception as e:
                logger.error(f'保存配置到文件失败: {e}')
    
    def get(self, key, default=None):
        """获取配置值"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key, value):
        """设置配置值"""
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
        self.last_updated = datetime.now(pytz.UTC)
        logger.info(f'更新配置: {key} = {value}')
    
    def get_all(self):
        """获取所有配置"""
        return self.config
    
    def reload(self):
        """重新加载配置"""
        if self.config_file:
            self.load_from_file(self.config_file)
    
    def get_last_updated(self):
        """获取最后更新时间"""
        return self.last_updated


config_manager = ConfigManager()

def retry_with_backoff(max_retries=3, base_delay=1, max_delay=10, error_types=None):
    """重试装饰器，带指数退避和错误分类"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            retries = 0
            delay = base_delay
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # 检查是否是指定的错误类型
                    if error_types and not any(isinstance(e, err_type) for err_type in error_types):
                        logger.error(f'调用 {func.__name__} 遇到非重试错误: {e}')
                        raise
                    
                    retries += 1
                    if retries >= max_retries:
                        logger.error(f'调用 {func.__name__} 失败，已达到最大重试次数: {e}')
                        raise
                    
                    # 根据错误类型调整延迟
                    error_msg = str(e)
                    if any(keyword in error_msg.lower() for keyword in ['timeout', 'network', 'connection']):
                        # 网络错误，使用更长的延迟
                        current_delay = min(delay * 1.5, max_delay)
                    elif any(keyword in error_msg.lower() for keyword in ['rate limit', 'too many requests']):
                        #  rate limit错误，使用更长的延迟
                        current_delay = min(delay * 2, max_delay)
                    else:
                        # 其他错误，使用标准指数退避
                        current_delay = min(delay * 2, max_delay)
                    
                    logger.warning(f'调用 {func.__name__} 失败，{retries}/{max_retries}，{current_delay:.2f}秒后重试: {e}')
                    await asyncio.sleep(current_delay)
                    delay = current_delay
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            retries = 0
            delay = base_delay
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # 检查是否是指定的错误类型
                    if error_types and not any(isinstance(e, err_type) for err_type in error_types):
                        logger.error(f'调用 {func.__name__} 遇到非重试错误: {e}')
                        raise
                    
                    retries += 1
                    if retries >= max_retries:
                        logger.error(f'调用 {func.__name__} 失败，已达到最大重试次数: {e}')
                        raise
                    
                    # 根据错误类型调整延迟
                    error_msg = str(e)
                    if any(keyword in error_msg.lower() for keyword in ['timeout', 'network', 'connection']):
                        # 网络错误，使用更长的延迟
                        current_delay = min(delay * 1.5, max_delay)
                    elif any(keyword in error_msg.lower() for keyword in ['rate limit', 'too many requests']):
                        #  rate limit错误，使用更长的延迟
                        current_delay = min(delay * 2, max_delay)
                    else:
                        # 其他错误，使用标准指数退避
                        current_delay = min(delay * 2, max_delay)
                    
                    logger.warning(f'调用 {func.__name__} 失败，{retries}/{max_retries}，{current_delay:.2f}秒后重试: {e}')
                    time.sleep(current_delay)
                    delay = current_delay
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    return decorator

class RiskManager:
    def __init__(self, config=None):
        self.config = config or {}
        self.max_slippage = self.config.get('max_slippage', 0.1)  # 最大滑点容忍度（%）
        self.emergency_stop = False  # 紧急停止开关
        self.circuit_breakers = {
            'api_failures': 0,
            'max_api_failures': 5,  # 最大API失败次数
            'order_failures': 0,
            'max_order_failures': 3,  # 最大订单失败次数
            'network_failures': 0,
            'max_network_failures': 4,  # 最大网络失败次数
            'rate_limit_failures': 0,
            'max_rate_limit_failures': 2,  # 最大rate limit失败次数
            'is_circuit_broken': False,
            'broken_since': None
        }
        self.error_history = []  # 错误历史记录
        self.last_reset_time = datetime.now(pytz.UTC)  # 上次重置时间
    
    def is_bybit_trading_hours(self):
        """检查Bybit TradFi是否在交易时间"""
        now = datetime.now(pytz.UTC)
        utc_time = now.astimezone(pytz.UTC)
        weekday = utc_time.weekday()
        
        # Bybit TradFi 交易时间（UTC）: 周一至周五
        # 周六日休市
        if weekday >= 5:  # 周六或周日
            return False
        
        return True
    
    def should_close_weekend_positions(self):
        """判断是否需要在周末前平仓"""
        now = datetime.now(pytz.UTC)
        utc_time = now.astimezone(pytz.UTC)
        weekday = utc_time.weekday()
        hour = utc_time.hour
        minute = utc_time.minute
        
        # 周五 16:00 后开始准备平仓
        if weekday == 4 and (hour > 16 or (hour == 16 and minute >= 0)):
            return True
        return False
    
    def validate_slippage(self, expected_price, actual_price):
        """验证滑点是否在容忍范围内"""
        if expected_price == 0:
            return False
        slippage = abs((actual_price - expected_price) / expected_price) * 100
        return slippage <= self.max_slippage
    
    def trigger_emergency_stop(self, reason="紧急情况"):
        """触发紧急停止"""
        logger.warning(f"触发紧急停止: {reason}")
        self.emergency_stop = True
    
    def reset_emergency_stop(self):
        """重置紧急停止"""
        logger.info("重置紧急停止")
        self.emergency_stop = False
    
    def is_emergency_stop_active(self):
        """检查紧急停止是否激活"""
        return self.emergency_stop
    
    def record_error(self, error_type, error_message):
        """记录错误"""
        now = datetime.now(pytz.UTC)
        error_info = {
            'type': error_type,
            'message': error_message,
            'timestamp': now
        }
        self.error_history.append(error_info)
        
        # 限制错误历史记录数量
        if len(self.error_history) > 100:
            self.error_history = self.error_history[-100:]
        
        # 根据错误类型记录失败次数
        if error_type == 'api':
            self.circuit_breakers['api_failures'] += 1
        elif error_type == 'order':
            self.circuit_breakers['order_failures'] += 1
        elif error_type == 'network':
            self.circuit_breakers['network_failures'] += 1
        elif error_type == 'rate_limit':
            self.circuit_breakers['rate_limit_failures'] += 1
        
        self.check_circuit_breakers()
    
    def record_api_failure(self):
        """记录API失败"""
        self.record_error('api', 'API failure')
    
    def record_order_failure(self):
        """记录订单失败"""
        self.record_error('order', 'Order failure')
    
    def reset_failures(self):
        """重置失败计数"""
        self.circuit_breakers['api_failures'] = 0
        self.circuit_breakers['order_failures'] = 0
        self.circuit_breakers['network_failures'] = 0
        self.circuit_breakers['rate_limit_failures'] = 0
        self.circuit_breakers['is_circuit_broken'] = False
        self.circuit_breakers['broken_since'] = None
        self.last_reset_time = datetime.now(pytz.UTC)
        logger.info("重置失败计数和熔断机制")
    
    def check_circuit_breakers(self):
        """检查熔断机制"""
        now = datetime.now(pytz.UTC)
        
        # 检查是否应该自动重置熔断
        if self.circuit_breakers['is_circuit_broken']:
            broken_since = self.circuit_breakers['broken_since']
            if broken_since and (now - broken_since).total_seconds() > 300:  # 5分钟后自动尝试重置
                logger.info("熔断时间已过，尝试重置熔断机制")
                self.reset_failures()
                return
        
        # 检查各种失败条件
        if (
            self.circuit_breakers['api_failures'] >= self.circuit_breakers['max_api_failures'] or
            self.circuit_breakers['order_failures'] >= self.circuit_breakers['max_order_failures'] or
            self.circuit_breakers['network_failures'] >= self.circuit_breakers['max_network_failures'] or
            self.circuit_breakers['rate_limit_failures'] >= self.circuit_breakers['max_rate_limit_failures']
        ):
            if not self.circuit_breakers['is_circuit_broken']:
                self.circuit_breakers['is_circuit_broken'] = True
                self.circuit_breakers['broken_since'] = now
                logger.warning("触发熔断机制，暂停交易")
                logger.warning(f"熔断原因: API失败={self.circuit_breakers['api_failures']}, 订单失败={self.circuit_breakers['order_failures']}, "
                             f"网络失败={self.circuit_breakers['network_failures']}, Rate Limit失败={self.circuit_breakers['rate_limit_failures']}")
    
    def is_circuit_broken(self):
        """检查熔断是否触发"""
        return self.circuit_breakers['is_circuit_broken']
    
    def get_error_statistics(self):
        """获取错误统计信息"""
        now = datetime.now(pytz.UTC)
        recent_errors = [e for e in self.error_history if (now - e['timestamp']).total_seconds() < 3600]  # 最近1小时的错误
        
        error_counts = {
            'total': len(recent_errors),
            'api': sum(1 for e in recent_errors if e['type'] == 'api'),
            'order': sum(1 for e in recent_errors if e['type'] == 'order'),
            'network': sum(1 for e in recent_errors if e['type'] == 'network'),
            'rate_limit': sum(1 for e in recent_errors if e['type'] == 'rate_limit')
        }
        
        return error_counts

class ExchangeConnector:
    def __init__(self, config, risk_manager=None):
        self.config = config
        self.risk_manager = risk_manager
        self.connector = VNPYExchangeConnector(config)
        # 初始化连接
        asyncio.run(self._connect())
    
    async def _connect(self):
        try:
            success = self.connector.connect()
            if not success:
                raise Exception('VeighNa交易所连接失败')
            logger.info('VeighNa交易所连接成功')
        except Exception as e:
            logger.error(f'交易所连接失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_api_failure()
            raise
    
    async def get_binance_price(self, symbol='XAUUSDT'):
        start_time = time.time()
        try:
            price = await self.connector.get_binance_price(symbol)
            if price:
                # 记录API响应时间
                response_time = time.time() - start_time
                performance_monitor.record_api_response('binance_price', response_time)
                performance_monitor.record_success('api')
                return price
            else:
                # 记录错误
                response_time = time.time() - start_time
                performance_monitor.record_api_response('binance_price', response_time)
                performance_monitor.record_error('api')
                
                logger.error('获取币安价格失败')
                if self.risk_manager:
                    self.risk_manager.record_api_failure()
                return None
        except Exception as e:
            # 记录错误
            response_time = time.time() - start_time
            performance_monitor.record_api_response('binance_price', response_time)
            performance_monitor.record_error('api')
            
            logger.error(f'获取币安价格失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_api_failure()
            return None
    
    async def get_bybit_price(self, symbol='XAUUSD'):
        start_time = time.time()
        try:
            price = await self.connector.get_bybit_price(symbol)
            if price:
                # 记录API响应时间
                response_time = time.time() - start_time
                performance_monitor.record_api_response('bybit_price', response_time)
                performance_monitor.record_success('api')
                return price
            else:
                # 记录错误
                response_time = time.time() - start_time
                performance_monitor.record_api_response('bybit_price', response_time)
                performance_monitor.record_error('api')
                
                logger.error('获取Bybit价格失败')
                if self.risk_manager:
                    self.risk_manager.record_api_failure()
                return None
        except Exception as e:
            # 记录错误
            response_time = time.time() - start_time
            performance_monitor.record_api_response('bybit_price', response_time)
            performance_monitor.record_error('api')
            
            logger.error(f'获取Bybit价格失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_api_failure()
            return None
    
    async def binance_place_order(self, symbol, side, amount, price=None, order_type='limit'):
        start_time = time.time()
        try:
            order = await self.connector.binance_place_order(symbol, side, amount, price, order_type)
            if order:
                # 记录订单执行时间
                execution_time = time.time() - start_time
                performance_monitor.record_order_execution('binance', execution_time)
                performance_monitor.record_success('order')
                
                logger.info(f'币安下单成功: {order}')
                return order
            else:
                # 记录错误
                execution_time = time.time() - start_time
                performance_monitor.record_order_execution('binance', execution_time)
                performance_monitor.record_error('order')
                
                logger.error('币安下单失败')
                if self.risk_manager:
                    self.risk_manager.record_order_failure()
                return None
        except Exception as e:
            # 记录错误
            execution_time = time.time() - start_time
            performance_monitor.record_order_execution('binance', execution_time)
            performance_monitor.record_error('order')
            
            logger.error(f'币安下单失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_order_failure()
            return None
    
    async def bybit_place_order(self, symbol, side, amount, price=None, order_type='limit'):
        start_time = time.time()
        try:
            order = await self.connector.bybit_place_order(symbol, side, amount, price, order_type)
            if order:
                # 记录订单执行时间
                execution_time = time.time() - start_time
                performance_monitor.record_order_execution('bybit', execution_time)
                performance_monitor.record_success('order')
                
                logger.info(f'Bybit下单成功: {order}')
                return order
            else:
                # 记录错误
                execution_time = time.time() - start_time
                performance_monitor.record_order_execution('bybit', execution_time)
                performance_monitor.record_error('order')
                
                logger.error('Bybit下单失败')
                if self.risk_manager:
                    self.risk_manager.record_order_failure()
                return None
        except Exception as e:
            # 记录错误
            execution_time = time.time() - start_time
            performance_monitor.record_order_execution('bybit', execution_time)
            performance_monitor.record_error('order')
            
            logger.error(f'Bybit下单失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_order_failure()
            return None
    
    async def close_all_bybit_positions(self, symbol='XAUUSD'):
        try:
            # 这里简化处理，实际应该获取当前持仓并平仓
            logger.info('关闭Bybit所有头寸')
            # 实际平仓逻辑
        except Exception as e:
            logger.error(f'平Bybit仓位失败: {e}')
    
    async def get_market_depth(self, exchange, symbol, limit=10):
        """获取市场深度"""
        try:
            orderbook = await self.connector.get_order_book(exchange, symbol, limit)
            return orderbook
        except Exception as e:
            logger.error(f'获取市场深度失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_api_failure()
            return None
    
    async def assess_liquidity(self, exchange, symbol, amount):
        """评估流动性和预测滑点"""
        start_time = time.time()
        try:
            orderbook = await self.get_market_depth(exchange, symbol)
            if not orderbook:
                # 记录流动性评估时间
                assessment_time = time.time() - start_time
                performance_monitor.record_liquidity_assessment(assessment_time)
                return {'has_enough_liquidity': False, 'estimated_slippage': 0}
            
            # 计算市场深度
            bids = orderbook['bids']
            asks = orderbook['asks']
            
            # 评估买单流动性和预测滑点
            total_bid_liquidity = 0
            bid_depth_levels = 0
            bid_weighted_avg_price = 0
            cumulative_bid_value = 0
            
            for price, qty in bids:
                qty_float = float(qty)
                total_bid_liquidity += qty_float
                bid_depth_levels += 1
                
                # 计算加权平均价格
                price_float = float(price)
                value = price_float * qty_float
                cumulative_bid_value += value
                
                if total_bid_liquidity >= amount:
                    break
            
            # 评估卖单流动性和预测滑点
            total_ask_liquidity = 0
            ask_depth_levels = 0
            ask_weighted_avg_price = 0
            cumulative_ask_value = 0
            
            for price, qty in asks:
                qty_float = float(qty)
                total_ask_liquidity += qty_float
                ask_depth_levels += 1
                
                # 计算加权平均价格
                price_float = float(price)
                value = price_float * qty_float
                cumulative_ask_value += value
                
                if total_ask_liquidity >= amount:
                    break
            
            # 计算加权平均价格
            if total_bid_liquidity > 0:
                bid_weighted_avg_price = cumulative_bid_value / total_bid_liquidity
            if total_ask_liquidity > 0:
                ask_weighted_avg_price = cumulative_ask_value / total_ask_liquidity
            
            # 预测滑点
            estimated_slippage = 0
            if bids and asks:
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                mid_price = (best_bid + best_ask) / 2
                
                # 根据订单大小和市场深度预测滑点
                if amount > 0:
                    # 计算流动性比率
                    bid_liquidity_ratio = min(1, amount / total_bid_liquidity) if total_bid_liquidity > 0 else 1
                    ask_liquidity_ratio = min(1, amount / total_ask_liquidity) if total_ask_liquidity > 0 else 1
                    
                    # 计算点差
                    spread = best_ask - best_bid
                    
                    # 基于流动性比率和点差预测滑点
                    estimated_slippage_buy = spread * (1 + bid_liquidity_ratio * 2)
                    estimated_slippage_sell = spread * (1 + ask_liquidity_ratio * 2)
                    estimated_slippage = max(estimated_slippage_buy, estimated_slippage_sell)
            
            # 检查是否有足够的流动性
            has_enough_liquidity = total_bid_liquidity >= amount and total_ask_liquidity >= amount
            
            # 评估流动性质量
            liquidity_quality = 'high'
            if not has_enough_liquidity:
                liquidity_quality = 'low'
            elif bid_depth_levels > 5 or ask_depth_levels > 5:
                # 需要超过5个层级才能满足订单，流动性一般
                liquidity_quality = 'medium'
            
            # 记录流动性评估时间
            assessment_time = time.time() - start_time
            performance_monitor.record_liquidity_assessment(assessment_time)
            
            logger.info(f'流动性评估: {exchange} {symbol} - 买单流动性={total_bid_liquidity:.2f}, 卖单流动性={total_ask_liquidity:.2f}, 所需={amount:.2f}, 足够={has_enough_liquidity}')
            logger.info(f'流动性质量: {liquidity_quality}, 买单深度层级={bid_depth_levels}, 卖单深度层级={ask_depth_levels}, 预估滑点={estimated_slippage:.4f}')
            
            return {
                'has_enough_liquidity': has_enough_liquidity,
                'total_bid_liquidity': total_bid_liquidity,
                'total_ask_liquidity': total_ask_liquidity,
                'liquidity_quality': liquidity_quality,
                'bid_depth_levels': bid_depth_levels,
                'ask_depth_levels': ask_depth_levels,
                'estimated_slippage': estimated_slippage,
                'best_bid': float(bids[0][0]) if bids else 0,
                'best_ask': float(asks[0][0]) if asks else 0
            }
        except Exception as e:
            # 记录流动性评估时间
            assessment_time = time.time() - start_time
            performance_monitor.record_liquidity_assessment(assessment_time)
            
            logger.error(f'评估流动性失败: {e}')
            return {'has_enough_liquidity': False, 'estimated_slippage': 0}
    
    async def smart_order_router(self, exchange, symbol, side, amount, price=None, order_type='limit'):
        """智能订单路由"""
        try:
            # 评估流动性
            liquidity = await self.assess_liquidity(exchange, symbol, amount)
            
            # 根据流动性质量和预估滑点调整订单执行策略
            if not liquidity['has_enough_liquidity']:
                logger.warning(f'流动性不足，拆分订单: {exchange} {symbol}')
                # 流动性不足，拆分为更多订单
                split_count = 5 if liquidity['liquidity_quality'] == 'low' else 3
                order_size = amount / split_count
                orders = []
                
                # 分批执行订单，每批之间加入小延迟
                for i in range(split_count):
                    if exchange == 'binance':
                        order = await self.binance_place_order(
                            symbol,
                            side,
                            order_size,
                            price,
                            order_type
                        )
                    elif exchange == 'bybit':
                        order = await self.bybit_place_order(
                            symbol,
                            side,
                            order_size,
                            price,
                            order_type
                        )
                    if order:
                        orders.append(order)
                    
                    # 小延迟，避免同时下单造成市场冲击
                    if i < split_count - 1:
                        await asyncio.sleep(0.1)
                
                logger.info(f'智能订单路由完成，拆分了 {len(orders)} 个订单')
                return orders
            else:
                # 根据流动性质量调整订单策略
                if liquidity['liquidity_quality'] == 'high':
                    # 流动性良好，直接下单
                    if exchange == 'binance':
                        order = await self.binance_place_order(
                            symbol,
                            side,
                            amount,
                            price,
                            order_type
                        )
                    elif exchange == 'bybit':
                        order = await self.bybit_place_order(
                            symbol,
                            side,
                            amount,
                            price,
                            order_type
                        )
                    return [order] if order else []
                else:
                    # 流动性一般，拆分订单以减少市场冲击
                    logger.info(f'流动性一般，拆分订单以减少市场冲击: {exchange} {symbol}')
                    split_count = 2
                    order_size = amount / split_count
                    orders = []
                    
                    for i in range(split_count):
                        if exchange == 'binance':
                            order = await self.binance_place_order(
                                symbol,
                                side,
                                order_size,
                                price,
                                order_type
                            )
                        elif exchange == 'bybit':
                            order = await self.bybit_place_order(
                                symbol,
                                side,
                                order_size,
                                price,
                                order_type
                            )
                        if order:
                            orders.append(order)
                        
                        # 小延迟
                        if i < split_count - 1:
                            await asyncio.sleep(0.1)
                    
                    logger.info(f'智能订单路由完成，拆分了 {len(orders)} 个订单')
                    return orders
        except Exception as e:
            logger.error(f'智能订单路由失败: {e}')
            return []
    
    async def get_binance_account_info(self):
        """获取币安账户信息"""
        try:
            account = await self.connector.get_binance_account_info()
            return account
        except Exception as e:
            logger.error(f'获取币安账户信息失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_api_failure()
            return None
    
    async def get_bybit_account_info(self):
        """获取Bybit账户信息"""
        try:
            account = await self.connector.get_bybit_account_info()
            return account
        except Exception as e:
            logger.error(f'获取Bybit账户信息失败: {e}')
            if self.risk_manager:
                self.risk_manager.record_api_failure()
            return None

class Strategy:
    def __init__(self, exchange, risk_manager, config):
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.config = config
        self.min_spread = config.get('min_spread', 3.0)  # 最小入场点差
        self.exit_spread = config.get('exit_spread', 0.5)  # 出场点差
        self.trade_size_xau = config.get('trade_size_xau', 1.0)  # 交易XAU数量
        self.max_slippage = config.get('max_slippage', 0.1)  # 最大滑点容忍度（%）
        self.binance_taker_fee = config.get('binance_taker_fee', 0.0004)  # 币安Taker手续费
        self.bybit_spread_cost = config.get('bybit_spread_cost', 0.5)  # Bybit点差成本
        self.positions = {
            'binance': None,
            'bybit': None
        }
        self.funding_rate_data = {
            'binance': None,
            'bybit': None
        }
    
    async def calculate_spread(self):
        """计算两个平台之间的点差，考虑交易成本和流动性"""
        start_time = time.time()
        # 并行获取两个平台的价格
        binance_price_task = self.exchange.get_binance_price()
        bybit_price_task = self.exchange.get_bybit_price()
        
        binance_price, bybit_price = await asyncio.gather(
            binance_price_task, 
            bybit_price_task
        )
        
        if not binance_price or not bybit_price:
            logger.warning('无法获取价格数据，跳过点差计算')
            return None
        
        # 使用中间价计算点差
        binance_mid = (binance_price['bid'] + binance_price['ask']) / 2
        bybit_mid = (bybit_price['bid'] + bybit_price['ask']) / 2
        
        spread = abs(binance_mid - bybit_mid)
        spread_percent = (spread / min(binance_mid, bybit_mid)) * 100
        
        # 评估流动性和预测滑点
        binance_liquidity_task = self.exchange.assess_liquidity('binance', 'XAUUSDT', self.trade_size_xau)
        bybit_liquidity_task = self.exchange.assess_liquidity('bybit', 'XAUUSD', self.trade_size_xau)
        
        binance_liquidity, bybit_liquidity = await asyncio.gather(
            binance_liquidity_task, 
            bybit_liquidity_task
        )
        
        # 计算交易成本
        binance_trade_cost = binance_mid * self.binance_taker_fee
        
        # 使用实际预估的滑点
        binance_slippage = binance_liquidity.get('estimated_slippage', 0)
        bybit_slippage = bybit_liquidity.get('estimated_slippage', 0)
        estimated_slippage = max(binance_slippage, bybit_slippage)
        
        # 计算总成本
        total_cost = binance_trade_cost + self.bybit_spread_cost + estimated_slippage
        
        # 计算有效点差（考虑交易成本后的点差）
        effective_spread = spread - total_cost
        
        # 评估套利机会质量
        arbitrage_quality = 'excellent' if effective_spread > self.min_spread * 1.5 else \
                          'good' if effective_spread >= self.min_spread else \
                          'marginal' if effective_spread > 0 else 'none'
        
        # 记录点差计算时间
        calculation_time = time.time() - start_time
        performance_monitor.record_spread_calculation(calculation_time)
        
        logger.info(f'点差计算: 币安={binance_mid:.2f}, Bybit={bybit_mid:.2f}, 点差={spread:.2f} ({spread_percent:.4f}%)')
        logger.info(f'交易成本: 币安手续费={binance_trade_cost:.2f}, Bybit点差={self.bybit_spread_cost:.2f}, 预估滑点={estimated_slippage:.2f}, 总成本={total_cost:.2f}')
        logger.info(f'有效点差: {effective_spread:.2f}, 套利机会质量: {arbitrage_quality}')
        
        return {
            'binance': binance_mid,
            'bybit': bybit_mid,
            'spread': spread,
            'spread_percent': spread_percent,
            'effective_spread': effective_spread,
            'total_cost': total_cost,
            'arbitrage_quality': arbitrage_quality,
            'binance_price': binance_price,
            'bybit_price': bybit_price,
            'binance_liquidity': binance_liquidity,
            'bybit_liquidity': bybit_liquidity
        }
    
    def check_funding_rate(self):
        """检查资金费率差异"""
        try:
            # 获取币安资金费率
            funding = self.exchange.binance.fetch_funding_rate('XAUUSDT')
            binance_funding = float(funding['fundingRate'])
            
            logger.info(f'币安资金费率: {binance_funding:.6f}')
            return binance_funding
        except Exception as e:
            logger.error(f'获取资金费率失败: {e}')
            return None
    
    async def check_margin_ratio(self):
        """检查保证金率"""
        try:
            # 并行获取币安和Bybit的账户信息
            binance_account_task = self.exchange.get_binance_account_info()
            bybit_account_task = self.exchange.get_bybit_account_info()
            
            binance_account, bybit_account = await asyncio.gather(
                binance_account_task, 
                bybit_account_task
            )
            
            # 设置保证金率预警阈值
            margin_warning_threshold = 150  # 150% 保证金率
            margin_danger_threshold = 120  # 120% 保证金率
            
            # 检查币安保证金率
            if binance_account:
                total_balance = float(binance_account['total']['USDT'])
                used_margin = float(binance_account['used']['USDT'])
                if used_margin > 0:
                    binance_margin = (total_balance / used_margin) * 100
                    logger.info(f'币安保证金率: {binance_margin:.2f}%')
                    
                    if binance_margin < margin_danger_threshold:
                        logger.warning(f'币安保证金率过低: {binance_margin:.2f}%，触发紧急停止')
                        self.risk_manager.trigger_emergency_stop('币安保证金率过低')
                    elif binance_margin < margin_warning_threshold:
                        logger.warning(f'币安保证金率警告: {binance_margin:.2f}%')
            
            # 检查Bybit保证金率
            if bybit_account:
                # MT5账户信息格式不同，简化处理
                total_balance = float(bybit_account.get('balance', 0))
                used_margin = float(bybit_account.get('frozen', 0))
                if used_margin > 0:
                    bybit_margin = (total_balance / used_margin) * 100
                    logger.info(f'Bybit保证金率: {bybit_margin:.2f}%')
                    
                    if bybit_margin < margin_danger_threshold:
                        logger.warning(f'Bybit保证金率过低: {bybit_margin:.2f}%，触发紧急停止')
                        self.risk_manager.trigger_emergency_stop('Bybit保证金率过低')
                    elif bybit_margin < margin_warning_threshold:
                        logger.warning(f'Bybit保证金率警告: {bybit_margin:.2f}%')
                        
        except Exception as e:
            logger.error(f'检查保证金率失败: {e}')
    
    async def execute_arbitrage(self):
        """执行套利策略"""
        # 检查紧急停止
        if self.risk_manager.is_emergency_stop_active():
            logger.warning('紧急停止已激活，跳过交易')
            return
        
        # 检查熔断机制
        if self.risk_manager.is_circuit_broken():
            logger.warning('熔断机制已触发，跳过交易')
            return
        
        # 检查保证金率
        await self.check_margin_ratio()
        
        # 检查是否需要处理周末休市
        if self.risk_manager.should_close_weekend_positions():
            logger.info('周末休市前，关闭所有Bybit头寸')
            await self.exchange.close_all_bybit_positions()
            self.positions['bybit'] = None
            # 相应调整币安头寸
            if self.positions['binance']:
                logger.info('调整币安头寸以应对周末休市')
            return
        
        # 计算点差
        spread_data = await self.calculate_spread()
        if not spread_data:
            return
        
        # 检查资金费率
        funding_rate = self.check_funding_rate()
        
        # 检查是否已存在头寸
        if self.positions['binance'] and self.positions['bybit']:
            # 检查是否应该出场
            if spread_data['effective_spread'] < self.exit_spread:
                logger.info('点差收敛，平仓出场')
                # 平仓逻辑
                self.positions['binance'] = None
                self.positions['bybit'] = None
            return
        
        # 检查是否满足点差套利入场条件
        if spread_data['effective_spread'] >= self.min_spread:
            logger.info(f'有效点差满足条件，准备入场，套利机会质量: {spread_data["arbitrage_quality"]}')
            
            # 确定买卖方向
            if spread_data['binance'] < spread_data['bybit']:
                # 币安买，Bybit卖
                binance_side = 'buy'
                bybit_side = 'sell'
                # 根据流动性和滑点调整价格
                binance_liquidity = spread_data['binance_liquidity']
                bybit_liquidity = spread_data['bybit_liquidity']
                
                binance_price = spread_data['binance_price']['ask'] + binance_liquidity.get('estimated_slippage', 0)
                bybit_price = spread_data['bybit_price']['bid'] - bybit_liquidity.get('estimated_slippage', 0)
            else:
                # 币安卖，Bybit买
                binance_side = 'sell'
                bybit_side = 'buy'
                # 根据流动性和滑点调整价格
                binance_liquidity = spread_data['binance_liquidity']
                bybit_liquidity = spread_data['bybit_liquidity']
                
                binance_price = spread_data['binance_price']['bid'] - binance_liquidity.get('estimated_slippage', 0)
                bybit_price = spread_data['bybit_price']['ask'] + bybit_liquidity.get('estimated_slippage', 0)
            
            # 根据套利机会质量调整订单类型
            order_type = 'market' if spread_data['arbitrage_quality'] == 'excellent' else 'limit'
            
            # 并行执行智能订单路由
            binance_orders_task = self.exchange.smart_order_router(
                'binance',
                'XAUUSDT',
                binance_side,
                self.trade_size_xau,
                binance_price if order_type == 'limit' else None,
                order_type=order_type
            )
            
            bybit_orders_task = self.exchange.smart_order_router(
                'bybit',
                'XAUUSD',
                bybit_side,
                self.trade_size_xau,
                bybit_price if order_type == 'limit' else None,
                order_type=order_type
            )
            
            binance_orders, bybit_orders = await asyncio.gather(
                binance_orders_task, 
                bybit_orders_task
            )
            
            if binance_orders and bybit_orders:
                logger.info('点差套利入场成功')
                self.positions['binance'] = binance_orders[0]  # 保存第一个订单
                self.positions['bybit'] = bybit_orders[0]  # 保存第一个订单
            else:
                logger.error('套利入场失败，取消所有订单')
                # 尝试取消已下单的订单
                for order in binance_orders:
                    try:
                        self.exchange.binance.cancel_order(order['id'], 'XAUUSDT')
                    except:
                        pass
                for order in bybit_orders:
                    try:
                        if 'orderId' in order['result']:
                            self.exchange.bybit.cancel_order(
                                category='tradfi',
                                orderId=order['result']['orderId'],
                                symbol='XAUUSD+'
                            )
                    except:
                        pass
        
        # 检查是否满足资金费率套利入场条件
        if funding_rate and abs(funding_rate) > 0.0001:  # 资金费率大于0.01%
            # 评估资金费率套利机会质量
            funding_rate_abs = abs(funding_rate)
            funding_opportunity_quality = 'excellent' if funding_rate_abs > 0.0005 else \
                                        'good' if funding_rate_abs >= 0.0002 else 'marginal'
            
            logger.info(f'资金费率差异满足条件，准备入场，资金费率: {funding_rate:.6f}, 机会质量: {funding_opportunity_quality}')
            
            # 资金费率套利逻辑
            if funding_rate > 0:
                # 币安资金费率为正，做多币安，做空Bybit
                binance_side = 'buy'
                bybit_side = 'sell'
            else:
                # 币安资金费率为负，做空币安，做多Bybit
                binance_side = 'sell'
                bybit_side = 'buy'
            
            # 根据机会质量调整订单类型
            order_type = 'market' if funding_opportunity_quality == 'excellent' else 'limit'
            
            # 获取最新价格用于限价单
            binance_price = None
            bybit_price = None
            
            if order_type == 'limit':
                # 对于限价单，获取最新价格
                binance_price_data = await self.exchange.get_binance_price()
                bybit_price_data = await self.exchange.get_bybit_price()
                
                if binance_price_data and bybit_price_data:
                    if binance_side == 'buy':
                        binance_price = binance_price_data['ask']
                    else:
                        binance_price = binance_price_data['bid']
                    
                    if bybit_side == 'buy':
                        bybit_price = bybit_price_data['ask']
                    else:
                        bybit_price = bybit_price_data['bid']
            
            # 并行执行智能订单路由
            binance_orders_task = self.exchange.smart_order_router(
                'binance',
                'XAUUSDT',
                binance_side,
                self.trade_size_xau,
                binance_price if order_type == 'limit' else None,
                order_type=order_type
            )
            
            bybit_orders_task = self.exchange.smart_order_router(
                'bybit',
                'XAUUSD+',
                bybit_side,
                self.trade_size_xau,
                bybit_price if order_type == 'limit' else None,
                order_type=order_type
            )
            
            binance_orders, bybit_orders = await asyncio.gather(
                binance_orders_task, 
                bybit_orders_task
            )
            
            if binance_orders and bybit_orders:
                logger.info('资金费率套利入场成功')
                self.positions['binance'] = binance_orders[0]  # 保存第一个订单
                self.positions['bybit'] = bybit_orders[0]  # 保存第一个订单
            else:
                logger.error('资金费率套利入场失败，取消所有订单')
                # 尝试取消已下单的订单
                for order in binance_orders:
                    try:
                        self.exchange.binance.cancel_order(order['id'], 'XAUUSDT')
                    except:
                        pass
                for order in bybit_orders:
                    try:
                        if 'orderId' in order['result']:
                            self.exchange.bybit.cancel_order(
                                category='tradfi',
                                orderId=order['result']['orderId'],
                                symbol='XAUUSD+'
                            )
                    except:
                        pass

class ArbitrageSystem:
    def __init__(self, config=None, config_file=None):
        # 如果提供了配置文件，使用ConfigManager
        if config_file:
            self.config_manager = ConfigManager(config_file)
            self.config = self.config_manager.get_all()
        else:
            # 否则使用传入的配置
            self.config_manager = None
            self.config = config or {}
        
        self.risk_manager = RiskManager(self.config)
        self.exchange = ExchangeConnector(self.config, self.risk_manager)
        self.strategy = Strategy(self.exchange, self.risk_manager, self.config)
        self.running = False
    
    def update_config(self, new_config):
        """更新配置"""
        if self.config_manager:
            self.config_manager._merge_config(new_config)
            self.config = self.config_manager.get_all()
        else:
            self.config.update(new_config)
        
        # 更新相关组件的配置
        self.strategy.config = self.config
        logger.info('配置已更新')
    
    def reload_config(self):
        """重新加载配置"""
        if self.config_manager:
            self.config_manager.reload()
            self.config = self.config_manager.get_all()
            # 更新相关组件的配置
            self.strategy.config = self.config
            logger.info('配置已重新加载')
    
    async def run(self):
        """运行套利系统"""
        self.running = True
        logger.info('Hustle XAU点差对冲搬砖系统启动')
        
        performance_report_counter = 0
        
        try:
            while self.running:
                try:
                    # 记录系统请求
                    performance_monitor.record_request()
                    
                    # 执行套利策略
                    await self.strategy.execute_arbitrage()
                    
                    # 每10次循环生成一次性能报告
                    performance_report_counter += 1
                    if performance_report_counter >= 10:
                        performance_monitor.log_performance_report()
                        performance_report_counter = 0
                    
                    # 休眠一段时间后再次检查
                    await asyncio.sleep(self.config.get('interval', 5))
                except Exception as e:
                    # 记录错误
                    performance_monitor.record_error('system')
                    logger.error(f'系统运行错误: {e}')
                    if self.risk_manager:
                        self.risk_manager.record_api_failure()
                    await asyncio.sleep(10)  # 错误后延长休眠时间
        except KeyboardInterrupt:
            logger.info('系统手动停止')
        finally:
            logger.info('系统关闭，清理头寸')
            # 生成最终性能报告
            performance_monitor.log_performance_report()
            # 关闭所有头寸
            await self.exchange.close_all_bybit_positions()
            self.running = False
    
    def start(self):
        """启动系统（同步入口）"""
        asyncio.run(self.run())

if __name__ == '__main__':
    # 配置示例
    config = {
        'binance': {
            'api_key': 'YOUR_BINANCE_KEY',
            'api_secret': 'YOUR_BINANCE_SECRET'
        },
        'bybit': {
            'api_key': 'YOUR_BYBIT_KEY',
            'api_secret': 'YOUR_BYBIT_SECRET'
        },
        'min_spread': 3.0,
        'exit_spread': 0.5,
        'trade_size_xau': 1.0,
        'max_slippage': 0.1,
        'binance_taker_fee': 0.0004,
        'bybit_spread_cost': 0.5,
        'interval': 5  # 检查间隔（秒）
    }
    
    # 方式1：使用字典配置创建系统实例
    # system = ArbitrageSystem(config)
    
    # 方式2：从配置文件创建系统实例
    # system = ArbitrageSystem(config_file='config.json')
    
    # 创建系统实例（默认方式）
    system = ArbitrageSystem(config)
    
    # 示例：运行时更新配置
    # system.update_config({'min_spread': 4.0, 'interval': 3})
    
    # 示例：重新加载配置
    # system.reload_config()
    
    # 注意：取消下面一行的注释以运行系统
    # system.start()
