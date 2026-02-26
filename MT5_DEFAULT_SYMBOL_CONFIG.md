# MT5默认品种配置说明

## 配置概述

已将MT5默认交易品种设置为 **XAUUSD.s**，并在系统初始化时自动激活和订阅该品种。

## 配置内容

### 1. 配置文件设置

**文件**: `backend/app/core/config.py`

新增配置项：
```python
# MT5 Trading Configuration
MT5_DEFAULT_SYMBOL: str = "XAUUSD.s"  # 默认交易品种
MT5_DEFAULT_SYMBOLS: List[str] = ["XAUUSD.s"]  # 默认监控品种列表
```

**说明**：
- `MT5_DEFAULT_SYMBOL`: 单个默认品种，用于快速引用
- `MT5_DEFAULT_SYMBOLS`: 品种列表，支持多品种监控（可扩展）

### 2. 自动初始化机制

**文件**: `backend/app/services/mt5_client.py`

#### 连接时自动初始化
```python
def connect(self) -> bool:
    """连接MT5时自动初始化默认品种"""
    # ... MT5连接逻辑 ...

    # 初始化默认品种（确保XAUUSD.s可见并就绪）
    self._initialize_default_symbols()

    return True
```

#### 品种初始化逻辑
```python
def _initialize_default_symbols(self):
    """初始化并激活默认交易品种"""
    default_symbols = settings.MT5_DEFAULT_SYMBOLS

    for symbol in default_symbols:
        # 1. 检查品种是否存在
        symbol_info = mt5.symbol_info(symbol)

        # 2. 确保品种可见（XAUUSD.s可能默认隐藏）
        if not symbol_info.visible:
            mt5.symbol_select(symbol, True)
            logger.info(f"Symbol {symbol} activated successfully")

        # 3. 订阅市场数据
        mt5.market_book_add(symbol)
```

**优势**：
- 每次连接MT5时自动激活XAUUSD.s
- 无需手动在MT5客户端中添加品种
- 确保品种始终可用于交易

### 3. 便捷访问方法

新增3个便捷方法：

#### get_default_symbol()
```python
def get_default_symbol(self) -> str:
    """获取默认交易品种"""
    return settings.MT5_DEFAULT_SYMBOL  # 返回 "XAUUSD.s"
```

#### get_default_symbol_info()
```python
def get_default_symbol_info(self) -> Optional[Dict[str, Any]]:
    """获取默认品种的详细信息"""
    return {
        'symbol': 'XAUUSD.s',
        'digits': 2,
        'point': 0.01,
        'volume_min': 0.01,
        'volume_max': 100.0,
        'volume_step': 0.01,
        'contract_size': 100.0,
        'visible': True,
        'spread': 3
    }
```

#### get_latest_tick() / get_latest_price()
```python
# 获取默认品种的最新报价
default_symbol = mt5_client.get_default_symbol()
tick = mt5_client.get_latest_tick(default_symbol)
price = mt5_client.get_latest_price(default_symbol)
```

## 使用示例

### 示例1：获取默认品种信息
```python
from app.services.market_service import market_data_service

mt5_client = market_data_service.mt5_client

# 获取默认品种名称
symbol = mt5_client.get_default_symbol()
print(f"Default symbol: {symbol}")  # 输出: XAUUSD.s

# 获取默认品种详细信息
info = mt5_client.get_default_symbol_info()
print(f"Digits: {info['digits']}")  # 输出: 2
print(f"Min volume: {info['volume_min']}")  # 输出: 0.01
```

### 示例2：使用默认品种下单
```python
# 获取默认品种
symbol = mt5_client.get_default_symbol()

# 获取最新报价
latest_price = mt5_client.get_latest_price(symbol)

# 下单
result = mt5_client.send_order(
    symbol=symbol,  # 使用默认品种
    order_type=mt5.ORDER_TYPE_BUY_LIMIT,
    volume=0.03,
    price=latest_price - 0.5
)
```

### 示例3：在套利策略中使用
```python
# 套利策略自动使用默认品种
async def execute_reverse_arbitrage(...):
    # 获取默认品种
    bybit_symbol = mt5_client.get_default_symbol()  # XAUUSD.s

    # 执行订单
    result = await order_executor.execute_dual_order(
        binance_symbol="XAUUSDT",
        bybit_symbol=bybit_symbol,  # 使用默认品种
        ...
    )
```

## 初始化流程

```
MT5连接
    ↓
读取配置 (MT5_DEFAULT_SYMBOLS)
    ↓
遍历默认品种列表
    ↓
检查品种是否存在
    ↓
激活隐藏品种 (symbol_select)
    ↓
订阅市场数据 (market_book_add)
    ↓
记录初始化日志
    ↓
完成
```

## 日志输出

初始化成功时的日志：
```
INFO: MT5 connected successfully to account 12345678
INFO: Initializing default MT5 symbols: ['XAUUSD.s']
INFO: Symbol XAUUSD.s activated successfully
INFO: Symbol XAUUSD.s already visible
```

## 配置扩展

如需添加更多默认品种，修改配置文件：

```python
# 支持多品种监控
MT5_DEFAULT_SYMBOLS: List[str] = [
    "XAUUSD.s",   # 黄金
    "XAGUSD.s",   # 白银
    "EURUSD.s"    # 欧元美元
]
```

系统会在连接时自动初始化所有列出的品种。

## 环境变量配置

也可以通过环境变量覆盖默认设置：

```bash
# .env 文件
MT5_DEFAULT_SYMBOL=XAUUSD.s
MT5_DEFAULT_SYMBOLS=["XAUUSD.s", "XAGUSD.s"]
```

## 优势总结

1. **自动化**: 连接时自动激活XAUUSD.s，无需手动操作
2. **可靠性**: 确保品种始终可见和可用
3. **便捷性**: 提供快速访问方法，简化代码
4. **可扩展**: 支持多品种配置
5. **集中管理**: 统一配置文件管理默认品种

## 相关文件

- `backend/app/core/config.py` - 配置定义
- `backend/app/services/mt5_client.py` - 初始化逻辑和便捷方法
- `backend/app/services/arbitrage_strategy.py` - 套利策略使用

## 测试验证

启动后端后，检查日志确认XAUUSD.s已成功初始化：

```bash
tail -f backend/backend.log | grep "XAUUSD.s"
```

预期输出：
```
INFO: Symbol XAUUSD.s activated successfully
```
