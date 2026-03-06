# 套利策略 V2.0 修正版技术设计文档

## 1. 核心需求变更说明

### 1.1 与原设计的主要差异

**原设计（已废弃）**:
- 持续0.1秒监控市场
- 自动触发执行
- 30秒Binance超时，10秒Bybit超时

**修正版设计（当前）**:
- 手动点击按钮触发
- 基于触发次数控制
- 0.2秒Binance超时，0.1秒Bybit超时
- 明确的撤单重试逻辑

### 1.2 核心概念

1. **触发次数机制**: 点差满足条件时触发一次，再次满足再触发一次，累计触发次数达到配置值后才执行下单
2. **单次下单手数**: 每次执行的最大数量限制
3. **总手数**: 阶梯配置的总数量限制（持仓不得超过此数量）
4. **阶梯顺序执行**: 阶梯1完成后才执行阶梯2

## 2. 点差计算定义

### 2.1 反向套利

**反向开仓**:
- **bybit做多点差值** = `binance_ask - bybit_ask`
- **触发条件**: bybit做多点差值 >= 反向开仓点差值

**反向平仓**:
- **bybit平仓点差值** = `binance_bid - bybit_bid`
- **触发条件**: bybit平仓点差值 <= 反向平仓点差值

### 2.2 正向套利

**正向开仓**:
- **binance做多点差值** = `bybit_bid - binance_bid`
- **触发条件**: binance做多点差值 >= 正向开仓点差值

**正向平仓**:
- **binance平仓点差值** = `bybit_ask - binance_ask`
- **触发条件**: binance平仓点差值 <= 正向平仓点差值

## 3. 反向套利策略详细设计

### 3.1 反向开仓流程

```
用户点击"反向开仓"按钮
    ↓
检查触发次数是否达到配置值
    ↓ (未达到)
等待点差满足条件，每次满足触发次数+1
    ↓ (达到)
检查条件1: 计算本次下单数量
    ↓
检查条件3: 点差是否满足
    ↓
执行双边下单
    ↓
情况1: Binance完全成交 → Bybit市价单
情况2: Binance 0.2秒未完全成交 → 撤单 → Bybit按已成交数量下单
    ↓
检查是否达到阶梯总手数
    ↓ (未达到)
重新检查条件，继续下单
    ↓ (达到)
当前阶梯完成，执行下一阶梯
```

**详细步骤**:

1. **初始化**
   - 用户点击"反向开仓"按钮
   - 系统初始化触发次数计数器 = 0
   - 当前阶梯索引 = 0
   - 当前持仓总数 = 0

2. **触发次数检测循环**
   ```python
   while trigger_count < config.reverse_opening_trigger_times:
       # 计算bybit做多点差值
       spread = binance_ask - bybit_ask

       if spread >= config.reverse_opening_spread:
           trigger_count += 1
           await asyncio.sleep(0.1)  # 防止重复触发
   ```

3. **条件检查**
   - **条件1**: 计算本次下单数量
     ```python
     remaining = ladder.total_qty - current_position
     order_qty = min(config.opening_m_coin, remaining)
     ```

   - **条件3**: 检查点差
     ```python
     spread = binance_ask - bybit_ask
     if spread < config.reverse_opening_spread:
         continue  # 不满足，继续等待
     ```

4. **Binance限价单挂单（开空）**
   ```python
   # Binance卖出（开空）
   binance_order = await binance_api.place_limit_order(
       symbol=symbol,
       side='SELL',
       quantity=order_qty,
       price=binance_bid  # 使用买一价挂单
   )
   ```

5. **Binance订单监控**
   ```python
   # 情况1: 完全成交
   start_time = time.time()
   while time.time() - start_time < 0.2:
       order_status = await binance_api.get_order(binance_order.id)

       if order_status.status == 'FILLED':
           filled_qty = order_status.filled_qty
           break

       await asyncio.sleep(0.01)  # 10ms检测一次
   else:
       # 情况2: 0.2秒未完全成交，撤单
       await binance_api.cancel_order(binance_order.id)
       filled_qty = order_status.filled_qty
   ```

6. **Bybit市价单（开多）**
   ```python
   # Bybit买入（开多）
   bybit_order = await bybit_api.place_market_order(
       symbol=symbol,
       side='BUY',
       quantity=filled_qty
   )
   ```

