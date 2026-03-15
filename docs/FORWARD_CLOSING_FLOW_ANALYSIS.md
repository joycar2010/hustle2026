# 正向平仓执行流程分析

## 问题描述
用户点击"启用正向平仓"按钮后，Binance成功挂单平仓（订单号1374422735、1374419677），但Bybit没有平仓，且单腿提醒没有触发。

## 完整执行流程

### 1. 前端触发 (StrategyPanel.vue)

**用户操作：** 点击"启用正向平仓"按钮

**代码位置：** `frontend/src/components/trading/StrategyPanel.vue:1228`

```javascript
async function toggleClosing() {
  if (config.value.closingEnabled) {
    // 禁用逻辑...
  } else {
    // 启用逻辑
    // 1. 验证账户
    const accountValidation = validateAccountsForExecution()
    // 2. 验证配置
    const configValidation = validateLadderConfig('closing')
    // 3. 检查持仓是否足够
    const positionCheck = await checkPositionForClosing()

    // 启用策略
    config.value.closingEnabled = true
    triggerCount.value.closing = 0
  }
}
```

### 2. 触发器累积 (StrategyPanel.vue)

**触发条件检测：** 每50ms检查一次点差

**代码位置：** `frontend/src/components/trading/StrategyPanel.vue:800-820`

```javascript
// 监听市场数据变化
watch(() => marketStore.marketData, (newData) => {
  // 计算点差
  closingSpread.value = spreads.forwardClosing

  // 如果启用了平仓策略
  if (config.value.closingEnabled && !executingClosing.value) {
    // 检查点差是否满足阈值
    if (closingSpread.value <= currentLadder.threshold) {
      triggerCount.value.closing++  // 累积触发次数

      // 达到触发次数要求
      if (triggerCount.value.closing >= config.value.closingSyncQty) {
        executeLadderClosing(currentLadderIdx, currentLadder)
        triggerCount.value.closing = 0
      }
    } else {
      triggerCount.value.closing = 0  // 重置
    }
  }
})
```

### 3. 执行平仓 (StrategyPanel.vue)

**代码位置：** `frontend/src/components/trading/StrategyPanel.vue:1456-1575`

```javascript
async function executeLadderClosing(ladderIndex, ladder) {
  executingClosing.value = true

  // 准备执行数据
  const executionData = {
    binance_account_id: binanceAccount.account_id,
    bybit_account_id: bybitMT5Account.account_id,
    quantity: batchQty,
    ladder_index: ladderIndex
  }

  // 调用后端API
  const response = await api.post(`/api/v1/strategies/close/forward`, executionData)

  // 处理响应
  if (response.data.success) {
    // 成功：更新进度
    const binanceFilled = response.data.binance_filled_qty || 0
    const bybitFilled = response.data.bybit_filled_qty || 0

    // 如果两边都没成交，保持策略启用等待重试
    if (binanceFilled === 0 && bybitFilled === 0) {
      return  // 不禁用策略
    }

    // 更新阶梯进度
    ladderProgress.value.closing.completedQty += Math.min(binanceFilled, bybitFilled)
  } else {
    // 失败：禁用策略
    config.value.closingEnabled = false
  }
}
```

### 4. 后端API处理 (strategies.py)

**API端点：** `POST /api/v1/strategies/close/forward`

**代码位置：** `backend/app/api/v1/strategies.py:661-735`

```python
@router.post("/close/forward")
async def close_forward_position(request: ClosePositionRequest, ...):
    # 1. 获取账户
    binance_account = ...
    bybit_account = ...

    # 2. 检查是否可以平仓
    can_close = position_manager.check_can_close(...)

    # 3. 获取当前市场价格
    market_data = await market_data_service.get_current_spread()
    binance_price = market_data.binance_quote.ask_price + 0.01  # MAKER价格
    bybit_price = market_data.bybit_quote.ask_price

    # 4. 执行订单
    result = await order_executor_v2.execute_forward_closing(
        binance_account=binance_account,
        bybit_account=bybit_account,
        quantity=request.quantity,
        binance_price=binance_price,
        bybit_price=bybit_price,
        db=db
    )

    # 5. 记录持仓变化
    if result.get("success"):
        position_manager.record_closing(...)

        # 6. 检查单腿并发送告警
        if result.get("is_single_leg"):
            await send_single_leg_alert(...)

    return result
```

### 5. 订单执行器 (order_executor_v2.py)

**代码位置：** `backend/app/services/order_executor_v2.py:361-492`

