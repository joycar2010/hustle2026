# 前端页面点差计算公式汇总

## 概述
后端策略计算逻辑已完全删除，但前端页面仍保留点差计算和显示功能。以下是所有前端页面中的点差计算公式。

---

## 1. SpreadDataTable.vue
**文件路径**: `frontend/src/components/trading/SpreadDataTable.vue`

**计算公式** (第60-61行):
```javascript
// 反向开仓: bybit做多点差 = binance_ask - bybit_ask
bybitSpread: newData.binance_ask - newData.bybit_ask

// 正向开仓: binance做多点差 = bybit_bid - binance_bid
binanceSpread: newData.bybit_bid - newData.binance_bid
```

**用途**: 实时显示点差历史表格（最新10条）

---

## 2. SpreadChart.vue (Trading)
**文件路径**: `frontend/src/components/trading/SpreadChart.vue`

**实时数据计算** (第135-136行):
```javascript
// 正向开仓: binance做多点差 = bybit_bid - binance_bid
const forwardSpread = newData.bybit_bid - newData.binance_bid

// 反向开仓: bybit做多点差 = binance_ask - bybit_ask
const reverseSpread = newData.binance_ask - newData.bybit_ask
```

**历史数据计算** (第173-174行):
```javascript
// 做多Binance (正向)
const forwardSpread = item.bybit_quote.ask - item.binance_quote.bid

// 做多Bybit (反向)
const reverseSpread = item.binance_quote.ask - item.bybit_quote.bid
```

**用途**: 点差趋势图表显示

---

## 3. RealTimePrices.vue
**文件路径**: `frontend/src/components/dashboard/RealTimePrices.vue`

**买卖价差** (第52, 98行):
```javascript
// Binance买卖价差
binance.ask - binance.bid

// Bybit买卖价差
bybit.ask - bybit.bid
```

**套利机会计算** (第139-140行):
```javascript
// 正向套利点差
const forwardSpread = bybit.value.bid - binance.value.ask

// 反向套利点差
const reverseSpread = binance.value.bid - bybit.value.ask
```

**用途**: 实时价格显示和套利机会提示

---

## 4. Dashboard.vue
**文件路径**: `frontend/src/views/Dashboard.vue`

**买卖价差** (第80, 132行):
```javascript
// Bybit买卖价差
bybitPrice.ask - bybitPrice.bid

// Binance买卖价差
binancePrice.ask - binancePrice.bid
```

**套利点差** (第170, 174行):
```javascript
// 正向点差
const forwardSpread = bybitPrice.value.bid - binancePrice.value.ask

// 反向点差
const reverseSpread = binancePrice.value.bid - bybitPrice.value.ask
```

**用途**: 主仪表板价格和点差显示

---

## 5. SpreadHistory.vue
**文件路径**: `frontend/src/components/dashboard/SpreadHistory.vue`

**历史数据计算** (第143-146行):
```javascript
// 正向点差
const forwardSpread = item.bybit_quote.ask - item.binance_quote.bid

// 反向点差
const reverseSpread = item.binance_quote.bid - item.bybit_quote.ask

// 选择绝对值较大的点差
const spread = isForward ? forwardSpread : reverseSpread
```

**用途**: 点差历史记录表格

---

## 6. OrderBook.vue
**文件路径**: `frontend/src/components/trading/OrderBook.vue`

**订单簿价差** (第49行):
```javascript
// 最优卖价 - 最优买价
spread = asks[0].price - bids[0].price
```

**用途**: 订单簿买卖价差显示

---

## 点差计算公式总结

### 正向套利（做多Binance，做空Bybit）
- **开仓点差**: `bybit_bid - binance_bid` 或 `bybit_bid - binance_ask`
- **含义**: Bybit卖出价 - Binance买入价

### 反向套利（做空Binance，做多Bybit）
- **开仓点差**: `binance_ask - bybit_ask` 或 `binance_bid - bybit_ask`
- **含义**: Binance卖出价 - Bybit买入价

### 买卖价差（单一交易所）
- **公式**: `ask_price - bid_price`
- **含义**: 卖一价 - 买一价

---

## 注意事项

1. **后端状态**: 后端所有策略计算逻辑已删除，点差计算返回0.0
2. **前端状态**: 前端保留完整的点差计算和显示功能
3. **数据来源**: 前端从WebSocket实时数据或REST API获取原始价格数据
4. **计算位置**: 所有点差计算均在前端JavaScript代码中完成
5. **功能影响**:
   - 前端页面可以正常显示点差数据
   - 后端策略执行功能已禁用（返回501错误）
   - 手动交易功能已禁用（返回501错误）

---

## 相关文件

### 已删除的后端文件
- `backend/app/services/strategy_forward.py`
- `backend/app/services/strategy_reverse.py`
- `backend/app/services/arbitrage_strategy.py`
- `backend/app/services/order_executor.py`

### 已修改的后端文件
- `backend/app/services/realtime_market_service.py`: 点差计算改为返回0.0
- `backend/app/api/v1/strategies.py`: 策略执行端点返回501错误
- `backend/app/api/v1/trading.py`: 手动交易端点返回501错误

### 保留的前端文件（含点差计算）
- `frontend/src/components/trading/SpreadDataTable.vue`
- `frontend/src/components/trading/SpreadChart.vue`
- `frontend/src/components/dashboard/RealTimePrices.vue`
- `frontend/src/views/Dashboard.vue`
- `frontend/src/components/dashboard/SpreadHistory.vue`
- `frontend/src/components/trading/OrderBook.vue`