7. **Bybit订单监控与追单**
   ```python
   await asyncio.sleep(0.1)  # 等待0.1秒

   bybit_status = await bybit_api.get_order(bybit_order.id)
   bybit_filled = bybit_status.filled_qty

   if bybit_filled < filled_qty:
       # 未完全成交，撤单
       await bybit_api.cancel_order(bybit_order.id)

       # 重新下单
       remaining = filled_qty - bybit_filled
       retry_order = await bybit_api.place_market_order(
           symbol=symbol,
           side='BUY',
           quantity=remaining
       )

       # 再次检测（循环一次）
       await asyncio.sleep(0.1)
       retry_status = await bybit_api.get_order(retry_order.id)
       # ... 继续匹配逻辑
   ```

8. **更新持仓并检查是否继续**
   ```python
   current_position += min(binance_filled, bybit_filled)

   if current_position >= ladder.total_qty:
       # 当前阶梯完成，移动到下一阶梯
       current_ladder_index += 1
       current_position = 0

       if current_ladder_index >= len(ladders):
           # 所有阶梯完成
           return

   # 重置触发次数，继续下一轮
   trigger_count = 0
   ```

### 3.2 反向平仓流程

与反向开仓类似，主要差异：

1. **点差计算**: bybit平仓点差值 = `binance_bid - bybit_bid`
2. **触发条件**: bybit平仓点差值 <= 反向平仓点差值
3. **Binance操作**: 买入平仓（使用ask价挂单）
4. **Bybit操作**: 卖出平仓（开空平仓）

```python
# Binance买入平仓
binance_order = await binance_api.place_limit_order(
    symbol=symbol,
    side='BUY',
    quantity=order_qty,
    price=binance_ask
)

# Bybit卖出平仓
bybit_order = await bybit_api.place_market_order(
    symbol=symbol,
    side='SELL',
    quantity=filled_qty,
    reduce_only=True  # 平仓标记
)
```

## 4. 正向套利策略详细设计

### 4.1 正向开仓流程

**点差计算**: binance做多点差值 = `bybit_bid - binance_bid`

**订单操作**:
1. **Binance**: 买入开多（使用ask价挂限价单）
2. **Bybit**: 卖出开空（市价单）

```python
# Binance买入（开多）
binance_order = await binance_api.place_limit_order(
    symbol=symbol,
    side='BUY',
    quantity=order_qty,
    price=binance_ask
)

# Bybit卖出（开空）
bybit_order = await bybit_api.place_market_order(
    symbol=symbol,
    side='SELL',
    quantity=filled_qty
)
```

### 4.2 正向平仓流程

**点差计算**: binance平仓点差值 = `bybit_ask - binance_ask`

**订单操作**:
1. **Binance**: 卖出平仓（使用bid价挂限价单）
2. **Bybit**: 买入平仓（市价单）

```python
# Binance卖出平仓
binance_order = await binance_api.place_limit_order(
    symbol=symbol,
    side='SELL',
    quantity=order_qty,
    price=binance_bid
)

# Bybit买入平仓
bybit_order = await bybit_api.place_market_order(
    symbol=symbol,
    side='BUY',
    quantity=filled_qty,
    reduce_only=True
)
```

## 5. 核心类设计

### 5.1 触发次数管理器

```python
class TriggerCountManager:
    def __init__(self, strategy_id: int, action: str):
        self.strategy_id = strategy_id
        self.action = action  # 'reverse_opening', 'reverse_closing', etc.
        self.count = 0
        self.last_trigger_time = None

    async def check_and_increment(self, current_spread: float, threshold: float,
                                   compare_op: str) -> bool:
        """检查点差并增加触发次数"""
        # 防止短时间内重复触发
        if self.last_trigger_time:
            if time.time() - self.last_trigger_time < 0.1:
                return False

        # 检查点差条件
        if compare_op == '>=':
            triggered = current_spread >= threshold
        else:  # '<='
            triggered = current_spread <= threshold

        if triggered:
            self.count += 1
            self.last_trigger_time = time.time()
            return True

        return False

    def reset(self):
        """重置触发次数"""
        self.count = 0
        self.last_trigger_time = None

    def is_ready(self, required_count: int) -> bool:
        """检查是否达到所需触发次数"""
        return self.count >= required_count
```

### 5.2 订单执行器（修正版）

