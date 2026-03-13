# Binance账号挂单逻辑汇总

## 概览

| 策略 | Binance操作 | 订单类型 | 价格设置 | 监控次数 | 撤单条件 |
|------|------------|---------|---------|---------|---------|
| 正向开仓 | 买入开多 | **市价单** | 市价 | 4次 | 点差不满足 |
| 反向开仓 | 卖出开空 | **市价单** | 市价 | 4次 | 点差不满足 |
| 反向平仓 | 卖出平空 | **限价单** | bid价 | 4次 | 点差不满足 |
| 正向平仓 | 买入平多 | **限价单** | ask价 | 4次 | 点差不满足 |

---

## 1. 正向开仓策略（Forward Opening）

### Binance操作
- **方向**: BUY（买入开多）
- **订单类型**: **市价单**（Market Order）
- **代码位置**: `strategy_executor_v3.py:524-528`

```python
binance_order = await self.order_executor.place_binance_market_order(
    config.symbol,
    "BUY",
    order_qty
)
```

### 监控逻辑
- **监控次数**: 最多4次（`max_bybit_retries = 4`）
- **检查间隔**: `self.normal_check_interval`（10ms）
- **总监控时间**: 约40ms

### 三种场景处理

#### 场景1：Binance未成交（filled_qty == 0）
- 检查当前点差是否满足
- 如果点差不满足：撤单并返回失败
- 等待时间：`self.open_wait_after_cancel_no_trade`秒

#### 场景2：Binance完全成交（status == 'FILLED'）
- 立即执行Bybit订单
- 使用混合方案（激进限价单+市价单兜底）

#### 场景3：Binance部分成交（0 < filled_qty < order_qty）
- 检查当前点差是否满足
- 如果点差不满足：撤单并执行Bybit订单（按已成交量）
- 等待时间：`self.open_wait_after_cancel_part`秒

---

## 2. 反向开仓策略（Reverse Opening）

### Binance操作
- **方向**: SELL（卖出开空）
- **订单类型**: **市价单**（Market Order）
- **代码位置**: `strategy_executor_v3.py:1012-1016`

```python
binance_order = await self.order_executor.place_binance_market_order(
    config.symbol,
    "SELL",
    order_qty
)
```

### 监控逻辑
- **监控次数**: 最多4次（`max_bybit_retries = 4`）
- **检查间隔**: `self.normal_check_interval`（10ms）
- **总监控时间**: 约40ms

### 三种场景处理
与正向开仓相同，只是方向相反。

---

## 3. 反向平仓策略（Reverse Closing）

### Binance操作
- **方向**: SELL（卖出平空）
- **订单类型**: **限价单**（Limit Order）
- **价格设置**: **bid价**（买方报价）
- **代码位置**: `strategy_executor_v3.py:1482-1487`

```python
binance_order = await self.order_executor.place_binance_limit_order(
    config.symbol,
    "SELL",
    order_qty,
    "bid"  # 使用bid价作为限价
)
```

### 价格逻辑
- **bid价**: 买方愿意支付的价格（较低）
- **卖出使用bid价**: 激进价格，容易成交
- **优点**: 比市价单更优的价格
- **缺点**: 如果市场波动，可能不成交

### 监控逻辑
- **监控次数**: 最多4次（`max_bybit_retries = 4`）
- **检查间隔**: `self.normal_check_interval`（10ms）
- **总监控时间**: 约40ms

### 三种场景处理

#### 场景1：Binance未成交（filled_qty == 0）
- 检查当前点差是否满足
- 如果点差不满足：撤单并返回失败
- 等待时间：`self.close_wait_after_cancel_no_trade`秒

#### 场景2：Binance完全成交（status == 'FILLED'）
- 立即执行Bybit订单
- 使用混合方案（激进限价单+市价单兜底）

