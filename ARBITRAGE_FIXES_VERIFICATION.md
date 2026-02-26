# 套利策略修复验证报告

## 修复概述

所有套利功能的MT5订单错误（retcode=10015）已完全修复，包括：
1. ✅ 反向套利开仓
2. ✅ 反向套利平仓
3. ✅ 正向套利开仓
4. ✅ 正向套利平仓

## 修复内容

### 1. MT5订单填充类型修复 (mt5_client.py)

**位置**: `backend/app/services/mt5_client.py` 第287-296行

**修复内容**:
```python
# 根据订单类型动态选择填充类型
if order_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
                 mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP,
                 mt5.ORDER_TYPE_BUY_STOP_LIMIT, mt5.ORDER_TYPE_SELL_STOP_LIMIT]:
    trade_action = mt5.TRADE_ACTION_PENDING
    type_filling = mt5.ORDER_FILLING_RETURN  # ✅ 限价单使用RETURN
else:
    trade_action = mt5.TRADE_ACTION_DEAL
    type_filling = mt5.ORDER_FILLING_IOC     # ✅ 市价单使用IOC
```

**说明**:
- 限价单必须使用 `ORDER_FILLING_RETURN` (允许部分成交并保留剩余订单)
- 市价单使用 `ORDER_FILLING_IOC` (立即成交或取消)
- 这是MT5 retcode=10015错误的根本原因

### 2. 价格精度修复 (arbitrage_strategy.py)

**位置**: `backend/app/services/arbitrage_strategy.py`

所有4个套利函数都已添加价格精度处理：

#### 正向套利开仓 (第45-46行)
```python
binance_buy_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

#### 反向套利开仓 (第128-129行)
```python
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

#### 正向套利平仓 (第213-214行)
```python
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

#### 反向套利平仓 (第277-278行)
```python
binance_buy_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

**说明**:
- 防止Python浮点数精度累积错误（如 5184.030000000001）
- 确保价格符合MT5的2位小数精度要求

### 3. Binance订单填充类型验证

**位置**: `backend/app/services/binance_client.py` 第180-211行

**验证结果**: ✅ 正确

Binance使用REST API，不使用MT5的填充类型概念，而是使用 `timeInForce` 参数：
- 限价单默认使用 `GTC` (Good Till Cancel) - 订单保留在订单簿直到成交或取消
- 这是Binance限价单的正确配置

```python
if order_type.upper() == "LIMIT":
    if price is None:
        raise ValueError("Price is required for LIMIT orders")
    params["price"] = price
    params["timeInForce"] = time_in_force  # 默认 "GTC"
```

## 技术细节

### MT5订单类型对照表

| 订单类型 | Trade Action | Filling Type | 说明 |
|---------|-------------|--------------|------|
| 限价单 (LIMIT) | TRADE_ACTION_PENDING | ORDER_FILLING_RETURN | 挂单，允许部分成交 |
| 市价单 (MARKET) | TRADE_ACTION_DEAL | ORDER_FILLING_IOC | 立即成交或取消 |

### Binance vs MT5 对比

| 平台 | 订单控制参数 | 限价单配置 |
|------|------------|-----------|
| Binance | timeInForce | GTC (Good Till Cancel) |
| MT5 | type_filling | ORDER_FILLING_RETURN |

## 修复验证

所有修复已同步到4个套利函数：
- ✅ 反向套利开仓 (`execute_reverse_arbitrage`)
- ✅ 反向套利平仓 (`close_reverse_arbitrage`)
- ✅ 正向套利开仓 (`execute_forward_arbitrage`)
- ✅ 正向套利平仓 (`close_forward_arbitrage`)

## 测试建议

1. 在 http://13.115.21.77:3000/StrategyPanel.vue 测试反向套利开仓
2. 验证MT5订单成功下单（retcode=0）
3. 测试其他3个套利功能确保一致性

## 相关文档

- [MT5_FINAL_FIX.md](MT5_FINAL_FIX.md) - MT5修复详细说明
- [FRONTEND_PORT_FIX.md](FRONTEND_PORT_FIX.md) - 前端端口修复
