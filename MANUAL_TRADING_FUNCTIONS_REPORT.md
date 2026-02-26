# 手动交易功能详细说明

## 概述

本文档详细说明 ManualTrading.vue 组件中的四个核心手动交易功能：
1. **买入开多** (Buy Long)
2. **卖出开空** (Sell Short)
3. **平仓所有持仓** (Close All Positions)
4. **取消所有挂单** (Cancel All Orders)

这些功能为紧急情况下的手动干预提供了快速通道，允许交易员直接在 Binance 或 Bybit MT5 平台上执行交易操作。

---

## 1. 买入开多 (Buy Long)

### 功能描述
在选定的交易平台上以限价单方式买入开多仓位。

### 前端实现
**文件**: `frontend/src/components/trading/ManualTrading.vue`

```javascript
// 行 183-199
async function executeTrade(side) {
  if (loading.value) return
  loading.value = true
  try {
    await api.post('/api/v1/trading/manual/order', {
      exchange: exchange.value,  // 'binance' 或 'bybit'
      side,                      // 'buy' 或 'sell'
      quantity: quantity.value,  // 用户输入的数量
    })
    showStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '下单失败', false)
  } finally {
    loading.value = false
  }
}
```

### 后端 API 端点
**文件**: `backend/app/api/v1/trading.py`
**端点**: `POST /api/v1/trading/manual/order`
**行数**: 560-628

### 执行流程

#### 步骤 1: 账户选择
```python
# 行 568-586
# 获取用户所有账户
accounts, accounts_map = await _get_user_accounts(db, current_user.user_id)

# 查找匹配的账户
if req.account_id:
    account = accounts_map.get(req.account_id)
else:
    # 自动选择第一个匹配平台的活跃账户
    for acc in accounts:
        if req.exchange == "binance" and acc.platform_id == 1 and acc.is_active:
            account = acc
            break
        if req.exchange == "bybit" and acc.platform_id == 2 and acc.is_active:
            account = acc
            break
```

#### 步骤 2: 价格计算（自动定价逻辑）

**Binance 买入开多**:
```python
# 行 589-597
quote = await market_data_service.get_binance_quote("XAUUSDT")
symbol = "XAUUSDT"
# 买入: bid + 0.01 (略高于买价，确保成交)
price = round(quote.bid_price + 0.01, 2)
position_side = "LONG"
result = await order_executor.place_binance_order(
    account, symbol, "BUY", "LIMIT", req.quantity, price, position_side="LONG"
)
```

**Bybit 买入开多**:
```python
# 行 598-604
quote = await market_data_service.get_bybit_quote("XAUUSD.s")
symbol = "XAUUSD.s"
# 买入: bid + 0.01
price = round(quote.bid_price + 0.01, 2)
result = await order_executor.place_bybit_order(
    account, symbol, "buy", "Limit", str(req.quantity), str(price)
)
```

#### 步骤 3: 数据库记录
```python
# 行 610-622
order_record = OrderRecord(
    account_id=account.account_id,
    symbol=symbol,
    order_side="buy",
    order_type="limit",
    price=price,
    qty=req.quantity,
    status="new",
    source="manual",  # 标记为手动交易
    platform_order_id=str(result.get("order_id", "")),
)
db.add(order_record)
await db.commit()
```

### 价格策略
- **买入开多**: `bid_price + 0.01` (略高于市场买价，提高成交概率)
- 使用限价单而非市价单，避免滑点过大

---

## 2. 卖出开空 (Sell Short)

### 功能描述
在选定的交易平台上以限价单方式卖出开空仓位。

### 执行流程
与买入开多类似，但价格计算逻辑不同：

#### 价格计算

**Binance 卖出开空**:
```python
# 行 593
# 卖出: ask - 0.01 (略低于卖价，确保成交)
price = round(quote.ask_price - 0.01, 2)
position_side = "SHORT"
result = await order_executor.place_binance_order(
    account, symbol, "SELL", "LIMIT", req.quantity, price, position_side="SHORT"
)
```

**Bybit 卖出开空**:
```python
# 行 601
# 卖出: ask - 0.01
price = round(quote.ask_price - 0.01, 2)
result = await order_executor.place_bybit_order(
    account, symbol, "sell", "Limit", str(req.quantity), str(price)
)
```

### 价格策略
- **卖出开空**: `ask_price - 0.01` (略低于市场卖价，提高成交概率)

---

## 3. 平仓所有持仓 (Close All Positions)

### 功能描述
一键平仓用户在 Binance 和 Bybit MT5 上的所有持仓，用于紧急风险控制。