```python
async def execute_forward_closing(self, ...):
    # Step 0: 预检查Bybit SHORT持仓
    bybit_positions = mt5_client.get_positions("XAUUSD.s")
    short_positions = [p for p in bybit_positions if p['type'] == 1]

    if not short_positions:
        return {
            "success": False,
            "error": "Bybit没有SHORT持仓可以平仓",
            "is_single_leg": False
        }

    # Step 1: 下Binance限价SELL单（平LONG仓）
    binance_result = await self.base_executor.place_binance_order(
        symbol="XAUUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity=quantity,
        price=binance_price,
        position_side="LONG",
        post_only=True  # 强制MAKER模式
    )

    binance_order_id = binance_result["order_id"]

    # Step 2: 监控Binance订单（0.6秒超时）
    binance_filled_qty = await self._monitor_binance_order(
        binance_account,
        "XAUUSDT",
        binance_order_id,
        self.binance_timeout  # 0.6秒
    )

    # Step 3: 如果Binance未成交，取消订单并返回
    if binance_filled_qty == 0:
        await self.base_executor.cancel_binance_order(...)
        return {
            "success": True,
            "binance_filled_qty": 0,
            "bybit_filled_qty": 0,
            "is_single_leg": False,
            "message": "Binance未匹配到订单，取消策略执行，下次再试!"
        }

    # Step 4: Binance成交后，下Bybit市价BUY单（平SHORT仓）
    bybit_quantity = quantity_converter.xau_to_lot(binance_filled_qty)
    bybit_filled_qty = await self._execute_bybit_market_buy(
        bybit_account,
        "XAUUSD.s",
        bybit_quantity,
        close_position=True  # 平仓模式
    )

    # Step 5: 检查Bybit是否成交
    if bybit_filled_qty == 0:
        return {
            "success": False,
            "error": "Bybit订单未成交",
            "binance_filled_qty": binance_filled_qty,
            "bybit_filled_qty": 0,
            "binance_order_id": binance_order_id,
            "is_single_leg": True,  # 标记为单腿
            "message": "Bybit订单已取消，等待下次重试"
        }

    # Step 6: 检查是否部分成交（单腿）
    bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_qty)
    is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.95

    return {
        "success": True,
        "binance_filled_qty": binance_filled_qty,
        "bybit_filled_qty": bybit_filled_qty,
        "binance_order_id": binance_order_id,
        "is_single_leg": is_single_leg,
        "single_leg_details": {...} if is_single_leg else None
    }
```

### 6. Bybit订单执行 (_execute_bybit_market_buy)

**代码位置：** `backend/app/services/order_executor_v2.py:530-609`

```python
async def _execute_bybit_market_buy(self, account, symbol, quantity, close_position=True):
    total_filled = 0
    remaining = quantity

    # 最多重试2次（初始 + 1次重试）
    for attempt in range(self.max_retries + 1):
        # 1. 下市价单
        result = await self.base_executor.place_bybit_order(
            account=account,
            symbol=symbol,
            side="Buy",
            order_type="Market",
            quantity=str(remaining),
            close_position=close_position
        )

        if not result["success"]:
            break  # 下单失败，退出

        order_id = result["order_id"]
        ticket = int(order_id)

        # 2. 等待成交（0.1秒 + 0.3秒MT5处理）
        await asyncio.sleep(self.bybit_timeout)  # 0.1秒
        await asyncio.sleep(0.3)  # MT5处理时间

        # 3. 检查MT5实际成交量
        volume_check = await self._check_mt5_filled_volume(account, ticket, remaining)
        actual_filled = volume_check["actual_filled"]

        if actual_filled > 0:
            total_filled += actual_filled

            if actual_filled >= remaining * 0.95:
                break  # 95%以上视为完全成交

            remaining -= actual_filled  # 更新剩余量
        else:
            break  # 未成交，退出

    return total_filled
```

### 7. MT5订单下单 (order_executor.py)

**代码位置：** `backend/app/services/order_executor.py:70-175`

```python
async def place_bybit_order(self, account, symbol, side, order_type, quantity, close_position=False):
    mt5_client = market_data_service.mt5_client

    # 如果是平仓订单，查找要平的持仓
    position_ticket = None
    if close_position:
        # 获取所有持仓
        all_positions = mt5_client.get_positions(symbol)
        logger.info(f"Current positions for {symbol}: {all_positions}")

        # 查找要平的持仓
        position_ticket = mt5_client.find_position_to_close(symbol, side)

        if position_ticket:
            logger.info(f"Found position to close: ticket={position_ticket}")
        else:
            logger.error(f"CRITICAL: No position found to close for {symbol} {side}")
            return {
                "success": False,
                "error": f"No position found to close for {symbol}"
            }

    # 下单
    logger.info(f"Bybit order params: symbol={symbol}, side={side}, quantity={quantity}, close_position={close_position}, position_ticket={position_ticket}")

    result = mt5_client.send_order(
        symbol=symbol,
        order_type=mt5_order_type,
        volume=float(quantity),
        price=None,  # 市价单
        position_ticket=position_ticket
    )

    if result is None:
        return {"success": False, "error": "MT5 order failed: no result returned"}

    if result.get("retcode") != mt5.TRADE_RETCODE_DONE:
        return {
            "success": False,
            "error": f"MT5 order error: retcode={result.get('retcode')}, comment={result.get('comment')}"
        }

    return {
        "success": True,
        "order_id": str(result.get("order")),
        "data": result
    }
```

