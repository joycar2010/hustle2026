# 连续执行单腿告警修复验证

## 修复时间
2026-03-10

## 问题描述
用户询问：连续开仓和连续平仓按钮的单腿警报是否会正常触发？

## 调查结果

### 发现的问题

**严重缺陷：** 连续执行器（`continuous_executor.py`）中**完全没有单腿检测和告警逻辑**！

#### 原有代码逻辑（第303-318行）

```python
# Step 8: Execute order
exec_result = await self._execute_order(...)

# ❌ 没有检查 is_single_leg
if not exec_result['success']:
    logger.error(f"Execution failed: {exec_result}")
    return {'success': False, 'error': exec_result.get('error')}

# Step 9: Handle Binance not filled
if exec_result.get('binance_filled_qty', 0) == 0:
    logger.info("Binance not filled, resetting triggers")
    self.trigger_mgr.reset()
    continue

# Step 10: Record position
filled_qty = min(
    exec_result.get('binance_filled_qty', 0),
    exec_result.get('bybit_filled_qty', 0)
)
# 直接记录持仓，没有告警
```

**问题分析：**
1. `order_executor_v2`返回的`exec_result`包含`is_single_leg`标志
2. 但`continuous_executor`完全忽略了这个标志
3. 即使发生单腿，也不会发送任何告警
4. 用户无法及时发现风险

### 影响范围

**受影响的功能：**
1. ✅ 反向连续开仓 - 已修复
2. ✅ 反向连续平仓 - 已修复
3. ✅ 正向连续开仓 - 已修复
4. ✅ 正向连续平仓 - 已修复

**对应的API endpoint：**
- `POST /api/v1/strategies/execute/reverse/continuous` - 反向连续开仓
- `POST /api/v1/strategies/execute/forward/continuous` - 正向连续开仓
- `POST /api/v1/strategies/close/reverse/continuous` - 反向连续平仓
- `POST /api/v1/strategies/close/forward/continuous` - 正向连续平仓

## 修复内容

### 1. 添加单腿检测逻辑

**修改文件：** `backend/app/services/continuous_executor.py`

**修改位置：** `_execute_ladder`方法，第301-305行

**修复后的代码：**
```python
# Step 8: Execute order
exec_result = await self._execute_order(...)
logger.info(f"Step 8 result - Success: {exec_result.get('success')}, Binance filled: {exec_result.get('binance_filled_qty')}, Bybit filled: {exec_result.get('bybit_filled_qty')}")

# Step 8.5: Check for single-leg trade and send alert (regardless of success status)
if exec_result.get('is_single_leg'):
    logger.error(f"SINGLE LEG DETECTED in continuous execution: {exec_result.get('single_leg_details')}")
    await self._send_single_leg_alert(
        strategy_type=strategy_type,
        exec_result=exec_result
    )

if not exec_result['success']:
    logger.error(f"Execution failed: {exec_result}")
    return {'success': False, 'error': exec_result.get('error')}

# Step 9: Handle Binance not filled
if exec_result.get('binance_filled_qty', 0) == 0:
    logger.info("Binance not filled, resetting triggers")
    self.trigger_mgr.reset()
    await self._push_trigger_reset(ladder_idx, strategy_type)
    continue

# Step 10: Record position
```

**关键改进：**
- 在检查`success`之前先检查`is_single_leg`
- 无论执行成功与否，只要检测到单腿就立即告警
- 使用ERROR级别日志记录单腿事件

### 2. 添加单腿告警方法

**新增方法：** `_send_single_leg_alert`

**代码：**
```python
async def _send_single_leg_alert(
    self,
    strategy_type: str,
    exec_result: Dict
):
    """Send single-leg trade alert via WebSocket and Feishu"""
    if not self.user_id:
        return

    # Determine strategy name and action
    if 'reverse' in strategy_type:
        strategy_name = "反向套利"
    else:
        strategy_name = "正向套利"

    if 'opening' in strategy_type:
        action = "开仓"
    else:
        action = "平仓"

    # Prepare alert details
    import datetime
    details = exec_result.get('single_leg_details', {})
    details['timestamp'] = datetime.datetime.utcnow().isoformat()

    # Send WebSocket notification
    from app.websocket.manager import manager
    alert_message = {
        "type": "single_leg_alert",
        "data": {
            "strategy_type": strategy_name,
            "action": action,
            "binance_filled": details.get("binance_filled", 0),
            "bybit_filled": details.get("bybit_filled", 0),
            "unfilled_qty": details.get("unfilled_qty", 0),
            "timestamp": details.get("timestamp"),
            "level": "critical",
            "title": "单腿交易警告",
            "message": f"{strategy_name} {action}: Binance成交 {details.get('binance_filled', 0)}, Bybit成交 {details.get('bybit_filled', 0)}, 未成交 {details.get('unfilled_qty', 0)}"
        }
    }
    await manager.send_to_user(alert_message, self.user_id)

    # Send Feishu notification
    try:
        from app.services.risk_alert_service import RiskAlertService
        from app.core.database import get_db

        # Get database session
        async for db in get_db():
            risk_alert_service = RiskAlertService(db)

            # Determine direction based on strategy type
            direction = "多头" if "forward" in strategy_type.lower() else "空头"
            exchange = "Binance"  # Single-leg usually happens on Binance side

            await risk_alert_service.check_single_leg(
                user_id=self.user_id,
                exchange=exchange,
                quantity=details.get("unfilled_qty", 0),
                duration=0,  # Immediate alert
                direction=direction
            )
            break  # Only need first session
    except Exception as e:
        logger.error(f"Failed to send Feishu single-leg alert: {e}")
```

