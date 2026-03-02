# 订单策略优化修改报告

## 修改日期
2026-03-02

## 修改目标
将所有策略的订单方式改为纯Maker模式，去掉价格调整和追单机制，以降低交易成本。

---

## 修改摘要

### 修改前
- **订单类型**：LIMIT（初始）+ MARKET（追单）
- **价格策略**：市场价格 ± 0.01
- **追单机制**：3秒后检查，最多重试3次
- **手续费**：混合（Maker 0.02% + Taker 0.04%）

### 修改后
- **订单类型**：纯LIMIT（Maker）
- **价格策略**：直接使用市场价格（bid/ask）
- **追单机制**：已移除
- **手续费**：纯Maker（0.02%）

---

## 详细修改内容

### 1. strategy_forward.py（正向套利策略）

#### 1.1 开仓价格修改

**修改前**：
```python
binance_buy_price = binance_bid + 0.01
bybit_sell_price = bybit_ask - 0.01
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_buy_price = binance_bid
bybit_sell_price = bybit_ask
```

#### 1.2 平仓价格修改

**修改前**：
```python
binance_sell_price = binance_ask - 0.01
bybit_buy_price = bybit_bid + 0.01
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_sell_price = binance_ask
bybit_buy_price = bybit_bid
```

---

### 2. strategy_reverse.py（反向套利策略）

#### 2.1 开仓价格修改

**修改前**：
```python
binance_sell_price = binance_ask - 0.01
bybit_buy_price = bybit_bid + 0.01
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_sell_price = binance_ask
bybit_buy_price = bybit_bid
```

#### 2.2 平仓价格修改

**修改前**：
```python
binance_buy_price = binance_bid + 0.01
bybit_sell_price = bybit_ask - 0.01
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_buy_price = binance_bid
bybit_sell_price = bybit_ask
```

---

### 3. arbitrage_strategy.py（套利策略服务）

#### 3.1 正向开仓价格修改

**修改前**：
```python
# Calculate order prices (adjust by 0.01 for better fill rate, with precision handling)
# MT5 limit order rules:
# - BUY limit: price must be BELOW current ask
# - SELL limit: price must be ABOVE current bid
# For Binance BUY limit, use ask - 0.01 to ensure price is below ask
binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
# For Bybit SELL limit, use bid + 0.01 to ensure price is above bid
bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_buy_price = round(spread_data.binance_quote.bid_price, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price, 2)
```

#### 3.2 反向开仓价格修改

**修改前**：
```python
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_sell_price = round(spread_data.binance_quote.ask_price, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price, 2)
```

#### 3.3 正向平仓价格修改

**修改前**：
```python
binance_sell_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_sell_price = round(spread_data.binance_quote.ask_price, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price, 2)
```

#### 3.4 反向平仓价格修改