## 单腿检测逻辑

### 检测条件

**代码位置：** `backend/app/services/order_executor_v2.py:465-478`

```python
# 情况1：Bybit完全未成交
if bybit_filled_qty == 0:
    return {
        "success": False,
        "is_single_leg": True,  # 标记为单腿
        "binance_filled_qty": binance_filled_qty,
        "bybit_filled_qty": 0
    }

# 情况2：Bybit部分成交（成交量 < Binance成交量的95%）
bybit_filled_xau = quantity_converter.lot_to_xau(bybit_filled_qty)
is_single_leg = binance_filled_qty > 0 and bybit_filled_xau < binance_filled_qty * 0.95
```

### 单腿告警触发

**代码位置：** `backend/app/api/v1/strategies.py:722-733`

```python
# 只有在success=True且is_single_leg=True时才触发告警
if result.get("success"):
    if result.get("is_single_leg"):
        await send_single_leg_alert(
            user_id=user_id,
            strategy_type="正向套利",
            action="平仓",
            details=details,
            db=db
        )
```

## 问题分析

### 为什么单腿告警没有触发？

根据执行流程，单腿告警触发需要满足两个条件：
1. `result.get("success") == True`
2. `result.get("is_single_leg") == True`

但是，当Bybit订单完全未成交时（`bybit_filled_qty == 0`），`execute_forward_closing`返回：
```python
{
    "success": False,  # ❌ success=False
    "is_single_leg": True,
    "binance_filled_qty": binance_filled_qty,
    "bybit_filled_qty": 0
}
```

**关键问题：** `success=False`导致API层的单腿告警检查被跳过！

```python
# strategies.py:714
if result.get("success"):  # ❌ 这里是False，不会进入
    if result.get("is_single_leg"):
        await send_single_leg_alert(...)
```

### 为什么Bybit订单没有执行？

可能的原因：

1. **MT5查找持仓失败**
   - `find_position_to_close`没有找到SHORT持仓
   - 返回`{"success": False, "error": "No position found"}`
   - `_execute_bybit_market_buy`中`result["success"]=False`，直接break

2. **MT5下单失败**
   - `mt5_client.send_order`返回None
   - 或者`retcode != TRADE_RETCODE_DONE`

3. **MT5成交检查失败**
   - `_check_mt5_filled_volume`返回`actual_filled=0`
   - 可能是MT5连接问题或延迟过高

### 实际情况

根据我的调查：
- Binance订单成交时间：19:33:42 和 19:33:51
- MT5在该时间段**没有任何BUY订单记录**
- 说明Bybit订单根本没有下单成功

最可能的原因是：
1. MT5查找SHORT持仓时失败（虽然预检查通过了）
2. 或者MT5下单时返回了错误

## 修复建议

### 1. 修复单腿告警逻辑

**问题：** `success=False`时不触发单腿告警

**修复方案：** 将单腿检查移到`success`判断之外

```python
# strategies.py
result = await order_executor_v2.execute_forward_closing(...)

# 记录持仓（只在success时）
if result.get("success"):
    position_manager.record_closing(...)

# 单腿检查（无论success与否）
if result.get("is_single_leg"):
    await send_single_leg_alert(...)

return result
```

### 2. 增强日志记录

在关键位置添加日志：
- Bybit下单前：记录持仓查找结果
- Bybit下单后：记录MT5返回结果
- MT5成交检查：记录实际成交量

### 3. 增加Bybit下单失败的详细错误信息

在`_execute_bybit_market_buy`中记录失败原因：
```python
if not result["success"]:
    logger.error(f"Bybit order failed: {result.get('error')}")
    break
```

## 总结

**正向平仓执行流程：**
1. 前端触发 → 2. 累积触发次数 → 3. 调用后端API → 4. 预检查Bybit持仓 → 5. 下Binance限价单 → 6. 监控Binance成交 → 7. 下Bybit市价单 → 8. 检查Bybit成交 → 9. 判断单腿 → 10. 发送告警

**单腿告警未触发原因：**
- `success=False`时，API层跳过了单腿告警检查
- 需要修改逻辑，让单腿告警在`success=False`时也能触发

**Bybit订单未执行原因：**
- MT5查找持仓失败或下单失败
- 需要检查日志确认具体失败原因
