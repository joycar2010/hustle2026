# MT5限价单价格规则修复

## 问题根源

MT5限价单对价格有严格的规则要求：

### MT5限价单价格规则
- **买入限价单(BUY LIMIT)**: 价格必须**低于**当前卖价(ask)
- **卖出限价单(SELL LIMIT)**: 价格必须**高于**当前买价(bid)

如果违反这些规则，MT5会返回 `retcode=10015, Invalid price`

## 原有错误逻辑

### 反向套利开仓（错误）
```python
# ❌ 错误：买入价 = bid + 0.01
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

**问题**：如果价差小于0.01，计算出的价格可能等于或高于ask价，违反MT5规则。

例如：
- bid = 5168.50, ask = 5168.51
- 计算价格 = 5168.51
- 结果：5168.51 >= 5168.51 ❌ 无效

### 正向套利开仓（错误）
```python
# ❌ 错误：买入价 = bid + 0.01
binance_buy_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
```

同样的问题。

## 修复方案

### 核心原则
- **买入限价单**：使用 `ask - 0.01` 确保价格低于ask
- **卖出限价单**：使用 `bid + 0.01` 确保价格高于bid

### 修复后的代码

#### 1. 反向套利开仓
```python
# ✅ 正确：Sell Binance, Buy Bybit
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)  # 使用ask-0.01
```

#### 2. 反向套利平仓
```python
# ✅ 正确：Buy Binance, Sell Bybit
binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)  # 使用ask-0.01
bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

#### 3. 正向套利开仓
```python
# ✅ 正确：Buy Binance, Sell Bybit
binance_buy_price = round(spread_data.binance_quote.ask_price - 0.01, 2)  # 使用ask-0.01
bybit_sell_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

#### 4. 正向套利平仓
```python
# ✅ 正确：Sell Binance, Buy Bybit
binance_sell_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)  # 使用ask-0.01
```

## 修复文件

- `backend/app/services/arbitrage_strategy.py`
  - 第44-51行：正向套利开仓
  - 第132-139行：反向套利开仓
  - 第217-224行：正向套利平仓
  - 第281-288行：反向套利平仓

## 价格计算逻辑总结

| 操作 | 方向 | 价格计算 | 原因 |
|------|------|---------|------|
| 买入限价 | BUY | ask - 0.01 | 必须低于当前卖价 |
| 卖出限价 | SELL | bid + 0.01 | 必须高于当前买价 |

## 验证

修复后，所有套利功能应该能够正常下单，不再出现 `retcode=10015` 错误。

测试步骤：
1. 访问 http://13.115.21.77:3000/StrategyPanel.vue
2. 点击"启用反向开仓"按钮
3. 验证订单成功下单（retcode=0）
4. 测试其他3个套利功能

## 相关文档

- [MT5_FINAL_FIX.md](MT5_FINAL_FIX.md) - MT5订单填充类型修复
- [ARBITRAGE_FIXES_VERIFICATION.md](ARBITRAGE_FIXES_VERIFICATION.md) - 套利策略修复验证
