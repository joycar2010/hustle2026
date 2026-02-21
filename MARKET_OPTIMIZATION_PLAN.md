# 行情接口优化实施方案

## 当前问题
1. 后端每1秒调用Binance/Bybit REST API，导致rate limit
2. 无账户状态检查，即使没有启用账户也在调用API
3. MT5周末休市时仍在调用API
4. 使用REST轮询而非WebSocket实时订阅
5. 缺少心跳和重连机制

## 优化目标
1. **账户状态检查**：只在有启用账户时调用相应平台API
2. **MT5市场时间检查**：周末和非交易时间停止调用
3. **Binance WebSocket**：使用WebSocket订阅实时行情，REST API作为兜底
4. **心跳/重连机制**：监控连接状态，自动重连
5. **优化轮询频率**：
   - 行情：200ms (WebSocket推送)
   - 持仓：1-2s
   - 账户余额：3-5s
   - 下单：同步REST

## 实施步骤

### 第一阶段：账户状态检查和MT5市场时间检查

#### 1.1 添加账户状态检查方法
**文件**: `backend/app/services/realtime_market_service.py`

```python
async def check_active_accounts(self):
    """检查是否有启用的账户"""
    db = SessionLocal()
    try:
        # 检查Binance账户
        binance_accounts = db.query(Account).filter(
            Account.platform_id == 1,  # Binance
            Account.is_active == True
        ).count()
        self.has_binance_accounts = binance_accounts > 0

        # 检查Bybit账户
        bybit_accounts = db.query(Account).filter(
            Account.platform_id == 2,  # Bybit
            Account.is_active == True
        ).count()
        self.has_bybit_accounts = bybit_accounts > 0

        logger.info(f"Active accounts - Binance: {self.has_binance_accounts}, Bybit: {self.has_bybit_accounts}")
    finally:
        db.close()
```

#### 1.2 添加MT5市场时间检查
```python
def is_mt5_market_open(self) -> bool:
    """检查MT5市场是否开放（周一00:00 - 周六00:00 UTC）"""
    now = datetime.utcnow()
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    # 周六和周日休市
    if weekday == 5 or weekday == 6:
        return False

    # 周五晚上到周六凌晨休市
    if weekday == 4 and now.hour >= 22:
        return False

    return True
```

#### 1.3 修改fetch_and_store_market_data
```python
async def fetch_and_store_market_data(self, symbol: str = "XAUUSDT"):
    # 每60秒检查一次账户状态
    if not self.last_account_check or (datetime.now() - self.last_account_check).seconds > 60:
        await self.check_active_accounts()
        self.last_account_check = datetime.now()

    # 只在有启用账户时调用API
    binance_data = None
    if self.has_binance_accounts:
        binance_data = await self.fetch_binance_ticker(symbol)

    bybit_data = None
    if self.has_bybit_accounts and self.is_mt5_market_open():
        bybit_data = await self.fetch_bybit_ticker(bybit_symbol)

    # ... 存储数据
```

### 第二阶段：Binance WebSocket实现

#### 2.1 创建WebSocket客户端
**新文件**: `backend/app/services/binance_websocket.py`

```python
import asyncio
import json
import logging
from typing import Optional, Callable
import websockets

logger = logging.getLogger(__name__)

class BinanceWebSocketClient:
    """Binance WebSocket客户端"""

    def __init__(self, symbol: str = "xauusdt"):
        self.symbol = symbol.lower()
        self.ws_url = f"wss://fstream.binance.com/ws/{self.symbol}@bookTicker"
        self.ws = None
        self.running = False
        self.callback: Optional[Callable] = None
        self.last_message_time = None
        self.reconnect_delay = 5

    async def connect(self):
        """连接WebSocket"""
        try:
            self.ws = await websockets.connect(self.ws_url)
            self.running = True
            logger.info(f"Binance WebSocket connected: {self.symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect Binance WebSocket: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("Binance WebSocket disconnected")

    async def listen(self, callback: Callable):
        """监听WebSocket消息"""
        self.callback = callback

        while self.running:
            try:
                if not self.ws or self.ws.closed:
                    await self.connect()
                    if not self.ws:
                        await asyncio.sleep(self.reconnect_delay)
                        continue

                message = await asyncio.wait_for(self.ws.recv(), timeout=30)
                self.last_message_time = datetime.now()

                data = json.loads(message)
                if self.callback:
                    await self.callback({
                        "bid_price": float(data.get("b", 0)),
                        "ask_price": float(data.get("a", 0)),
                        "bid_qty": float(data.get("B", 0)),
                        "ask_qty": float(data.get("A", 0)),
                    })

            except asyncio.TimeoutError:
                logger.warning("Binance WebSocket timeout, reconnecting...")
                await self.disconnect()
                await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error(f"Binance WebSocket error: {e}")
                await self.disconnect()
                await asyncio.sleep(self.reconnect_delay)

    def is_healthy(self) -> bool:
        """检查连接健康状态"""
        if not self.last_message_time:
            return False
        return (datetime.now() - self.last_message_time).seconds < 60
```

#### 2.2 集成WebSocket到服务
修改 `realtime_market_service.py`:

```python
from app.services.binance_websocket import BinanceWebSocketClient

class RealTimeMarketDataService:
    def __init__(self):
        # ... 现有代码
        self.binance_ws = BinanceWebSocketClient("xauusdt")
        self.binance_ws_task = None
        self.latest_binance_data = None

    async def start(self):
        # ... 现有代码
        # 启动WebSocket
        if self.has_binance_accounts:
            self.binance_ws_task = asyncio.create_task(
                self.binance_ws.listen(self._on_binance_data)
            )

    async def _on_binance_data(self, data):
        """WebSocket数据回调"""
        self.latest_binance_data = data
        # 存储到数据库
        await self._store_binance_data(data)
```

### 第三阶段：心跳和重连机制

#### 3.1 添加心跳监控
```python
class RealTimeMarketDataService:
    def __init__(self):
        # ... 现有代码
        self.binance_heartbeat_failures = 0
        self.bybit_heartbeat_failures = 0
        self.max_heartbeat_failures = 3

    async def _heartbeat_monitor(self):
        """心跳监控"""
        while self.running:
            await asyncio.sleep(10)  # 每10秒检查一次

            # 检查Binance WebSocket健康状态
            if self.has_binance_accounts:
                if not self.binance_ws.is_healthy():
                    self.binance_heartbeat_failures += 1
                    logger.warning(f"Binance heartbeat failure: {self.binance_heartbeat_failures}")

                    if self.binance_heartbeat_failures >= self.max_heartbeat_failures:
                        logger.error("Binance WebSocket unhealthy, reconnecting...")
                        await self.binance_ws.disconnect()
                        self.binance_heartbeat_failures = 0
                else:
                    self.binance_heartbeat_failures = 0
```

#### 3.2 添加连接状态API
**文件**: `backend/app/api/v1/market.py`

```python
@router.get("/connection/status")
async def get_connection_status():
    """获取连接状态"""
    return {
        "binance": {
            "connected": realtime_service.binance_ws.running,
            "healthy": realtime_service.binance_ws.is_healthy(),
            "heartbeat_failures": realtime_service.binance_heartbeat_failures
        },
        "bybit": {
            "connected": realtime_service.mt5_client.connected,
            "market_open": realtime_service.is_mt5_market_open()
        }
    }
```

### 第四阶段：前端优化

#### 4.1 更新MarketCards.vue
```vue
<template>
  <!-- 添加连接状态指示器 -->
  <div class="connection-status">
    <div v-if="connectionStatus.binance.heartbeat_failures > 0" class="alert">
      ⚠️ Binance连接不稳定，正在重连...
    </div>
  </div>

  <!-- 心跳线显示 -->
  <div class="heartbeat-indicator">
    <div v-for="i in 5" :key="i"
         :class="['beat', i <= heartbeatLevel ? 'active' : '']">
    </div>
  </div>
</template>

<script setup>
// 每200ms更新一次行情（WebSocket推送）
const updateInterval = 200

// 每10秒检查一次连接状态
setInterval(async () => {
  const status = await api.get('/api/v1/market/connection/status')
  connectionStatus.value = status.data
}, 10000)
</script>
```

#### 4.2 优化轮询频率
```javascript
// 行情：200ms (WebSocket推送，前端只需读取)
setInterval(fetchMarketData, 200)

// 持仓：1-2s
setInterval(fetchPositions, 1500)

// 账户余额：3-5s
setInterval(fetchBalance, 4000)
```

### 第五阶段：配置更新

#### 5.1 更新config.py
```python
# 行情更新间隔（WebSocket模式下主要用于REST兜底）
MARKET_DATA_UPDATE_INTERVAL: int = 5  # 从1秒改为5秒

# WebSocket配置
BINANCE_WS_ENABLED: bool = True
BINANCE_WS_RECONNECT_DELAY: int = 5
BINANCE_WS_HEARTBEAT_TIMEOUT: int = 60

# 账户检查间隔
ACCOUNT_CHECK_INTERVAL: int = 60  # 每60秒检查一次账户状态
```

## 实施优先级

### 高优先级（立即实施）
1. ✅ 账户状态检查
2. ✅ MT5市场时间检查
3. ✅ 优化REST API调用频率（5秒）

### 中优先级（本周实施）
4. Binance WebSocket实现
5. 心跳监控机制
6. 前端连接状态显示

### 低优先级（后续优化）
7. WebSocket断线重连优化
8. 多symbol支持
9. 性能监控和日志

## 预期效果

1. **API调用减少90%**：
   - 当前：每秒2次REST调用（Binance + Bybit）
   - 优化后：Binance使用WebSocket，Bybit仅在市场开放时每5秒调用1次

2. **实时性提升**：
   - WebSocket推送延迟 < 100ms
   - REST轮询延迟 1000ms

3. **稳定性提升**：
   - 自动重连机制
   - 心跳监控
   - 账户状态感知

4. **避免rate limit**：
   - Binance: 从每秒1次降至WebSocket推送
   - Bybit: 从每秒1次降至每5秒1次（且仅在市场开放时）

## 风险和注意事项

1. **WebSocket断线风险**：需要完善的重连机制
2. **数据一致性**：WebSocket和REST数据可能存在微小差异
3. **MT5市场时间**：需要考虑夏令时调整
4. **账户状态缓存**：避免频繁查询数据库

## 测试计划

1. 单元测试：WebSocket连接、重连、心跳
2. 集成测试：完整数据流测试
3. 压力测试：长时间运行稳定性
4. 故障测试：网络断开、API限流等场景