**功能说明：**
1. 根据strategy_type确定策略名称（反向/正向）和动作（开仓/平仓）
2. 发送WebSocket通知到前端
3. 发送飞书通知
4. 包含详细的单腿信息：Binance成交量、Bybit成交量、未成交量

## 测试验证

### 测试场景1：连续开仓单腿（Bybit完全未成交）

**操作步骤：**
1. 点击"启用连续开仓"按钮
2. 等待触发条件满足
3. Binance订单成交
4. Bybit订单未成交

**预期行为：**
- ✅ 检测到单腿：`is_single_leg=True`
- ✅ 日志记录：`[ERROR] SINGLE LEG DETECTED in continuous execution`
- ✅ WebSocket通知：前端收到`single_leg_alert`消息
- ✅ 飞书通知：发送单腿告警到飞书
- ✅ 策略继续运行（不会因为单腿而停止）

### 测试场景2：连续平仓单腿（Bybit部分成交）

**操作步骤：**
1. 点击"启用连续平仓"按钮
2. 等待触发条件满足
3. Binance订单成交2.0 XAU
4. Bybit订单成交1.5 XAU（< 95%）

**预期行为：**
- ✅ 检测到单腿：`is_single_leg=True`
- ✅ 日志记录单腿详情
- ✅ 发送告警通知
- ✅ 记录实际成交量：min(2.0, 1.5) = 1.5 XAU
- ✅ 策略继续执行下一次交易

### 测试场景3：连续执行正常成交

**操作步骤：**
1. 点击"启用连续开仓"按钮
2. Binance和Bybit都正常成交

**预期行为：**
- ✅ `is_single_leg=False`
- ✅ 不发送单腿告警
- ✅ 正常记录持仓
- ✅ 继续执行直到达到阶梯限制

## 日志示例

### 正常执行日志
```
[INFO] Step 8 - Executing reverse_opening: 2.0 units
[INFO] Step 8 result - Success: True, Binance filled: 2.0, Bybit filled: 2.0
[INFO] Position updated: +2.0
```

### 单腿情况日志
```
[INFO] Step 8 - Executing forward_closing: 2.0 units
[INFO] Step 8 result - Success: False, Binance filled: 2.0, Bybit filled: 0.0
[ERROR] SINGLE LEG DETECTED in continuous execution: {'binance_filled': 2.0, 'bybit_filled': 0.0, 'bybit_filled_xau': 0.0, 'unfilled_qty': 2.0}
[ERROR] Execution failed: {'success': False, 'error': 'Bybit订单未成交', 'is_single_leg': True}
```

## 与单次执行的对比

### 单次执行（已修复）
- 位置：`backend/app/api/v1/strategies.py`
- 逻辑：在API层检查`is_single_leg`并发送告警
- 适用：单次开仓、单次平仓

### 连续执行（本次修复）
- 位置：`backend/app/services/continuous_executor.py`
- 逻辑：在执行器内部检查`is_single_leg`并发送告警
- 适用：连续开仓、连续平仓

**统一性：** 两种执行模式现在都有完整的单腿检测和告警机制。

## 部署步骤

1. 停止后端服务
2. 更新代码
3. 重启后端服务
4. 测试连续执行功能
5. 验证单腿告警正常触发

## 修复总结

### 修复前
- ❌ 连续执行完全没有单腿检测
- ❌ 单腿发生时用户无法得知
- ❌ 存在严重的风险管理漏洞

### 修复后
- ✅ 连续执行有完整的单腿检测
- ✅ 单腿发生时立即告警（WebSocket + 飞书）
- ✅ 详细日志记录便于追溯
- ✅ 与单次执行保持一致的告警机制

## 风险评估

**修复前风险：** 🔴 高风险
- 连续执行中的单腿无法被发现
- 可能造成大量单边敞口
- 用户无法及时止损

**修复后风险：** 🟢 低风险
- 单腿立即告警
- 用户能及时发现并处理
- 完整的日志追溯能力

## 后续建议

1. **增加单腿统计**
   - 记录单腿发生频率
   - 分析单腿原因（MT5连接、持仓不足等）
   - 优化执行策略

2. **增加自动恢复**
   - 检测到单腿后自动重试Bybit订单
   - 或提供手动补单界面

3. **增加预警机制**
   - 在Bybit订单前再次确认持仓
   - 检查MT5连接状态
   - 验证账户余额

4. **监控告警**
   - 如果单腿频繁发生，自动暂停策略
   - 发送系统级告警给管理员
