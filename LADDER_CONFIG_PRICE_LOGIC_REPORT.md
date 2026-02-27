# 阶梯配置开仓价和平仓价获取逻辑分析报告

**生成时间**: 2026-02-27
**系统**: Hustle XAU 套利交易系统
**分析范围**: 阶梯配置的开仓价和平仓价获取逻辑

---

## 一、阶梯配置数据结构

### 1.1 数据库模型 (backend/app/models/strategy.py)

```python
class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    config_id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    strategy_type = Column(String(20))  # forward, reverse
    target_spread = Column(Float)       # 目标点差（开仓条件）
    order_qty = Column(Float)           # 订单数量
    retry_times = Column(Integer)       # 追单重试次数
    mt5_stuck_threshold = Column(Integer)
    opening_sync_count = Column(Integer)
    closing_sync_count = Column(Integer)
    m_coin = Column(Float)              # 每批最大手数
    ladders = Column(JSONB)             # 阶梯配置数组
    is_enabled = Column(Boolean)
```

### 1.2 Schema 定义 (backend/app/schemas/strategy.py)

```python
class LadderConfig(BaseModel):
    enabled: bool = True
    openPrice: float = Field(default=3.0, ge=0)    # 开仓价
    threshold: float = Field(default=2.0, ge=0)    # 阈值
    qtyLimit: float = Field(default=3.0, gt=0)     # 数量限制
```

**默认配置**:
- 阶梯1: enabled=True, openPrice=3.0, threshold=2.0, qtyLimit=3.0
- 阶梯2: enabled=True, openPrice=3.0, threshold=3.0, qtyLimit=3.0
- 阶梯3: enabled=False, openPrice=3.0, threshold=4.0, qtyLimit=3.0

---

## 二、开仓价获取逻辑分析

### 2.1 正向套利 (Forward Arbitrage)

**文件**: `backend/app/services/strategy_forward.py`

#### 开仓逻辑 (execute_entry)
```python
# 入场条件: bybit_ask - binance_bid >= target_spread
# 执行价格:
binance_buy_price = binance_bid + 0.01   # Binance买入价 = 买一价 + 0.01
bybit_sell_price = bybit_ask - 0.01      # Bybit卖出价 = 卖一价 - 0.01
```

**价格来源**:
- `binance_bid`: 从 `spread_data.binance_quote.bid_price` 获取
- `bybit_ask`: 从 `spread_data.bybit_quote.ask_price` 获取

#### 平仓逻辑 (execute_exit)
```python
# 退出条件: binance_ask - bybit_bid <= 0
# 执行价格:
binance_sell_price = binance_ask - 0.01  # Binance卖出价 = 卖一价 - 0.01
bybit_buy_price = bybit_bid + 0.01       # Bybit买入价 = 买一价 + 0.01
```

**价格来源**:
- `binance_ask`: 从 `spread_data.binance_quote.ask_price` 获取
- `bybit_bid`: 从 `spread_data.bybit_quote.bid_price` 获取

### 2.2 反向套利 (Reverse Arbitrage)

**文件**: `backend/app/services/strategy_reverse.py`

#### 开仓逻辑 (execute_entry)
```python
# 入场条件: binance_ask - bybit_bid <= -target_spread (负点差)
# 执行价格:
binance_sell_price = binance_ask - 0.01  # Binance卖出价 = 卖一价 - 0.01
bybit_buy_price = bybit_bid + 0.01       # Bybit买入价 = 买一价 + 0.01
```

**价格来源**:
- `binance_ask`: 从 `spread_data.binance_quote.ask_price` 获取
- `bybit_bid`: 从 `spread_data.bybit_quote.bid_price` 获取

#### 平仓逻辑 (execute_exit)
```python
# 退出条件: bybit_ask - binance_bid <= 0
# 执行价格:
binance_buy_price = binance_bid + 0.01   # Binance买入价 = 买一价 + 0.01
bybit_sell_price = bybit_ask - 0.01      # Bybit卖出价 = 卖一价 - 0.01
```

**价格来源**:
- `binance_bid`: 从 `spread_data.binance_quote.bid_price` 获取
- `bybit_ask`: 从 `spread_data.bybit_quote.ask_price` 获取

### 2.3 统一套利服务 (Arbitrage Strategy Service)

**文件**: `backend/app/services/arbitrage_strategy.py`

#### 正向套利开仓 (execute_forward_arbitrage)
```python
# 价格计算 (带精度处理)
binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

**⚠️ 注意**: 这里使用的是 `ask_price - 0.01` 而不是 `bid_price + 0.01`

#### 正向套利平仓 (close_forward_arbitrage)
```python
# 价格计算
binance_sell_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