```python
class OrderExecutorRevised:
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.binance_timeout = 0.2  # 200ms
        self.bybit_timeout = 0.1    # 100ms

    async def execute_reverse_opening(self, order_qty: float) -> dict:
        """执行反向开仓"""
        # 1. Binance限价卖单（开空）
        binance_order = await self._place_binance_limit_sell(order_qty)

        # 2. 监控Binance订单
        binance_filled = await self._monitor_binance_order(
            binance_order.id,
            self.binance_timeout
        )

        if binance_filled == 0:
            return {'success': False, 'reason': 'binance_no_fill'}

        # 3. Bybit市价买单（开多）
        bybit_filled = await self._execute_bybit_market_buy(binance_filled)

        return {
            'success': True,
            'binance_filled': binance_filled,
            'bybit_filled': bybit_filled
        }

    async def _monitor_binance_order(self, order_id: str, timeout: float) -> float:
        """监控Binance订单"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            order = await binance_api.get_order(order_id)

            if order.status == 'FILLED':
                return order.filled_qty

            await asyncio.sleep(0.01)  # 10ms检测间隔

        # 超时，撤单
        await binance_api.cancel_order(order_id)
        order = await binance_api.get_order(order_id)
        return order.filled_qty

    async def _execute_bybit_market_buy(self, target_qty: float) -> float:
        """执行Bybit市价买单，带重试逻辑"""
        total_filled = 0
        remaining = target_qty
        max_retries = 2  # 最多重试1次（循环此流程一次）

        for attempt in range(max_retries):
            # 下市价单
            order = await bybit_api.place_market_order(
                symbol=self.config.symbol,
                side='BUY',
                quantity=remaining
            )

            # 等待0.1秒
            await asyncio.sleep(self.bybit_timeout)

            # 检查成交情况
            order_status = await bybit_api.get_order(order.id)
            filled = order_status.filled_qty
            total_filled += filled

            if filled >= remaining:
                # 完全成交
                break

            # 未完全成交，撤单
            await bybit_api.cancel_order(order.id)
            remaining -= filled

            if attempt == max_retries - 1:
                # 最后一次尝试
                logger.warning(f"Bybit未完全成交，差额: {remaining}")

        return total_filled
```

### 5.3 策略执行器

```python
class ArbitrageStrategyExecutor:
    def __init__(self, strategy_id: int, config: StrategyConfig):
        self.strategy_id = strategy_id
        self.config = config
        self.order_executor = OrderExecutorRevised(config)
        self.trigger_manager = None
        self.current_ladder_index = 0
        self.current_position = 0
        self.is_running = False

    async def start_reverse_opening(self):
        """启动反向开仓策略"""
        self.is_running = True
        self.current_ladder_index = 0
        self.current_position = 0

        while self.is_running and self.current_ladder_index < len(self.config.ladders):
            ladder = self.config.ladders[self.current_ladder_index]

            # 执行当前阶梯
            success = await self._execute_ladder_reverse_opening(ladder)

            if success:
                # 阶梯完成，移动到下一阶梯
                self.current_ladder_index += 1
                self.current_position = 0
            else:
                # 执行失败，停止
                break

        self.is_running = False

    async def _execute_ladder_reverse_opening(self, ladder: Ladder) -> bool:
        """执行单个阶梯的反向开仓"""
        # 初始化触发管理器
        self.trigger_manager = TriggerCountManager(
            self.strategy_id,
            'reverse_opening'
        )

        while self.current_position < ladder.total_qty:
            # 步骤1: 等待触发次数达标
            await self._wait_for_triggers(
                required_count=self.config.reverse_opening_trigger_times,
                spread_calculator=lambda: self._calc_bybit_long_spread(),
                threshold=ladder.opening_spread,
                compare_op='>='
            )

            # 步骤2: 计算本次下单数量（条件1）
            remaining = ladder.total_qty - self.current_position
            order_qty = min(self.config.opening_m_coin, remaining)

            # 步骤3: 检查点差（条件3）
            current_spread = await self._calc_bybit_long_spread()
            if current_spread < ladder.opening_spread:
                # 点差不满足，重置触发次数
                self.trigger_manager.reset()
                continue

            # 步骤4: 执行双边下单
            result = await self.order_executor.execute_reverse_opening(order_qty)

            if result['success']:
                # 更新持仓
                filled = min(result['binance_filled'], result['bybit_filled'])
                self.current_position += filled

                # 重置触发次数，准备下一轮
                self.trigger_manager.reset()
            else:
                # 执行失败
                logger.error(f"反向开仓执行失败: {result}")
                return False

        return True

    async def _wait_for_triggers(self, required_count: int,
                                  spread_calculator, threshold: float,
                                  compare_op: str):
        """等待触发次数达标"""
        while not self.trigger_manager.is_ready(required_count):
            # 计算当前点差
            current_spread = await spread_calculator()

            # 检查并增加触发次数
            await self.trigger_manager.check_and_increment(
                current_spread, threshold, compare_op
            )

            # 短暂等待
            await asyncio.sleep(0.05)

    async def _calc_bybit_long_spread(self) -> float:
        """计算bybit做多点差值"""
        binance_book = await binance_api.get_orderbook(self.config.symbol)
        bybit_book = await bybit_api.get_orderbook(self.config.symbol)

        return binance_book.ask - bybit_book.ask

    async def _calc_bybit_close_spread(self) -> float:
        """计算bybit平仓点差值"""
        binance_book = await binance_api.get_orderbook(self.config.symbol)
        bybit_book = await bybit_api.get_orderbook(self.config.symbol)

        return binance_book.bid - bybit_book.bid

    async def _calc_binance_long_spread(self) -> float:
        """计算binance做多点差值"""
        binance_book = await binance_api.get_orderbook(self.config.symbol)
        bybit_book = await bybit_api.get_orderbook(self.config.symbol)

        return bybit_book.bid - binance_book.bid

    async def _calc_binance_close_spread(self) -> float:
        """计算binance平仓点差值"""
        binance_book = await binance_api.get_orderbook(self.config.symbol)
        bybit_book = await bybit_api.get_orderbook(self.config.symbol)

        return bybit_book.ask - binance_book.ask
```