**修改前**：
```python
binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

**修改后**：
```python
# Use market prices directly for maker orders
binance_buy_price = round(spread_data.binance_quote.bid_price, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price, 2)
```

---

### 4. order_executor.py（订单执行器）

#### 4.1 移除追单逻辑

**修改前**（第475-580行）：
- 等待3秒检查订单状态
- 如果未成交，取消原订单
- 使用MARKET订单追单
- 最多重试3次

**修改后**：
```python
# Return final status (no chase logic, pure maker orders)
return {
    "success": binance_result["success"] and bybit_result["success"],
    "binance_filled": False,  # Status unknown without checking
    "bybit_filled": False,  # Status unknown without checking
    "binance_order_id": binance_order_id,
    "bybit_order_id": bybit_order_id,
    "binance_result": binance_result,
    "bybit_result": bybit_result,
    "retries": 0,
}
```

**移除的方法**：
- `_chase_binance_order()` - 不再需要
- `_chase_bybit_order()` - 不再需要

---

## 修改影响分析

### 优势

1. **手续费降低**
   - 修改前：混合费率（Maker 0.02% + Taker 0.04%）
   - 修改后：纯Maker费率（0.02%）
   - **节省**：每次交易节省约50%手续费

2. **订单价格更优**
   - 修改前：价格调整±0.01可能导致滑点
   - 修改后：直接使用市场最优价格
   - **效果**：理论上获得更好的成交价格

3. **代码简化**
   - 移除了复杂的追单逻辑
   - 减少了约100行代码
   - 降低了维护成本

### 风险

1. **成交率降低**
   - ⚠️ LIMIT订单可能不成交或部分成交
   - ⚠️ 没有追单机制保证成交
   - **建议**：监控订单成交率，必要时手动处理

2. **套利机会错失**
   - ⚠️ 如果订单未成交，可能错过套利机会
   - ⚠️ 市场快速变化时可能无法及时成交
   - **建议**：设置订单超时自动取消机制

3. **持仓不平衡**
   - ⚠️ 一边成交一边未成交会导致单边持仓
   - ⚠️ 需要手动平衡持仓
   - **建议**：实现订单状态监控和告警

---

## 价格策略对比

### Binance买入订单

| 场景 | 修改前 | 修改后 | 说明 |
|------|--------|--------|------|
| 正向开仓 | bid + 0.01 | bid | 使用买价（更优） |
| 反向平仓 | ask - 0.01 | bid | 使用买价（更优） |

### Binance卖出订单

| 场景 | 修改前 | 修改后 | 说明 |
|------|--------|--------|------|
| 正向平仓 | ask - 0.01 | ask | 使用卖价（更优） |
| 反向开仓 | ask - 0.01 | ask | 使用卖价（一致） |

### Bybit买入订单

| 场景 | 修改前 | 修改后 | 说明 |
|------|--------|--------|------|
| 正向平仓 | bid + 0.01 | bid | 使用买价（更优） |
| 反向开仓 | bid + 0.01 | bid | 使用买价（更优） |

### Bybit卖出订单

| 场景 | 修改前 | 修改后 | 说明 |
|------|--------|--------|------|
| 正向开仓 | ask - 0.01 | ask | 使用卖价（更优） |
| 反向平仓 | ask - 0.01 | ask | 使用卖价（一致） |

---

## 手续费节省计算

### 单次交易（1 XAU @ 2700 USDT）

**修改前（假设50%追单率）**：
- Maker成交：2700 × 0.0002 = 0.54 USDT
- Taker成交：2700 × 0.0004 = 1.08 USDT
- 平均：(0.54 + 1.08) / 2 = 0.81 USDT
- 双边（开仓+平仓）：0.81 × 2 = 1.62 USDT

**修改后（100% Maker）**：
- Maker成交：2700 × 0.0002 = 0.54 USDT
- 双边（开仓+平仓）：0.54 × 2 = 1.08 USDT

**节省**：1.62 - 1.08 = 0.54 USDT/XAU（33%）

### 月度节省（假设100次交易）

- 修改前：1.62 × 100 = 162 USDT
- 修改后：1.08 × 100 = 108 USDT
- **月度节省**：54 USDT

---

## 后续建议

### 1. 监控机制
- 实现订单成交率监控
- 设置未成交订单告警
- 记录每次订单的成交时间

### 2. 风险控制
- 设置订单超时自动取消（如30秒）
- 实现单边持仓检测和告警
- 添加手动平仓功能

### 3. 性能优化
- 如果成交率<70%，考虑恢复价格调整（但使用更小的调整值，如±0.005）
- 如果成交率>90%，当前策略最优

### 4. 数据分析
- 统计Maker订单成交率
- 分析不同市场条件下的成交情况
- 优化订单价格策略

---

## 修改文件清单

1. ✅ `backend/app/services/strategy_forward.py`
2. ✅ `backend/app/services/strategy_reverse.py`
3. ✅ `backend/app/services/arbitrage_strategy.py`
4. ✅ `backend/app/services/order_executor.py`

---

## 测试建议

1. **单元测试**
   - 测试价格计算逻辑
   - 验证订单参数正确性

2. **集成测试**
   - 测试完整的开仓/平仓流程
   - 验证订单成功提交到交易所

3. **生产测试**
   - 小额测试（0.01 XAU）
   - 监控订单成交情况
   - 逐步增加交易量

---

## 回滚方案

如果修改后成交率过低，可以：

1. **恢复价格调整**（使用更小的值）
   ```python
   binance_buy_price = binance_bid + 0.005
   bybit_sell_price = bybit_ask - 0.005
   ```

2. **恢复追单机制**（但延长等待时间）
   ```python
   await asyncio.sleep(10)  # 从3秒改为10秒
   ```

3. **混合策略**
   - 初始订单：纯Maker
   - 追单订单：使用更激进的LIMIT价格
   - 最后才使用MARKET订单

---

## 结论

本次修改将订单策略优化为纯Maker模式，预期可以节省约33%的交易手续费。但需要密切监控订单成交率，确保不会因为成交率降低而错失套利机会。建议在生产环境中进行小额测试，根据实际成交情况调整策略。