#### 反向套利开仓 (execute_reverse_arbitrage)
```python
# 价格计算
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

**⚠️ 注意**: Bybit买入使用 `ask_price - 0.01` 而不是 `bid_price + 0.01`

#### 反向套利平仓 (close_reverse_arbitrage)
```python
# 价格计算
binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

---

## 三、阶梯订单服务分析

**文件**: `backend/app/services/ladder_order.py`

### 3.1 阶梯订单执行逻辑

```python
async def execute_ladder_orders(
    task_id, symbol, total_quantity, num_orders,
    price_range, direction, binance_account_id,
    bybit_account_id, db
):
    # 获取当前市场价格
    market_data = await self.market_service.get_market_data(symbol)

    # 计算基准价格
    if direction == "forward":
        base_price = market_data.get("binance_bid", 0)  # 使用Binance买一价
    else:
        base_price = market_data.get("binance_ask", 0)  # 使用Binance卖一价

    # 计算价格步长
    price_step = (base_price * price_range / 100) / (num_orders - 1)

    # 计算每个阶梯的目标价格
    for i in range(num_orders):
        if direction == "forward":
            # 正向: 在更低的价格买入
            target_price = base_price - (price_step * i)
        else:
            # 反向: 在更高的价格卖出
            target_price = base_price + (price_step * i)
```

### 3.2 阶梯订单价格分布

**正向套利阶梯**:
- 基准价: Binance买一价 (bid)
- 阶梯1: base_price - 0 * step
- 阶梯2: base_price - 1 * step
- 阶梯3: base_price - 2 * step
- ...

**反向套利阶梯**:
- 基准价: Binance卖一价 (ask)
- 阶梯1: base_price + 0 * step
- 阶梯2: base_price + 1 * step
- 阶梯3: base_price + 2 * step
- ...

---

## 四、前端配置界面分析

**文件**: `frontend/src/views/Strategies.vue`

### 4.1 阶梯配置显示

```vue
<div v-for=\"(ladder, index) in strategy.ladders\" :key=\"index\">
  <span>梯度{{ index + 1 }}: {{ ladder.enabled ? '启用' : '禁用' }}</span>
  <span>
    开仓价: {{ ladder.open_price }} USDT |
    阈值: {{ ladder.threshold }} |
    数量: {{ ladder.qty_limit }}
  </span>
</div>
```

### 4.2 数据映射问题

**⚠️ 发现问题**: 前端表单数据到后端的映射存在混淆

```javascript
const configData = {
  strategy_type: strategyForm.value.type,
  target_spread: strategyForm.value.ladders[0]?.open_price || 2650,  // ❌ 错误映射
  order_qty: strategyForm.value.ladders[0]?.qty_limit || 0.1,
  retry_times: Math.floor(strategyForm.value.ladders[0]?.threshold || 2),  // ❌ 错误映射
  mt5_stuck_threshold: 5,
  is_enabled: strategyForm.value.opening_enabled
}
```

**问题说明**:
1. `open_price` 被映射到 `target_spread` (目标点差)
2. `threshold` 被映射到 `retry_times` (重试次数)
3. 这导致前端显示的"开仓价"实际上是"目标点差"
4. 前端显示的"阈值"实际上是"重试次数"

---

## 五、关键问题总结

### 5.1 价格获取逻辑不一致

**问题1**: `strategy_forward.py` vs `arbitrage_strategy.py` 价格计算不一致

| 策略类型 | strategy_forward.py | arbitrage_strategy.py |
|---------|---------------------|----------------------|
| 正向开仓-Binance | bid + 0.01 | ask - 0.01 ❌ |
| 正向开仓-Bybit | ask - 0.01 | bid + 0.01 ❌ |

**问题2**: `strategy_reverse.py` vs `arbitrage_strategy.py` 价格计算不一致

| 策略类型 | strategy_reverse.py | arbitrage_strategy.py |
|---------|---------------------|----------------------|
| 反向开仓-Bybit | bid + 0.01 | ask - 0.01 ❌ |

### 5.2 阶梯配置字段语义混淆

**当前状态**:
- `openPrice`: 实际存储的是 `target_spread` (目标点差)
- `threshold`: 实际存储的是 `retry_times` (重试次数)
- `qtyLimit`: 实际存储的是 `order_qty` (订单数量)

**应该是**:
- `openPrice`: 应该是开仓时的价格参考值或价格偏移量
- `threshold`: 应该是触发阈值或点差阈值
- `qtyLimit`: 订单数量限制 ✓ (这个是正确的)