## 6. 数据库设计

### 6.1 新增字段到 strategy_configs

```sql
-- 触发次数配置
ALTER TABLE strategy_configs ADD COLUMN reverse_opening_trigger_times INTEGER DEFAULT 1;
ALTER TABLE strategy_configs ADD COLUMN reverse_closing_trigger_times INTEGER DEFAULT 1;
ALTER TABLE strategy_configs ADD COLUMN forward_opening_trigger_times INTEGER DEFAULT 1;
ALTER TABLE strategy_configs ADD COLUMN forward_closing_trigger_times INTEGER DEFAULT 1;

-- 超时配置
ALTER TABLE strategy_configs ADD COLUMN binance_order_timeout FLOAT DEFAULT 0.2;
ALTER TABLE strategy_configs ADD COLUMN bybit_order_timeout FLOAT DEFAULT 0.1;
```

### 6.2 执行状态表

```sql
CREATE TABLE strategy_execution_state (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL UNIQUE,
    strategy_type VARCHAR(20) NOT NULL,  -- 'reverse' or 'forward'
    action VARCHAR(20) NOT NULL,  -- 'opening' or 'closing'
    is_running BOOLEAN DEFAULT FALSE,
    current_ladder_index INTEGER DEFAULT 0,
    current_position FLOAT DEFAULT 0,
    trigger_count INTEGER DEFAULT 0,
    last_trigger_time TIMESTAMP,
    started_at TIMESTAMP,
    stopped_at TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategy_configs(id) ON DELETE CASCADE
);
```

### 6.3 订单记录表

```sql
CREATE TABLE arbitrage_orders (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL,
    ladder_index INTEGER NOT NULL,
    action VARCHAR(20) NOT NULL,
    binance_order_id VARCHAR(100),
    binance_side VARCHAR(10),
    binance_qty FLOAT,
    binance_filled_qty FLOAT,
    binance_status VARCHAR(20),
    bybit_order_id VARCHAR(100),
    bybit_side VARCHAR(10),
    bybit_qty FLOAT,
    bybit_filled_qty FLOAT,
    bybit_status VARCHAR(20),
    spread_at_execution FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategy_configs(id) ON DELETE CASCADE
);
```

## 7. API 接口设计

### 7.1 策略控制接口

```python
# 启动反向开仓
POST /api/v1/strategies/{strategy_id}/reverse/opening/start

# 停止反向开仓
POST /api/v1/strategies/{strategy_id}/reverse/opening/stop

# 启动反向平仓
POST /api/v1/strategies/{strategy_id}/reverse/closing/start

# 停止反向平仓
POST /api/v1/strategies/{strategy_id}/reverse/closing/stop

# 启动正向开仓
POST /api/v1/strategies/{strategy_id}/forward/opening/start

# 停止正向开仓
POST /api/v1/strategies/{strategy_id}/forward/opening/stop

# 启动正向平仓
POST /api/v1/strategies/{strategy_id}/forward/closing/start

# 停止正向平仓
POST /api/v1/strategies/{strategy_id}/forward/closing/stop
```

### 7.2 状态查询接口

