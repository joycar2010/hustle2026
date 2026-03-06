# 套利策略计算逻辑完整汇总

## 修改日期
2026-03-02

## 目录
1. [点差计算逻辑](#1-点差计算逻辑)
2. [订单价格计算逻辑](#2-订单价格计算逻辑)
3. [订单类型选择逻辑](#3-订单类型选择逻辑)
4. [持仓计算逻辑](#4-持仓计算逻辑)
5. [套利触发逻辑](#5-套利触发逻辑)
6. [手续费计算逻辑](#6-手续费计算逻辑)
7. [利润计算逻辑](#7-利润计算逻辑)

---

## 1. 点差计算逻辑

### 1.1 基础价格获取

**文件位置**：`backend/app/services/realtime_market_service.py`

**Binance价格**（第127-147行）：
```python
# 优先使用WebSocket实时数据
if binance_ws.connected and binance_ws.bid and binance_ws.ask:
    binance_bid = binance_ws.bid
    binance_ask = binance_ws.ask
# 备用REST API
else:
    ticker = await self.binance_client.get_book_ticker("XAUUSDT")
    binance_bid = float(ticker["bidPrice"])
    binance_ask = float(ticker["askPrice"])
```

**Bybit价格**（第149-167行）：
```python
# 通过MT5获取Bybit价格
tick = await loop.run_in_executor(None, self.mt5_client.get_tick, "XAUUSD.s")
bybit_bid = float(tick["bid"])
bybit_ask = float(tick["ask"])
```

### 1.2 点差计算公式

**文件位置**：`backend/app/services/realtime_market_service.py`（第239-240行）

**正向点差**（Forward Spread）：
```python
forward_spread = bybit_bid - binance_ask
```
- **含义**：Bybit买价 - Binance卖价
- **正值**：可以做正向套利（买Binance，卖Bybit）
- **示例**：bybit_bid=2700.5, binance_ask=2698.0 → forward_spread=2.5

**反向点差**（Reverse Spread）：
```python
reverse_spread = binance_bid - bybit_ask
```
- **含义**：Binance买价 - Bybit卖价
- **正值**：可以做反向套利（卖Binance，买Bybit）
- **示例**：binance_bid=2700.0, bybit_ask=2697.5 → reverse_spread=2.5

### 1.3 开仓/平仓点差

**正向套利**：
- **开仓点差**：`forward_entry_spread = bybit_bid - binance_ask`
- **平仓点差**：`forward_exit_spread = binance_bid - bybit_ask`

**反向套利**：
- **开仓点差**：`reverse_entry_spread = binance_ask - bybit_bid`
- **平仓点差**：`reverse_exit_spread = bybit_bid - binance_ask`

---

## 2. 订单价格计算逻辑

### 2.1 正向套利价格计算

**文件位置**：
- `backend/app/services/strategy_forward.py`
- `backend/app/services/arbitrage_strategy.py`

#### 2.1.1 正向开仓（买Binance，卖Bybit）

**strategy_forward.py**（第57-62行）：
```python
binance_bid = binance_quote.get("bid_price", 0)
bybit_ask = bybit_quote.get("ask_price", 0)

# Use market prices directly for maker orders
binance_buy_price = binance_bid  # Binance买入价 = Binance买价
bybit_sell_price = bybit_ask     # Bybit卖出价 = Bybit卖价
```

**arbitrage_strategy.py**（第44-46行）：
```python
# Use market prices directly for maker orders
binance_buy_price = round(spread_data.binance_quote.bid_price, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price, 2)
```

**逻辑说明**：
- Binance买入：使用bid价格（买价），LIMIT订单挂在买价上
- Bybit卖出：使用ask价格（卖价），MARKET订单立即成交

#### 2.1.2 正向平仓（卖Binance，买Bybit）

**strategy_forward.py**（第111-116行）：
```python
binance_ask = binance_quote.get("ask_price", 0)
bybit_bid = bybit_quote.get("bid_price", 0)

# Use market prices directly for maker orders
binance_sell_price = binance_ask  # Binance卖出价 = Binance卖价
bybit_buy_price = bybit_bid       # Bybit买入价 = Bybit买价
```

**arbitrage_strategy.py**（第221-223行）：
```python
# Use market prices directly for maker orders
binance_sell_price = round(spread_data.binance_quote.ask_price, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price, 2)
```

### 2.2 反向套利价格计算

**文件位置**：
- `backend/app/services/strategy_reverse.py`
- `backend/app/services/arbitrage_strategy.py`

#### 2.2.1 反向开仓（卖Binance，买Bybit）

**strategy_reverse.py**（第58-63行）：
```python
binance_ask = binance_quote.get("ask_price", 0)
bybit_bid = bybit_quote.get("bid_price", 0)

# Use market prices directly for maker orders
binance_sell_price = binance_ask  # Binance卖出价 = Binance卖价
bybit_buy_price = bybit_bid       # Bybit买入价 = Bybit买价
```

**arbitrage_strategy.py**（第132-134行）：
```python
# Use market prices directly for maker orders
binance_sell_price = round(spread_data.binance_quote.ask_price, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price, 2)
```

#### 2.2.2 反向平仓（买Binance，卖Bybit）

**strategy_reverse.py**（第112-117行）：
```python
binance_bid = binance_quote.get("bid_price", 0)
bybit_ask = bybit_quote.get("ask_price", 0)

# Use market prices directly for maker orders
binance_buy_price = binance_bid   # Binance买入价 = Binance买价
bybit_sell_price = bybit_ask      # Bybit卖出价 = Bybit卖价
```

**arbitrage_strategy.py**（第290-292行）：
```python
# Use market prices directly for maker orders
binance_buy_price = round(spread_data.binance_quote.bid_price, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price, 2)
```

### 2.3 价格精度处理

所有价格都会四舍五入到2位小数：
```python
binance_price = round(price, 2)  # Binance XAUUSDT: 2位小数
bybit_price = round(price, 2)    # Bybit XAUUSD.s: 2位小数
```

---

## 3. 订单类型选择逻辑

### 3.1 Binance订单类型

**文件位置**：`backend/app/services/order_executor.py`（第428-436行）

```python
self.place_binance_order(
    binance_account,
    binance_symbol,
    binance_side,
    order_type,  # "LIMIT"
    quantity,
    binance_price,
    position_side=binance_position_side,
)
```

**订单类型**：
- **LIMIT**（限价单）
- **Maker**方式
- **手续费**：0.02%
- **成交保证**：❌ 可能不成交

### 3.2 Bybit订单类型

**文件位置**：`backend/app/services/order_executor.py`（第438-445行）

```python
self.place_bybit_order(
    bybit_account,
    bybit_symbol,
    bybit_side,
    "Market",  # Always use Market orders for Bybit (Taker)
    str(bybit_quantity),
    None,  # Market orders don't need price
)
```

**订单类型**：
- **MARKET**（市价单）
- **Taker**方式
- **手续费**：0.06%
- **成交保证**：✅ 保证成交

### 3.3 MT5订单类型映射

**文件位置**：`backend/app/services/order_executor.py`（第76-80行）

```python
# Map side to MT5 order type
if side.lower() == "buy":
    mt5_order_type = mt5.ORDER_TYPE_BUY_LIMIT if order_type.lower() == "limit" else mt5.ORDER_TYPE_BUY
else:
    mt5_order_type = mt5.ORDER_TYPE_SELL_LIMIT if order_type.lower() == "limit" else mt5.ORDER_TYPE_SELL
```

**当前使用**：
- 由于传入`order_type="Market"`，所以使用：
  - 买入：`mt5.ORDER_TYPE_BUY`（市价买单）
  - 卖出：`mt5.ORDER_TYPE_SELL`（市价卖单）

---

## 4. 持仓计算逻辑

### 4.1 数量单位转换

**Binance XAUUSDT**：
- 1 contract = 1 XAU（盎司）
- 最小交易量：0.001 XAU
- 精度：3位小数

**Bybit XAUUSD.s（MT5）**：
- 1 lot = 100 XAU（盎司）
- 最小交易量：0.01 lot
- 精度：2位小数

**转换公式**（`order_executor.py`第374-375行）：
```python
if bybit_quantity is None:
    bybit_quantity = quantity / 100.0
```

**示例**：
- Binance数量：1.0 XAU
- Bybit数量：1.0 / 100 = 0.01 lot

### 4.2 数量精度处理

**文件位置**：`backend/app/services/order_executor.py`（第377-381行）

```python
# Round quantities to correct precision
# Binance XAUUSDT: min 0.001, step 0.001 → 3 decimal places
quantity = round(quantity, 3)
# Bybit MT5 XAUUSD.s: min 0.01 lot, step 0.01 → 2 decimal places
bybit_quantity = round(bybit_quantity, 2)
```

### 4.3 最小数量验证

**文件位置**：`backend/app/services/order_executor.py`（第383-396行）

```python
# Validate minimum quantities
# Binance XAUUSDT: minimum 0.001 XAU
if quantity < 0.001:
    return {
        "success": False,
        "error": f"Binance数量不足: {quantity} XAU < 0.001 XAU (最小交易量)",
    }

# Bybit MT5 XAUUSD.s: minimum 0.01 Lot
if bybit_quantity < 0.01:
    return {
        "success": False,
        "error": f"Bybit数量不足: {bybit_quantity} Lot < 0.01 Lot (最小交易量)",
    }
```

### 4.4 持仓方向（Binance）

**文件位置**：`backend/app/services/order_executor.py`（第422-424行）

```python
# Derive positionSide for Binance hedge mode accounts
# BUY opens/closes LONG side; SELL opens/closes SHORT side
binance_position_side = "LONG" if binance_side.upper() == "BUY" else "SHORT"
```

**逻辑**：
- BUY订单 → LONG持仓
- SELL订单 → SHORT持仓

---

## 5. 套利触发逻辑

### 5.1 正向套利触发条件

**文件位置**：`backend/app/services/strategy_forward.py`（第25-31行）

```python
async def check_entry_condition(self, spread_data: Dict[str, Any]) -> bool:
    """Check if forward arbitrage entry condition is met

    Entry spread = bybit_ask - binance_bid
    """
    forward_entry_spread = spread_data.get("forward_entry_spread", 0)
    return forward_entry_spread >= self.config.target_spread
```

**触发条件**：
```
forward_entry_spread >= target_spread
```

**示例**：
- target_spread = 2.0 USDT
- forward_entry_spread = 2.5 USDT
- 结果：触发开仓 ✅

### 5.2 正向套利平仓条件

**文件位置**：`backend/app/services/strategy_forward.py`（第33-40行）

```python
async def check_exit_condition(self, spread_data: Dict[str, Any]) -> bool:
    """Check if forward arbitrage exit condition is met

    Exit spread = binance_ask - bybit_bid
    """
    forward_exit_spread = spread_data.get("forward_exit_spread", 0)
    # Exit when spread narrows (profitable to close)
    return forward_exit_spread <= 0
```

**平仓条件**：
```
forward_exit_spread <= 0
```

**示例**：
- forward_exit_spread = -0.5 USDT
- 结果：触发平仓 ✅

### 5.3 反向套利触发条件

**文件位置**：`backend/app/services/strategy_reverse.py`（第25-32行）

```python
async def check_entry_condition(self, spread_data: Dict[str, Any]) -> bool:
    """Check if reverse arbitrage entry condition is met

    Entry spread = binance_ask - bybit_bid (should be negative for profit)
    """
    reverse_entry_spread = spread_data.get("reverse_entry_spread", 0)
    # For reverse arbitrage, we want negative spread (Binance cheaper than Bybit)
    return reverse_entry_spread <= -self.config.target_spread
```

**触发条件**：
```
reverse_entry_spread <= -target_spread
```

**示例**：
- target_spread = 2.0 USDT
- reverse_entry_spread = -2.5 USDT
- 结果：触发开仓 ✅

### 5.4 反向套利平仓条件

**文件位置**：`backend/app/services/strategy_reverse.py`（第34-41行）

```python
async def check_exit_condition(self, spread_data: Dict[str, Any]) -> bool:
    """Check if reverse arbitrage exit condition is met

    Exit spread = bybit_ask - binance_bid
    """
    reverse_exit_spread = spread_data.get("reverse_exit_spread", 0)
    # Exit when spread narrows (profitable to close)
    return reverse_exit_spread <= 0
```

**平仓条件**：
```
reverse_exit_spread <= 0
```

---

## 6. 手续费计算逻辑

### 6.1 Binance手续费

**订单类型**：LIMIT（Maker）
**费率**：0.02%

**计算公式**：
```python
binance_fee = price * quantity * 0.0002
```

**示例**（1 XAU @ 2700 USDT）：
```
binance_fee = 2700 * 1.0 * 0.0002 = 0.54 USDT
```

### 6.2 Bybit手续费

**订单类型**：MARKET（Taker）
**费率**：0.06%

**计算公式**：
```python
bybit_fee = price * quantity * 100 * 0.0006  # 注意：1 lot = 100 XAU
```

**示例**（0.01 lot @ 2700 USDT）：
```
bybit_fee = 2700 * 0.01 * 100 * 0.0006 = 1.62 USDT
```

### 6.3 总手续费

**单边手续费**：
```
total_fee_one_side = binance_fee + bybit_fee
                   = 0.54 + 1.62
                   = 2.16 USDT
```

**双边手续费**（开仓+平仓）：
```
total_fee_round_trip = total_fee_one_side * 2
                     = 2.16 * 2
                     = 4.32 USDT
```

---

## 7. 利润计算逻辑

### 7.1 正向套利利润

**文件位置**：`backend/app/services/arbitrage_strategy.py`（第251行）

```python
# Calculate profit (simplified - should include fees)
task.profit = (task.open_spread - spread_data.forward_exit_spread) * quantity
```

**公式**：
```
profit = (open_spread - close_spread) * quantity - total_fees
```

**详细计算**：
```python
# 开仓点差
open_spread = bybit_bid - binance_ask  # 例如：2700.5 - 2698.0 = 2.5

# 平仓点差
close_spread = binance_bid - bybit_ask  # 例如：2699.0 - 2699.5 = -0.5

# 点差收益
spread_profit = (open_spread - close_spread) * quantity
              = (2.5 - (-0.5)) * 1.0
              = 3.0 USDT

# 扣除手续费
net_profit = spread_profit - total_fees
           = 3.0 - 4.32
           = -1.32 USDT（亏损）
```

### 7.2 反向套利利润

**文件位置**：`backend/app/services/arbitrage_strategy.py`（第320行）

```python
# Calculate profit: open_spread (binance_ask - bybit_bid) minus exit cost (bybit_ask - binance_bid)
task.profit = (task.open_spread - spread_data.reverse_exit_spread) * quantity
```

**公式**：
```
profit = (open_spread - close_spread) * quantity - total_fees
```

### 7.3 盈亏平衡点

**计算公式**：
```
breakeven_spread = total_fees / quantity
                 = 4.32 / 1.0
                 = 4.32 USDT
```

**结论**：
- 点差 > 4.32 USDT：盈利
- 点差 = 4.32 USDT：盈亏平衡
- 点差 < 4.32 USDT：亏损

---

## 8. 完整交易流程示例

### 8.1 正向套利完整流程

**市场数据**：
- Binance bid: 2698.0, ask: 2698.5
- Bybit bid: 2700.5, ask: 2701.0

**步骤1：计算开仓点差**
```
forward_entry_spread = bybit_bid - binance_ask
                     = 2700.5 - 2698.5
                     = 2.0 USDT
```

**步骤2：检查触发条件**
```
if forward_entry_spread >= target_spread:  # 2.0 >= 2.0
    # 触发开仓 ✅
```

**步骤3：计算订单价格**
```
binance_buy_price = binance_bid = 2698.0  # LIMIT订单
bybit_sell_price = bybit_ask = 2701.0     # MARKET订单
```

**步骤4：下单**
- Binance：买入1.0 XAU @ 2698.0（LIMIT，Maker）
- Bybit：卖出0.01 lot @ 市价（MARKET，Taker）

**步骤5：等待平仓条件**
```
# 市场变化后
binance_bid = 2699.0, ask = 2699.5
bybit_bid = 2699.5, ask = 2700.0

forward_exit_spread = binance_bid - bybit_ask
                    = 2699.0 - 2700.0
                    = -1.0 USDT

if forward_exit_spread <= 0:  # -1.0 <= 0
    # 触发平仓 ✅
```

**步骤6：平仓订单**
- Binance：卖出1.0 XAU @ 2699.5（LIMIT，Maker）
- Bybit：买入0.01 lot @ 市价（MARKET，Taker）

**步骤7：计算利润**
```
# 开仓收益
open_profit = bybit_sell_price - binance_buy_price
            = 2701.0 - 2698.0
            = 3.0 USDT

# 平仓成本
close_cost = bybit_buy_price - binance_sell_price
           = 2700.0 - 2699.5
           = 0.5 USDT

# 点差收益
spread_profit = open_profit - close_cost
              = 3.0 - 0.5
              = 2.5 USDT

# 手续费
total_fees = 4.32 USDT

# 净利润
net_profit = spread_profit - total_fees
           = 2.5 - 4.32
           = -1.82 USDT（亏损）
```

---

## 9. 关键参数汇总

### 9.1 交易参数

| 参数 | Binance | Bybit |
|------|---------|-------|
| 交易对 | XAUUSDT | XAUUSD.s |
| 单位 | 1 contract = 1 XAU | 1 lot = 100 XAU |
| 最小数量 | 0.001 XAU | 0.01 lot |
| 数量精度 | 3位小数 | 2位小数 |
| 价格精度 | 2位小数 | 2位小数 |
| 订单类型 | LIMIT（Maker） | MARKET（Taker） |
| 手续费率 | 0.02% | 0.06% |

### 9.2 点差阈值

| 策略 | 开仓条件 | 平仓条件 |
|------|---------|---------|
| 正向套利 | forward_spread >= target_spread | forward_exit_spread <= 0 |
| 反向套利 | reverse_spread <= -target_spread | reverse_exit_spread <= 0 |

### 9.3 盈亏平衡

| 项目 | 数值 |
|------|------|
| 单边手续费 | 2.16 USDT |
| 双边手续费 | 4.32 USDT |
| 盈亏平衡点差 | 4.32 USDT |
| 建议最小点差 | 5.0 USDT |

---

## 10. 注意事项

### 10.1 价格使用规则

**Binance买入**：
- ✅ 使用bid价格（买价）
- ❌ 不使用ask价格（卖价）

**Binance卖出**：
- ✅ 使用ask价格（卖价）
- ❌ 不使用bid价格（买价）

**Bybit买入**：
- ✅ 使用bid价格（买价）
- ❌ 不使用ask价格（卖价）

**Bybit卖出**：
- ✅ 使用ask价格（卖价）
- ❌ 不使用bid价格（买价）

### 10.2 数量转换规则

**Binance → Bybit**：
```python
bybit_quantity = binance_quantity / 100.0
```

**Bybit → Binance**：
```python
binance_quantity = bybit_quantity * 100.0
```

### 10.3 精度处理规则

**价格精度**：
```python
price = round(price, 2)  # 统一2位小数
```

**数量精度**：
```python
binance_quantity = round(quantity, 3)  # 3位小数
bybit_quantity = round(quantity, 2)    # 2位小数
```

---

## 11. 修改历史

### 2026-03-02 修改
1. ✅ Binance订单改为纯LIMIT（Maker）
2. ✅ Bybit订单改为纯MARKET（Taker）
3. ✅ 去掉价格调整±0.01逻辑
4. ✅ 移除追单机制
5. ✅ 直接使用bid/ask价格

### 修改前后对比

| 项目 | 修改前 | 修改后 |
|------|--------|--------|
| Binance价格 | bid/ask ± 0.01 | bid/ask |
| Bybit价格 | bid/ask ± 0.01 | 市价 |
| Binance订单 | LIMIT + MARKET（追单） | 纯LIMIT |
| Bybit订单 | LIMIT + MARKET（追单） | 纯MARKET |
| 手续费 | 1.08~5.40 USDT | 4.32 USDT |

---

## 12. 相关文件索引

1. **realtime_market_service.py** - 市场数据和点差计算
2. **strategy_forward.py** - 正向套利策略
3. **strategy_reverse.py** - 反向套利策略
4. **arbitrage_strategy.py** - 套利策略服务
5. **order_executor.py** - 订单执行器
6. **binance_client.py** - Binance API客户端
7. **mt5_client.py** - MT5客户端（Bybit）
8. **position_manager.py** - 持仓管理