### 前端实现
```javascript
// 行 201-214
async function closeAllPositions() {
  if (!confirm('确定要平仓所有持仓吗？')) return  // 二次确认
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/close-all')
    showStatus(`平仓指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '平仓失败', false)
  } finally {
    loading.value = false
  }
}
```

### 后端 API 端点
**文件**: `backend/app/api/v1/trading.py`
**端点**: `POST /api/v1/trading/manual/close-all`
**行数**: 631-717

### 执行流程

#### Binance 平仓逻辑
```python
# 行 645-679
if account.platform_id == 1:
    # 获取所有持仓
    client = BinanceFuturesClient(account.api_key, account.api_secret)
    positions = await client.get_position_risk("XAUUSDT")

    for pos in positions:
        amt = float(pos.get("positionAmt", 0))
        if amt == 0:
            continue  # 跳过无持仓

        # 反向平仓
        side = "SELL" if amt > 0 else "BUY"  # 多仓用卖单平，空仓用买单平
        position_side = "LONG" if amt > 0 else "SHORT"
        qty = abs(amt)

        # 获取实时报价
        quote = await market_data_service.get_binance_quote("XAUUSDT")
        # 平多仓: ask - 0.01, 平空仓: bid + 0.01
        price = round(quote.ask_price - 0.01, 2) if side == "SELL" else round(quote.bid_price + 0.01, 2)

        # 执行平仓订单
        r = await order_executor.place_binance_order(
            account, "XAUUSDT", side, "LIMIT", qty, price, position_side=position_side
        )

        # 保存订单记录
        if r.get("success"):
            order_record = OrderRecord(
                account_id=account.account_id,
                symbol="XAUUSDT",
                order_side=side.lower(),
                order_type="limit",
                price=price,
                qty=qty,
                status="new",
                source="manual",
                platform_order_id=str(r.get("order_id", "")),
            )
            db.add(order_record)
        results.append({"exchange": "binance", "account": account.account_name, **r})
```

#### Bybit MT5 平仓逻辑
```python
# 行 681-711
elif account.platform_id == 2:
    # 获取所有持仓
    loop = asyncio.get_event_loop()
    positions = await loop.run_in_executor(
        None, lambda: mt5.positions_get(symbol="XAUUSD.s")
    )

    if positions:
        quote = await market_data_service.get_bybit_quote("XAUUSD.s")
        for pos in positions:
            # 反向平仓
            side = "Sell" if pos.type == mt5.POSITION_TYPE_BUY else "Buy"
            # 平多仓: ask - 0.01, 平空仓: bid + 0.01
            price = round(quote.ask_price - 0.01, 2) if side == "Sell" else round(quote.bid_price + 0.01, 2)

            # 执行平仓订单
            r = await order_executor.place_bybit_order(
                account, "XAUUSD.s", side, "Limit", str(pos.volume), str(price)
            )

            # 保存订单记录
            if r.get("success"):
                order_record = OrderRecord(
                    account_id=account.account_id,
                    symbol="XAUUSD.s",
                    order_side=side.lower(),
                    order_type="limit",
                    price=price,
                    qty=pos.volume,
                    status="new",
                    source="manual",
                    platform_order_id=str(r.get("order_id", "")),
                )
                db.add(order_record)
            results.append({"exchange": "bybit", "account": account.account_name, **r})