### 5.3 阶梯订单服务未被使用

**发现**: `ladder_order.py` 中的阶梯订单服务已实现，但在实际策略执行中未被调用。当前策略执行使用的是 `arbitrage_strategy.py` 中的简单双边订单逻辑。

### 5.4 MT5 限价单规则遵守情况

**正确的MT5规则**:
- BUY limit: 价格必须 **低于** 当前ask价
- SELL limit: 价格必须 **高于** 当前bid价

**当前实现检查**:

✅ **strategy_forward.py** (正确):
- 开仓买入: `bid + 0.01` (低于ask) ✓
- 开仓卖出: `ask - 0.01` (高于bid) ✓

❌ **arbitrage_strategy.py** (部分错误):
- 正向开仓买入: `ask - 0.01` (可能等于或高于ask) ❌
- 正向开仓卖出: `bid + 0.01` (可能等于或低于bid) ❌

---

## 六、建议修复方案

### 6.1 统一价格计算逻辑

**建议**: 以 `strategy_forward.py` 和 `strategy_reverse.py` 的逻辑为准，修复 `arbitrage_strategy.py`

```python
# 正向套利开仓 (修复后)
binance_buy_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)

# 反向套利开仓 (修复后)
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

### 6.2 修正前端字段映射

**建议**: 重新设计阶梯配置的字段语义

```javascript
// 方案1: 修改前端字段名称
{
  enabled: true,
  targetSpread: 3.0,      // 目标点差 (原 open_price)
  retryTimes: 2,          // 重试次数 (原 threshold)
  orderQty: 3.0           // 订单数量 (原 qty_limit)
}

// 方案2: 修改后端映射逻辑
const configData = {
  target_spread: strategyForm.value.target_spread,  // 使用独立字段
  order_qty: strategyForm.value.order_qty,
  retry_times: strategyForm.value.retry_times,
  ladders: strategyForm.value.ladders  // 保持阶梯配置独立
}
```

### 6.3 启用阶梯订单服务

**建议**: 在策略执行时集成 `ladder_order_service`

```python
# 在 arbitrage_strategy.py 中
if config.ladders and len(config.ladders) > 1:
    # 使用阶梯订单服务
    result = await ladder_order_service.execute_ladder_orders(
        task_id=task.task_id,
        symbol=symbol,
        total_quantity=total_qty,
        num_orders=len(config.ladders),
        price_range=config.price_range,
        direction=direction,
        binance_account_id=binance_account.account_id,
        bybit_account_id=bybit_account.account_id,
        db=db
    )
else:
    # 使用简单双边订单
    result = await order_executor.execute_dual_order(...)
```

### 6.4 添加价格验证

**建议**: 在订单执行前验证价格是否符合MT5规则

```python
def validate_limit_price(side: str, limit_price: float, current_bid: float, current_ask: float) -> bool:
    \"\"\"验证限价单价格是否符合MT5规则\"\"\"
    if side == "BUY":
        # 买入限价必须低于当前卖一价
        return limit_price < current_ask
    elif side == "SELL":
        # 卖出限价必须高于当前买一价
        return limit_price > current_bid
    return False
```

---

## 七、风险评估

### 7.1 高风险问题

1. **价格计算不一致**: 可能导致订单被拒绝或以不利价格成交
2. **MT5规则违反**: 可能导致订单失败，返回 retcode=10015 错误
3. **字段语义混淆**: 用户配置的"开仓价"实际上是"目标点差"，可能导致误操作

### 7.2 中风险问题

1. **阶梯订单未启用**: 无法实现分批建仓的风险控制
2. **缺少价格验证**: 没有在订单提交前验证价格合理性

### 7.3 低风险问题

1. **前端显示不直观**: 字段名称与实际含义不符，影响用户体验

---

## 八、优先级建议

### P0 (立即修复)
1. 修复 `arbitrage_strategy.py` 中的价格计算逻辑
2. 添加MT5限价单规则验证

### P1 (近期修复)
1. 统一前后端字段语义
2. 修正前端数据映射逻辑

### P2 (中期优化)
1. 启用阶梯订单服务
2. 完善阶梯配置功能

---

## 九、测试建议

### 9.1 单元测试
- 测试各种市场价格下的订单价格计算
- 测试MT5规则验证函数

### 9.2 集成测试
- 测试正向套利完整流程（开仓+平仓）
- 测试反向套利完整流程（开仓+平仓）
- 测试阶梯订单执行

### 9.3 回归测试
- 验证修复后不影响现有功能
- 验证MT5订单成功率提升

---

**报告结束**