#### 场景3：Binance部分成交（0 < filled_qty < order_qty）
- 检查当前点差是否满足
- 如果点差不满足：撤单并执行Bybit订单（按已成交量）
- 等待时间：`self.close_wait_after_cancel_part`秒

---

## 4. 正向平仓策略（Forward Closing）

### Binance操作
- **方向**: BUY（买入平多）
- **订单类型**: **限价单**（Limit Order）
- **价格设置**: **ask价**（卖方报价）
- **代码位置**: `strategy_executor_v3.py:1906-1911`

```python
binance_order = await self.order_executor.place_binance_limit_order(
    config.symbol,
    "BUY",
    order_qty,
    "ask"  # 使用ask价作为限价
)
```

### 价格逻辑
- **ask价**: 卖方要求的价格（较高）
- **买入使用ask价**: 激进价格，容易成交
- **优点**: 比市价单更优的价格
- **缺点**: 如果市场波动，可能不成交

### 监控逻辑
- **监控次数**: 最多4次（`max_bybit_retries = 4`）
- **检查间隔**: `self.normal_check_interval`（10ms）
- **总监控时间**: 约40ms

### 三种场景处理
与反向平仓相同，只是方向相反。

---

## 问题分析

### 当前问题：频繁挂单撤单

**症状**: 正向平仓时，Binance账号频繁撤单然后再次挂单

**根本原因**:
1. **限价单可能不成交**: 使用ask价的限价单，如果市场价格波动，可能长时间不成交
2. **监控时间太短**: 只监控4次×10ms=40ms，限价单可能需要更长时间成交
3. **点差检查频繁**: 每10ms检查一次点差，如果点差不满足立即撤单
4. **触发次数重置**: 撤单后触发次数重置，如果点差很快又满足，立即重新下单

### 对比：开仓策略为什么不频繁撤单？

**开仓策略使用市价单**:
- 市价单立即成交，不存在"挂单等待"的问题
- 即使监控时间短（40ms），市价单也能在这段时间内成交
- 不会出现频繁撤单重挂的情况

**平仓策略使用限价单**:
- 限价单需要等待市场价格触及限价才能成交
- 40ms的监控时间太短，限价单可能还没成交就被撤单
- 撤单后重新下单，形成频繁挂单撤单循环

---

## 解决方案建议

### 方案1：平仓策略也使用混合方案（推荐）

**Binance也采用混合方案**:
1. 先下激进限价单（bid/ask价）
2. 等待0.5秒检查是否成交
3. 如果不成交，撤单改用市价单兜底

**优点**:
- 既能获得限价单的价格优势
- 又能保证市价单的成交率
- 避免频繁撤单重挂

### 方案2：延长监控时间

**增加监控次数和间隔**:
- 监控次数：从4次增加到10次
- 检查间隔：从10ms增加到100ms
- 总监控时间：从40ms增加到1秒

**优点**:
- 给限价单更多时间成交
- 减少不必要的撤单

**缺点**:
- 如果限价单一直不成交，会浪费时间

### 方案3：动态调整限价

**根据市场情况动态调整限价**:
- 如果限价单不成交，调整价格为更激进的限价
- 例如：bid价 → bid价+0.01 → bid价+0.02

**优点**:
- 逐步提高成交概率
- 仍然比市价单更优的价格

**缺点**:
- 实现复杂度较高

---

## 推荐方案

**建议采用方案1：Binance也使用混合方案**

理由：
1. **统一逻辑**: Binance和Bybit都使用混合方案，代码逻辑一致
2. **最优平衡**: 既优化价格又保证成交
3. **避免频繁撤单**: 0.5秒等待时间足够限价单成交，如果不成交直接市价单兜底
4. **已验证**: Bybit混合方案已经实现并验证有效

实现步骤：
1. 修改`place_binance_limit_order`为混合方案
2. 先下激进限价单（IOC时效）
3. 等待0.5秒检查成交情况
4. 如果不成交，撤单改用市价单
