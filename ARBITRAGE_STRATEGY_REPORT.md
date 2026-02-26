# 套利策略算法汇总报告

**生成日期**: 2026-02-26
**系统版本**: Hustle 2026 Trading System
**报告范围**: StrategyPanel.vue 所有套利策略 + ManualTrading.vue 平仓功能

---

## 📋 目录

1. [系统架构概览](#系统架构概览)
2. [套利策略详细算法](#套利策略详细算法)
3. [平仓所有持仓功能](#平仓所有持仓功能)
4. [关键技术参数](#关键技术参数)
5. [风险控制机制](#风险控制机制)

---

## 🏗️ 系统架构概览

### 组件关系图

```
前端 (Vue 3)
├── StrategyPanel.vue (套利策略面板)
│   ├── 正向套利策略 (Forward Arbitrage)
│   └── 反向套利策略 (Reverse Arbitrage)
└── ManualTrading.vue (紧急手动交易)
    ├── 手动开仓
    ├── 平仓所有持仓 ⚠️
    └── 取消所有挂单

后端 (FastAPI)
├── arbitrage_strategy.py (套利策略服务)
│   ├── execute_forward_arbitrage()
│   ├── execute_reverse_arbitrage()
│   ├── close_forward_arbitrage()
│   └── close_reverse_arbitrage()
├── order_executor.py (订单执行器)
│   └── execute_dual_order()
└── trading.py (交易API)
    ├── POST /api/v1/trading/manual/close-all
    └── POST /api/v1/trading/manual/cancel-all

交易所
├── Binance (XAUUSDT 永续合约)
└── Bybit MT5 (XAUUSD.s TradFi)
```

---

## 📊 套利策略详细算法

### 1. 正向套利策略 (Forward Arbitrage)

#### 1.1 正向开仓 (Forward Entry)

**策略原理**: 做多 Binance，做空 Bybit，赚取价差收益

**触发条件**:
```
forward_entry_spread = bybit_ask - binance_bid >= target_spread
```

**执行逻辑**:

```python
# 步骤 1: 获取实时行情
spread_data = await market_data_service.get_current_spread()

# 步骤 2: 检查价差是否满足目标
if spread_data.forward_entry_spread < target_spread:
    return {"success": False, "error": "价差不足"}

# 步骤 3: 计算订单价格 (调整 0.01 提高成交率)
binance_buy_price = spread_data.binance_quote.bid_price + 0.01
bybit_sell_price = spread_data.bybit_quote.ask_price - 0.01

# 步骤 4: 执行双边订单
result = await order_executor.execute_dual_order(
    binance_side="BUY",      # Binance 做多
    bybit_side="Sell",       # Bybit 做空
    quantity=quantity,       # Binance 数量 (XAU)
    binance_price=binance_buy_price,
    bybit_price=bybit_sell_price,
    order_type="LIMIT"
)
```

**订单详情**:
- **Binance**: BUY LIMIT @ (bid + 0.01)
  - 合约单位: 1 XAU
  - 持仓方向: LONG
  - 最小数量: 0.001 XAU

- **Bybit**: Sell LIMIT @ (ask - 0.01)
  - 合约单位: 1 Lot = 100 XAU
  - 持仓方向: SHORT
  - 最小数量: 0.01 Lot

**数量转换**:
```
bybit_quantity = binance_quantity / 100
例如: Binance 3 XAU → Bybit 0.03 Lot
```

#### 1.2 正向平仓 (Forward Exit)

**策略原理**: 平掉正向套利持仓，锁定利润

**执行逻辑**:

```python
# 步骤 1: 获取实时行情
spread_data = await market_data_service.get_current_spread()

# 步骤 2: 计算平仓价格
binance_sell_price = spread_data.binance_quote.ask_price - 0.01
bybit_buy_price = spread_data.bybit_quote.bid_price + 0.01

# 步骤 3: 执行平仓订单 (反向操作)
result = await order_executor.execute_dual_order(
    binance_side="SELL",     # 平 Binance 多头
    bybit_side="Buy",        # 平 Bybit 空头
    quantity=quantity,
    binance_price=binance_sell_price,
    bybit_price=bybit_buy_price,
    order_type="LIMIT"
)

# 步骤 4: 计算利润
profit = (open_spread - close_spread) * quantity
```

**订单详情**:
- **Binance**: SELL LIMIT @ (ask - 0.01) - 平多头
- **Bybit**: Buy LIMIT @ (bid + 0.01) - 平空头

---

### 2. 反向套利策略 (Reverse Arbitrage)

#### 2.1 反向开仓 (Reverse Entry)

**策略原理**: 做空 Binance，做多 Bybit，赚取反向价差

**触发条件**:
```
reverse_entry_spread = binance_ask - bybit_bid >= target_spread
```

**执行逻辑**:

```python
# 步骤 1: 获取实时行情
spread_data = await market_data_service.get_current_spread()

# 步骤 2: 检查价差是否满足目标
if spread_data.reverse_entry_spread < target_spread:
    return {"success": False, "error": "价差不足"}

# 步骤 3: 计算订单价格
binance_sell_price = spread_data.binance_quote.ask_price - 0.01
bybit_buy_price = spread_data.bybit_quote.bid_price + 0.01

# 步骤 4: 执行双边订单
result = await order_executor.execute_dual_order(
    binance_side="SELL",     # Binance 做空
    bybit_side="Buy",        # Bybit 做多
    quantity=quantity,
    binance_price=binance_sell_price,
    bybit_price=bybit_buy_price,
    order_type="LIMIT"
)
```

**订单详情**:
- **Binance**: SELL LIMIT @ (ask - 0.01)
  - 持仓方向: SHORT

- **Bybit**: Buy LIMIT @ (bid + 0.01)
  - 持仓方向: LONG

#### 2.2 反向平仓 (Reverse Exit)

**策略原理**: 平掉反向套利持仓，锁定利润

**执行逻辑**:

```python
# 步骤 1: 获取实时行情
spread_data = await market_data_service.get_current_spread()

# 步骤 2: 计算平仓价格
binance_buy_price = spread_data.binance_quote.bid_price + 0.01
bybit_sell_price = spread_data.bybit_quote.ask_price - 0.01

# 步骤 3: 执行平仓订单 (反向操作)
result = await order_executor.execute_dual_order(
    binance_side="BUY",      # 平 Binance 空头
    bybit_side="Sell",       # 平 Bybit 多头
    quantity=quantity,
    binance_price=binance_buy_price,
    bybit_price=bybit_sell_price,
    order_type="LIMIT"
)

# 步骤 4: 计算利润
profit = (open_spread - close_spread) * quantity
```

**订单详情**:
- **Binance**: BUY LIMIT @ (bid + 0.01) - 平空头
- **Bybit**: Sell LIMIT @ (ask - 0.01) - 平多头

---

### 3. 阶梯策略 (Ladder Strategy)

**策略原理**: 根据价差分级执行不同数量的订单

**配置参数**:
```javascript
{
  enabled: true,          // 是否启用该阶梯
  openPrice: 3.00,        // 开仓触发价差 (USDT)
  threshold: 2.00,        // 平仓触发价差 (USDT)
  qtyLimit: 3             // 该阶梯总手数 (XAU)
}
```

**执行逻辑**:

```javascript
// 步骤 1: 监听市场数据
watch(() => marketStore.marketData, (newData) => {
  // 计算当前价差
  const binanceLongValue = type === 'forward'
    ? newData.binance_bid
    : newData.binance_ask

  // 步骤 2: 检查开仓条件
  if (config.openingEnabled) {
    const enabledLadders = config.ladders.filter(l => l.enabled)
    const matchedLadder = enabledLadders.find(l =>
      binanceLongValue >= l.openPrice
    )

    if (matchedLadder) {
      triggerCount.opening++

      // 步骤 3: 达到触发次数后执行
      if (triggerCount.opening >= config.openingSyncQty) {
        executeBatchOpening(matchedLadder)
        triggerCount.opening = 0
      }
    }
  }
})

// 步骤 4: 批量执行 (分批下单)
async function executeBatchOpening(ladder) {
  const totalQuantity = ladder.qtyLimit
  const mCoin = config.mCoin  // 单次最多手数
  const numBatches = Math.ceil(totalQuantity / mCoin)

  for (let i = 0; i < numBatches; i++) {
    const batchQuantity = Math.min(mCoin, remainingQuantity)

    // 执行该批次订单
    await api.post(`/api/v1/strategies/execute/${type}`, {
      binance_account_id,
      bybit_account_id,
      quantity: batchQuantity,
      target_spread: ladder.threshold
    })

    // 等待订单成交后再执行下一批
    await waitForOrderFill(response.data.order_ids)
  }
}
```

**阶梯示例**:
```
阶梯 1: 价差 >= 3.00 USDT → 下单 3 XAU
阶梯 2: 价差 >= 4.00 USDT → 下单 5 XAU
阶梯 3: 价差 >= 5.00 USDT → 下单 10 XAU
```

---

### 4. 追单机制 (Chase Logic)

**策略原理**: 如果限价单未成交，自动追单确保双边成交

**执行流程**:

```python
# 步骤 1: 下初始限价单
binance_result, bybit_result = await asyncio.gather(
    place_binance_order(...),
    place_bybit_order(...)
)

# 步骤 2: 等待并检查成交状态
await asyncio.sleep(retry_delay)
binance_filled = check_binance_order_status(...)
bybit_filled = check_bybit_order_status(...)

# 步骤 3: 追单逻辑 (最多重试 max_retries 次)
retry_count = 0
while retry_count < max_retries and not (binance_filled and bybit_filled):
    # 计算追单数量
    if binance_filled and not bybit_filled:
        # Binance 已成交，追 Bybit
        bybit_chase_qty = binance_filled_qty / 100.0
    elif bybit_filled and not binance_filled:
        # Bybit 已成交，追 Binance
        binance_chase_qty = bybit_filled_qty * 100

    # 取消未成交订单，改用市价单
    if not binance_filled:
        await cancel_binance_order(...)
        await place_binance_order(..., order_type="MARKET")

    if not bybit_filled:
        await cancel_bybit_order(...)
        await place_bybit_order(..., order_type="Market")

    retry_count += 1
```

**追单策略**:
1. **限价单优先**: 初始使用限价单，降低滑点
2. **市价单追单**: 未成交则改用市价单，确保成交
3. **数量匹配**: 根据已成交方的数量调整追单数量
4. **最大重试**: 默认最多重试 3 次

---

## ⚠️ 平仓所有持仓功能

### 功能位置
- **前端**: `ManualTrading.vue` → "⚠️ 平仓所有持仓" 按钮
- **后端**: `POST /api/v1/trading/manual/close-all`

### 功能说明

**用途**: 紧急情况下一键平掉所有交易所的所有持仓

**执行流程**:

```python
async def close_all_positions():
    """平仓所有持仓 - 紧急功能"""

    # 步骤 1: 获取用户所有活跃账户
    accounts = await get_user_accounts(user_id)
    results = []

    # 步骤 2: 遍历每个账户
    for account in accounts:
        if not account.is_active:
            continue

        # === Binance 平仓逻辑 ===
        if account.platform_id == 1:
            # 2.1 获取所有持仓
            positions = await client.get_position_risk("XAUUSDT")

            for pos in positions:
                amt = float(pos.get("positionAmt", 0))
                if amt == 0:
                    continue  # 跳过无持仓

                # 2.2 确定平仓方向
                side = "SELL" if amt > 0 else "BUY"  # 多头平仓卖出，空头平仓买入
                position_side = "LONG" if amt > 0 else "SHORT"
                qty = abs(amt)

                # 2.3 获取实时行情
                quote = await market_data_service.get_binance_quote("XAUUSDT")

                # 2.4 计算平仓价格 (调整 0.01 提高成交率)
                if side == "SELL":
                    price = round(quote.ask_price - 0.01, 2)
                else:
                    price = round(quote.bid_price + 0.01, 2)

                # 2.5 下平仓限价单
                result = await order_executor.place_binance_order(
                    account=account,
                    symbol="XAUUSDT",
                    side=side,
                    order_type="LIMIT",
                    quantity=qty,
                    price=price,
                    position_side=position_side
                )

                # 2.6 保存订单记录到数据库
                if result.get("success"):
                    order_record = OrderRecord(
                        account_id=account.account_id,
                        symbol="XAUUSDT",
                        order_side=side.lower(),
                        order_type="limit",
                        price=price,
                        qty=qty,
                        status="new",
                        source="manual",
                        platform_order_id=str(result.get("order_id"))
                    )
                    db.add(order_record)

                results.append({
                    "exchange": "binance",
                    "account": account.account_name,
                    **result
                })

        # === Bybit MT5 平仓逻辑 ===
        elif account.platform_id == 2:
            # 2.1 获取所有持仓
            positions = await loop.run_in_executor(
                None,
                lambda: mt5.positions_get(symbol="XAUUSD.s")
            )

            if positions:
                # 2.2 获取实时行情
                quote = await market_data_service.get_bybit_quote("XAUUSD.s")

                for pos in positions:
                    # 2.3 确定平仓方向
                    # MT5: POSITION_TYPE_BUY (多头) → Sell 平仓
                    # MT5: POSITION_TYPE_SELL (空头) → Buy 平仓
                    side = "Sell" if pos.type == mt5.POSITION_TYPE_BUY else "Buy"

                    # 2.4 计算平仓价格
                    if side == "Sell":
                        price = round(quote.ask_price - 0.01, 2)
                    else:
                        price = round(quote.bid_price + 0.01, 2)

                    # 2.5 下平仓限价单
                    result = await order_executor.place_bybit_order(
                        account=account,
                        symbol="XAUUSD.s",
                        side=side,
                        order_type="Limit",
                        quantity=str(pos.volume),
                        price=str(price)
                    )

                    # 2.6 保存订单记录到数据库
                    if result.get("success"):
                        order_record = OrderRecord(
                            account_id=account.account_id,
                            symbol="XAUUSD.s",
                            order_side=side.lower(),
                            order_type="limit",
                            price=price,
                            qty=pos.volume,
                            status="new",
                            source="manual",
                            platform_order_id=str(result.get("order_id"))
                        )
                        db.add(order_record)

                    results.append({
                        "exchange": "bybit",
                        "account": account.account_name,
                        **result
                    })

    # 步骤 3: 提交所有订单记录到数据库
    await db.commit()

    return {
        "success": True,
        "results": results,
        "total_orders": len(results)
    }
```

### 前端交互流程

```javascript
// ManualTrading.vue

async function closeAllPositions() {
  // 步骤 1: 二次确认
  if (!confirm('确定要平仓所有持仓吗？')) return

  if (loading.value) return
  loading.value = true

  try {
    // 步骤 2: 调用后端API
    const res = await api.post('/api/v1/trading/manual/close-all')

    // 步骤 3: 显示结果
    showStatus(
      `平仓指令已发送，共 ${res.data.results?.length || 0} 笔`,
      true
    )

    // 步骤 4: 刷新订单列表
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '平仓失败', false)
  } finally {
    loading.value = false
  }
}
```

### 关键特性

1. **全账户覆盖**: 自动处理用户所有活跃账户
2. **双交易所支持**: 同时平仓 Binance 和 Bybit MT5 持仓
3. **智能方向判断**: 自动识别多空方向，执行反向平仓
4. **限价单优先**: 使用限价单平仓，减少滑点损失
5. **数据库记录**: 所有平仓订单都记录到数据库
6. **二次确认**: 前端要求用户确认，防止误操作

### 安全机制

```javascript
// 前端安全检查
1. 二次确认对话框
2. 加载状态锁定 (防止重复点击)
3. 错误提示

// 后端安全检查
1. 用户身份验证 (JWT Token)
2. 账户权限验证 (只能操作自己的账户)
3. 账户状态检查 (只处理活跃账户)
4. 异常捕获和错误处理
```

---

## 🔧 关键技术参数

### 交易所规格

| 参数 | Binance XAUUSDT | Bybit XAUUSD.s (MT5) |
|------|----------------|---------------------|
| **合约单位** | 1 XAU (盎司) | 1 Lot = 100 XAU |
| **最小数量** | 0.001 XAU | 0.01 Lot |
| **数量精度** | 3 位小数 | 2 位小数 |
| **价格精度** | 2 位小数 | 由 symbol_info.digits 决定 |
| **默认杠杆** | 20x | 100x |
| **持仓模式** | 双向持仓 (Hedge Mode) | 单向持仓 |
| **订单类型** | LIMIT / MARKET | Limit / Market |

### 数量转换公式

```python
# Binance → Bybit
bybit_quantity = binance_quantity / 100.0
例如: 3 XAU → 0.03 Lot

# Bybit → Binance
binance_quantity = bybit_quantity * 100
例如: 0.05 Lot → 5 XAU
```

### 价格调整策略

```python
# 买入订单 (提高成交率)
buy_price = bid_price + 0.01

# 卖出订单 (提高成交率)
sell_price = ask_price - 0.01
```

---

## 🛡️ 风险控制机制

### 1. 下单前验证

```python
# 1.1 最小交易量验证
if binance_quantity < 0.001:
    return {"error": "Binance数量不足: < 0.001 XAU"}

if bybit_quantity < 0.01:
    return {"error": "Bybit数量不足: < 0.01 Lot"}

# 1.2 交易时间检查
is_open, message = is_bybit_trading_hours()
if not is_open:
    return {"error": f"Bybit交易时间限制: {message}"}

# 1.3 资金充足性检查
binance_required_margin = price * quantity / leverage
if binance_available < binance_required_margin:
    return {"error": "Binance资金不足"}

bybit_required_margin = price * quantity * 100 / leverage
if bybit_available < bybit_required_margin:
    return {"error": "Bybit资金不足"}
```

### 2. 账户验证

```javascript
// 前端验证
function validateAccountsForExecution() {
  // 2.1 检查账户是否存在
  if (!binanceAccount || !bybitMT5Account) {
    return {valid: false, message: '账户不存在'}
  }

  // 2.2 检查账户是否断开连接
  if (disconnectedAccounts.has(account_id)) {
    return {valid: false, message: '账户已断开连接'}
  }

  // 2.3 检查账户是否激活
  if (!account.is_active) {
    return {valid: false, message: '账户未激活'}
  }

  // 2.4 检查账户余额
  if (balance <= 0) {
    return {valid: false, message: '账户余额为0'}
  }

  // 2.5 检查单腿模式
  if (account.single_leg_mode) {
    return {valid: false, message: '账户处于单腿模式'}
  }

  return {valid: true}
}
```

### 3. 触发次数控制

```javascript
// 防止误触发
config.openingSyncQty = 3  // 需要连续触发 3 次才执行
config.closingSyncQty = 3  // 需要连续触发 3 次才执行

// 计数逻辑
if (matchedLadder) {
  triggerCount.opening++
  if (triggerCount.opening >= config.openingSyncQty) {
    executeBatchOpening(matchedLadder)
    triggerCount.opening = 0
  }
} else {
  triggerCount.opening = 0  // 不满足条件时重置计数
}
```

### 4. 订单状态监控

```python
# 4.1 订单成交检查
binance_status = await check_binance_order_status(...)
bybit_status = await check_bybit_order_status(...)

# 4.2 追单机制
if not binance_filled or not bybit_filled:
    # 取消未成交订单
    # 改用市价单追单
    # 最多重试 3 次
```

### 5. 数据库记录

```python
# 所有订单都记录到数据库
order_record = OrderRecord(
    account_id=account.account_id,
    symbol=symbol,
    order_side=side.lower(),
    order_type=order_type,
    price=price,
    qty=quantity,
    status="new",
    source="strategy" | "manual",
    platform_order_id=order_id,
    create_time=datetime.utcnow()
)
db.add(order_record)
await db.commit()
```

---

## 📈 策略执行流程总览

### 完整执行链路

```
1. 用户操作
   ↓
2. 前端验证 (账户状态、余额、连接)
   ↓
3. 触发次数累计 (防误触发)
   ↓
4. 后端API调用
   ↓
5. 获取实时行情
   ↓
6. 价差检查
   ↓
7. 下单前验证 (最小量、交易时间、资金)
   ↓
8. 计算订单价格
   ↓
9. 执行双边订单 (Binance + Bybit)
   ↓
10. 订单状态检查
   ↓
11. 追单机制 (如需要)
   ↓
12. 数据库记录
   ↓
13. WebSocket 通知前端
   ↓
14. 前端更新UI
```

---

## 📊 策略对比表

| 特性 | 正向套利 | 反向套利 | 平仓所有持仓 |
|------|---------|---------|------------|
| **开仓方向** | Binance 多 + Bybit 空 | Binance 空 + Bybit 多 | 反向平仓 |
| **触发条件** | bybit_ask - binance_bid | binance_ask - bybit_bid | 手动触发 |
| **订单类型** | LIMIT | LIMIT | LIMIT |
| **追单机制** | ✅ 支持 | ✅ 支持 | ❌ 不支持 |
| **阶梯策略** | ✅ 支持 | ✅ 支持 | ❌ 不适用 |
| **批量执行** | ✅ 支持 | ✅ 支持 | ✅ 支持 |
| **风险等级** | 中 | 中 | 高 (紧急功能) |

---

## 🔗 相关文件

### 前端
- `frontend/src/components/trading/StrategyPanel.vue` - 套利策略面板
- `frontend/src/components/trading/ManualTrading.vue` - 手动交易面板
- `frontend/src/stores/market.js` - 市场数据状态管理

### 后端
- `backend/app/services/arbitrage_strategy.py` - 套利策略服务
- `backend/app/services/order_executor.py` - 订单执行器
- `backend/app/services/mt5_client.py` - MT5 客户端
- `backend/app/services/binance_client.py` - Binance 客户端
- `backend/app/api/v1/trading.py` - 交易API
- `backend/app/api/v1/strategies.py` - 策略API

---

**报告生成**: Claude Sonnet 4.6
**最后更新**: 2026-02-26
