# 单腿告警修复总结

## 修复时间
2026-03-10

## 问题描述
用户点击"启用正向平仓"按钮后，Binance成功挂单平仓（订单号1374422735、1374419677），但Bybit没有平仓，造成单腿交易，但系统没有触发单腿告警。

## 根本原因

### 1. 单腿告警逻辑缺陷

**问题代码位置：** `backend/app/api/v1/strategies.py`

在所有4个执行endpoint中（反向开仓、反向平仓、正向开仓、正向平仓），单腿检查被错误地包裹在`success`判断内：

```python
# 错误的逻辑
if result.get("success"):  # ❌ 当Bybit未成交时，success=False
    position_manager.record_closing(...)

    if result.get("is_single_leg"):  # ❌ 永远不会执行
        await send_single_leg_alert(...)
```

当Bybit完全未成交时，`execute_forward_closing`返回：
```python
{
    "success": False,  # ❌ 导致告警被跳过
    "is_single_leg": True,
    "binance_filled_qty": 2.0,
    "bybit_filled_qty": 0
}
```

**结果：** 单腿告警检查被跳过，用户无法及时得知单腿风险。

### 2. 日志记录不足

**问题：**
- 关键执行步骤没有日志记录
- Bybit订单失败原因不明确
- 无法追溯历史执行问题

## 修复内容

### 1. 修复单腿告警逻辑

**修改文件：** `backend/app/api/v1/strategies.py`

**修改的endpoint：**
- `/execute/reverse/opening` - 反向开仓
- `/close/reverse` - 反向平仓
- `/execute/forward/opening` - 正向开仓
- `/close/forward` - 正向平仓

**修复后的逻辑：**
```python
# 正确的逻辑
# 5. Record position if successful
if result.get("success"):
    position_manager.record_closing(...)

# 6. Check for single-leg trade and send alert (regardless of success status)
if result.get("is_single_leg"):  # ✅ 无论success与否都检查
    import datetime
    details = result.get("single_leg_details", {})
    details["timestamp"] = datetime.datetime.utcnow().isoformat()
    await send_single_leg_alert(
        user_id=user_id,
        strategy_type="正向套利",
        action="平仓",
        details=details,
        db=db
    )

return result
```

**关键改进：**
- 将单腿检查移到`success`判断之外
- 无论执行成功与否，只要检测到单腿就立即告警
- 确保用户能及时收到单腿风险通知

### 2. 增强日志记录

**修改文件：** `backend/app/services/order_executor_v2.py`

**添加的日志：**

#### execute_forward_closing方法
```python
logger.info(f"[FORWARD_CLOSING] Starting execution: quantity={quantity}, binance_price={binance_price}")
logger.info(f"[FORWARD_CLOSING] Bybit positions check: total={len(bybit_positions)}, short={len(short_positions)}")
logger.info(f"[FORWARD_CLOSING] Position check: total_short={total_short_volume} Lot, required={required_volume} Lot")
logger.info(f"[FORWARD_CLOSING] Placing Binance SELL order: quantity={quantity}, price={binance_price}")
logger.info(f"[FORWARD_CLOSING] Binance order placed: order_id={binance_order_id}")
logger.info(f"[FORWARD_CLOSING] Binance filled: {binance_filled_qty} XAU")
logger.info(f"[FORWARD_CLOSING] Placing Bybit BUY order: quantity={bybit_quantity} Lot")
logger.info(f"[FORWARD_CLOSING] Bybit filled: {bybit_filled_qty} Lot")
logger.error(f"[FORWARD_CLOSING] SINGLE LEG DETECTED: Binance filled {binance_filled_qty} XAU, Bybit filled 0 Lot")
logger.warning(f"[FORWARD_CLOSING] PARTIAL SINGLE LEG: Binance={binance_filled_qty} XAU, Bybit={bybit_filled_xau} XAU")
```

#### _execute_bybit_market_buy方法
```python
logger.info(f"[BYBIT_BUY] Starting: quantity={quantity} Lot, close_position={close_position}")
logger.info(f"[BYBIT_BUY] Attempt {attempt + 1}/{self.max_retries + 1}: remaining={remaining} Lot")
logger.error(f"[BYBIT_BUY] Order placement failed: {result.get('error')}")
logger.info(f"[BYBIT_BUY] Order placed: ticket={ticket}")
logger.info(f"[BYBIT_BUY] Ticket {ticket} filled: {actual_filled} Lot (partial={is_partial})")
logger.warning(f"[BYBIT_BUY] Not fully filled after {self.max_retries + 1} attempts")
logger.warning(f"[BYBIT_BUY] No fill detected for ticket {ticket}, stopping retries")
logger.info(f"[BYBIT_BUY] Completed: total_filled={total_filled} Lot")
```

**日志改进：**
- 统一使用`[FORWARD_CLOSING]`和`[BYBIT_BUY]`前缀，便于过滤
- 记录所有关键步骤：持仓检查、订单下单、成交确认
- 记录失败原因和错误详情
- 使用不同日志级别：INFO（正常）、WARNING（部分成交）、ERROR（失败/单腿）