```

### 平仓价格策略
- **平多仓**: `ask_price - 0.01` (卖出平仓，略低于卖价)
- **平空仓**: `bid_price + 0.01` (买入平仓，略高于买价)
- 目标：快速成交，优先风险控制而非价格优化

### 安全机制
1. **前端二次确认**: `confirm('确定要平仓所有持仓吗？')`
2. **遍历所有账户**: 自动处理用户在两个平台上的所有活跃账户
3. **跳过零持仓**: `if amt == 0: continue`
4. **数据库事务**: 所有订单记录统一提交 `await db.commit()`

---

## 4. 取消所有挂单 (Cancel All Orders)

### 功能描述
一键取消用户在 Binance 和 Bybit MT5 上的所有挂单（未成交订单）。

### 前端实现
```javascript
// 行 216-229
async function cancelAllOrders() {
  if (!confirm('确定要取消所有挂单吗？')) return  // 二次确认
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/cancel-all')
    showStatus(`撤单指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '撤单失败', false)
  } finally {
    loading.value = false
  }
}
```

### 后端 API 端点
**文件**: `backend/app/api/v1/trading.py`
**端点**: `POST /api/v1/trading/manual/cancel-all`
**行数**: 868-921

### 执行流程

#### Binance 撤单逻辑
```python
# 行 882-891
if account.platform_id == 1:
    client = BinanceFuturesClient(account.api_key, account.api_secret)
    try:
        # 批量取消所有挂单
        r = await client.cancel_all_orders("XAUUSDT")
        results.append({
            "exchange": "binance",
            "account": account.account_name,
            "success": True,
            "data": r
        })
    except Exception as e:
        results.append({
            "exchange": "binance",
            "account": account.account_name,
            "success": False,
            "error": str(e)
        })
    finally:
        await client.close()
```

#### Bybit MT5 撤单逻辑
```python
# 行 893-903
elif account.platform_id == 2:
    loop = asyncio.get_event_loop()
    # 获取所有挂单
    orders = await loop.run_in_executor(
        None, lambda: mt5.orders_get(symbol="XAUUSD.s")
    )

    if orders:
        # 逐个取消挂单
        for order in orders:
            r = await order_executor.cancel_bybit_order(
                account, "XAUUSD.s", str(order.ticket)
            )
            results.append({
                "exchange": "bybit",
                "account": account.account_name,
                **r
            })
    else:
        results.append({
            "exchange": "bybit",
            "account": account.account_name,
            "success": True,
            "data": "no orders"
        })
```

#### 数据库订单状态更新
```python
# 行 905-917
# 将数据库中所有 pending/new 状态的订单标记为 manually_processed
account_ids = [acc.account_id for acc in accounts if acc.is_active]
if account_ids:
    pending_orders_result = await db.execute(
        select(OrderRecord).filter(
            OrderRecord.account_id.in_(account_ids),
            OrderRecord.status.in_(["new", "pending"])
        )
    )
    pending_orders = pending_orders_result.scalars().all()
    for order in pending_orders:
        order.status = "manually_processed"  # 标记为手动处理
    await db.commit()

return {
    "success": True,
    "results": results,
    "db_orders_processed": len(pending_orders) if account_ids else 0
}
```

### 安全机制
1. **前端二次确认**: `confirm('确定要取消所有挂单吗？')`
2. **异常处理**: Binance 撤单失败不影响 Bybit 撤单继续执行
3. **数据库同步**: 自动更新数据库中的订单状态为 `manually_processed`
4. **返回详细结果**: 返回每个账户的撤单结果，便于追踪

---

## 通用特性

### 1. 实时状态反馈
所有操作都通过 `showStatus()` 函数提供即时反馈：
```javascript
function showStatus(msg, ok = true) {
  statusMsg.value = msg
  statusOk.value = ok
  setTimeout(() => { statusMsg.value = '' }, 4000)  // 4秒后自动消失
}
```

### 2. WebSocket 实时更新
```javascript
// 行 146-164
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'order_update') {
    handleOrderUpdate(message.data)
  }
})

function handleOrderUpdate(orderData) {
  if (orderData.source === 'manual') {
    const index = recentOrders.value.findIndex(o => o.id === orderData.id)
    if (index !== -1) {
      recentOrders.value[index] = { ...recentOrders.value[index], ...orderData }
    } else {
      recentOrders.value = [orderData, ...recentOrders.value].slice(0, 4)
    }
  }
}
```

### 3. 防重复提交
所有函数都使用 `loading` 状态防止重复点击：
```javascript
if (loading.value) return
loading.value = true
try {
  // 执行操作
} finally {
  loading.value = false
}
```

### 4. 订单来源标记
所有手动交易订单在数据库中标记为 `source="manual"`，便于后续筛选和分析。

---

## 价格计算总结

| 操作类型 | 价格计算公式 | 说明 |
|---------|------------|------|
| 买入开多 | `bid_price + 0.01` | 略高于买价，提高成交率 |
| 卖出开空 | `ask_price - 0.01` | 略低于卖价，提高成交率 |
| 平多仓 | `ask_price - 0.01` | 卖出平仓，略低于卖价 |
| 平空仓 | `bid_price + 0.01` | 买入平仓，略高于买价 |

**设计理念**:
- 使用限价单而非市价单，避免极端滑点
- 价格偏移 0.01 美元，在成交速度和价格优化之间取得平衡
- 紧急平仓优先考虑成交速度，而非价格最优

---

## 安全建议

1. **谨慎使用平仓功能**: 该功能会平掉所有持仓，包括套利策略的对冲仓位，可能导致单边风险暴露
2. **确认账户状态**: 操作前确认账户余额充足，避免因保证金不足导致平仓失败
3. **监控执行结果**: 操作后检查 "最近交易记录" 确认订单状态
4. **避免频繁操作**: 手动交易应仅用于紧急情况，频繁使用可能干扰自动化策略

---

## 相关文件

- **前端组件**: `frontend/src/components/trading/ManualTrading.vue`
- **后端路由**: `backend/app/api/v1/trading.py` (行 560-921)
- **订单执行器**: `backend/app/services/order_executor.py`
- **Binance 客户端**: `backend/app/services/binance_client.py`
- **MT5 客户端**: `backend/app/services/mt5_client.py`
- **数据模型**: `backend/app/models/order.py`

---

**生成时间**: 2026-02-26
**版本**: 1.0