```python
# 获取执行状态
GET /api/v1/strategies/{strategy_id}/execution/state
Response: {
    "is_running": true,
    "strategy_type": "reverse",
    "action": "opening",
    "current_ladder_index": 1,
    "current_position": 15.5,
    "trigger_count": 2,
    "last_trigger_time": "2026-03-01T10:30:00Z"
}

# 获取订单历史
GET /api/v1/strategies/{strategy_id}/orders
Response: {
    "orders": [
        {
            "id": 1,
            "ladder_index": 0,
            "action": "reverse_opening",
            "binance_filled_qty": 5.0,
            "bybit_filled_qty": 5.0,
            "spread_at_execution": 12.5,
            "created_at": "2026-03-01T10:25:00Z"
        }
    ]
}
```

## 8. 前端修改

### 8.1 StrategyPanel.vue 修改

```javascript
// 新增状态
const executionState = ref({
  isRunning: false,
  strategyType: '',  // 'reverse' or 'forward'
  action: '',  // 'opening' or 'closing'
  currentLadderIndex: 0,
  currentPosition: 0,
  triggerCount: 0,
  lastTriggerTime: null
})

// 启动反向开仓
async function startReverseOpening() {
  const response = await fetch(`/api/v1/strategies/${strategyId}/reverse/opening/start`, {
    method: 'POST'
  })
  const data = await response.json()
  if (data.success) {
    executionState.value.isRunning = true
    executionState.value.strategyType = 'reverse'
    executionState.value.action = 'opening'
  }
}

// 停止策略
async function stopStrategy() {
  const { strategyType, action } = executionState.value
  const response = await fetch(
    `/api/v1/strategies/${strategyId}/${strategyType}/${action}/stop`,
    { method: 'POST' }
  )
  const data = await response.json()
  if (data.success) {
    executionState.value.isRunning = false
  }
}
```

### 8.2 UI 组件

```vue
<template>
  <div class="strategy-panel">
    <!-- 反向套利 -->
    <div class="reverse-strategy">
      <h3>反向套利策略</h3>

      <div class="controls">
        <el-button
          type="primary"
          @click="startReverseOpening"
          :disabled="executionState.isRunning"
        >
          反向开仓
        </el-button>

        <el-button
          type="warning"
          @click="startReverseClosing"
          :disabled="executionState.isRunning"
        >
          反向平仓
        </el-button>

        <el-button
          type="danger"
          @click="stopStrategy"
          :disabled="!executionState.isRunning"
        >
          停止
        </el-button>
      </div>

      <div class="status" v-if="executionState.isRunning">
        <p>当前阶梯: {{ executionState.currentLadderIndex + 1 }}</p>
        <p>当前持仓: {{ executionState.currentPosition }}</p>
        <p>触发次数: {{ executionState.triggerCount }}</p>
      </div>
    </div>

    <!-- 正向套利 -->
    <div class="forward-strategy">
      <h3>正向套利策略</h3>

      <div class="controls">
        <el-button
          type="primary"
          @click="startForwardOpening"
          :disabled="executionState.isRunning"
        >
          正向开仓
        </el-button>

        <el-button
          type="warning"
          @click="startForwardClosing"
          :disabled="executionState.isRunning"
        >
          正向平仓
        </el-button>
      </div>
    </div>
  </div>
</template>
```

## 9. 实施计划

### Phase 1: 基础架构 (2-3天)
- [ ] 创建/修改数据库表
- [ ] 实现 TriggerCountManager 类
- [ ] 实现基础 API 接口

### Phase 2: 订单执行器 (3-4天)
- [ ] 实现 OrderExecutorRevised 类
- [ ] 实现 Binance 0.2秒超时逻辑
- [ ] 实现 Bybit 0.1秒超时和重试逻辑
- [ ] 单元测试

### Phase 3: 策略执行器 (3-4天)
- [ ] 实现 ArbitrageStrategyExecutor 类
- [ ] 实现触发次数等待逻辑
- [ ] 实现阶梯顺序执行
- [ ] 集成测试

### Phase 4: 前端集成 (2-3天)
- [ ] 修改 StrategyPanel.vue
- [ ] 添加四个按钮（反向开仓/平仓，正向开仓/平仓）
- [ ] 实现状态显示
- [ ] UI测试

### Phase 5: 测试和优化 (2-3天)
- [ ] 完整流程测试
- [ ] 边界情况测试
- [ ] 性能优化
- [ ] 文档完善

**总计**: 约 12-17 天

---

**文档版本**: 2.0 (修正版)
**创建日期**: 2026-03-01
**最后更新**: 2026-03-01