## 测试验证

### 测试场景1：Bybit完全未成交
**预期行为：**
1. Binance订单成交
2. Bybit订单未成交
3. 返回`{"success": False, "is_single_leg": True}`
4. ✅ 触发单腿告警（修复前不会触发）
5. 用户收到WebSocket通知和飞书通知

### 测试场景2：Bybit部分成交
**预期行为：**
1. Binance订单成交2.0 XAU
2. Bybit订单成交1.5 XAU（< 95%）
3. 返回`{"success": True, "is_single_leg": True}`
4. ✅ 触发单腿告警
5. 用户收到通知

### 测试场景3：正常成交
**预期行为：**
1. Binance订单成交2.0 XAU
2. Bybit订单成交2.0 XAU（≥ 95%）
3. 返回`{"success": True, "is_single_leg": False}`
4. ✅ 不触发单腿告警
5. 正常记录持仓

## 日志示例

### 正常执行日志
```
[FORWARD_CLOSING] Starting execution: quantity=2.0, binance_price=5183.26
[FORWARD_CLOSING] Bybit positions check: total=1, short=1
[FORWARD_CLOSING] Position check: total_short=7.08 Lot, required=2.0 Lot
[FORWARD_CLOSING] Placing Binance SELL order: quantity=2.0, price=5183.26
[FORWARD_CLOSING] Binance order placed: order_id=1374422735
[FORWARD_CLOSING] Binance filled: 2.0 XAU
[FORWARD_CLOSING] Placing Bybit BUY order: quantity=2.0 Lot (from 2.0 XAU)
[BYBIT_BUY] Starting: quantity=2.0 Lot, close_position=True
[BYBIT_BUY] Attempt 1/2: remaining=2.0 Lot
[BYBIT_BUY] Order placed: ticket=10011075371
[BYBIT_BUY] Ticket 10011075371 filled: 2.0 Lot (partial=False)
[BYBIT_BUY] Completed: total_filled=2.0 Lot
[FORWARD_CLOSING] Bybit filled: 2.0 Lot
[FORWARD_CLOSING] Execution completed successfully: Binance=2.0 XAU, Bybit=2.0 XAU
```

### 单腿情况日志
```
[FORWARD_CLOSING] Starting execution: quantity=2.0, binance_price=5183.26
[FORWARD_CLOSING] Bybit positions check: total=1, short=1
[FORWARD_CLOSING] Position check: total_short=7.08 Lot, required=2.0 Lot
[FORWARD_CLOSING] Placing Binance SELL order: quantity=2.0, price=5183.26
[FORWARD_CLOSING] Binance order placed: order_id=1374422735
[FORWARD_CLOSING] Binance filled: 2.0 XAU
[FORWARD_CLOSING] Placing Bybit BUY order: quantity=2.0 Lot (from 2.0 XAU)
[BYBIT_BUY] Starting: quantity=2.0 Lot, close_position=True
[BYBIT_BUY] Attempt 1/2: remaining=2.0 Lot
[BYBIT_BUY] Order placement failed: No SHORT position found to close for XAUUSD.s
[BYBIT_BUY] Completed: total_filled=0.0 Lot
[FORWARD_CLOSING] Bybit filled: 0.0 Lot
[FORWARD_CLOSING] SINGLE LEG DETECTED: Binance filled 2.0 XAU, Bybit filled 0 Lot
```

## 影响范围

**修改的文件：**
1. `backend/app/api/v1/strategies.py` - 4个endpoint的单腿检查逻辑
2. `backend/app/services/order_executor_v2.py` - 增强日志记录

**影响的功能：**
- 反向开仓单腿告警
- 反向平仓单腿告警
- 正向开仓单腿告警
- 正向平仓单腿告警

**向后兼容性：**
- ✅ 完全向后兼容
- ✅ 不影响现有功能
- ✅ 只是修复了告警逻辑缺陷

## 部署步骤

1. 停止后端服务
2. 更新代码
3. 重启后端服务
4. 验证日志输出正常

## 后续建议

### 1. 增加单腿恢复机制
当检测到单腿时，自动尝试补单：
- 记录单腿详情到数据库
- 提供手动补单接口
- 或自动重试Bybit订单

### 2. 增加预警机制
在Bybit订单下单前：
- 再次确认持仓存在
- 检查MT5连接状态
- 验证账户余额充足

### 3. 增加监控告警
- 监控单腿发生频率
- 如果频繁发生，触发系统告警
- 自动暂停策略执行

### 4. 优化日志查询
- 建立日志索引
- 提供日志查询界面
- 支持按订单号、时间范围查询

## 总结

本次修复解决了单腿告警不触发的关键问题，并增强了日志记录能力。修复后：

✅ 单腿情况能及时告警
✅ 详细日志便于问题追溯
✅ 向后兼容，不影响现有功能
✅ 覆盖所有4个执行endpoint

**风险降低：** 用户能及时发现单腿风险，避免更大损失。
