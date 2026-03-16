# 单腿警报误报问题修复

## 问题描述
单腿警报存在误报问题：在平仓/开仓操作完成后立即检查持仓，由于交易所API数据同步延迟（通常3-8秒），导致检测到持仓不一致而触发误报。

## 根本原因
原有逻辑在订单执行完成后立即检查`is_single_leg`标志并发送警报，没有考虑：
1. Binance和Bybit的持仓数据同步延迟
2. 交易所API返回数据的临时波动
3. 网络延迟导致的数据不一致

## 修复方案

### 核心思路
1. **10秒延时**：订单执行完成后等待10秒，覆盖交易所数据同步的最大延迟
2. **双重校验**：进行两次持仓检查（间隔1秒），排除临时数据波动
3. **异步执行**：使用`asyncio.create_task`异步执行检查，不阻塞主流程

### 实现逻辑

#### 1. 触发延时检查（continuous_executor.py:360-368）
```python
# Step 8.5: Schedule delayed single-leg check (10 seconds + double verification)
if exec_result.get('is_single_leg'):
    logger.warning(f"Potential single-leg detected, scheduling delayed verification in 10 seconds")
    # Schedule async delayed check (non-blocking)
    import asyncio
    asyncio.create_task(self._delayed_single_leg_check(
        strategy_type=strategy_type,
        exec_result=exec_result,
        binance_account=binance_account,
        bybit_account=bybit_account
    ))
```

#### 2. 延时检查方法（continuous_executor.py:648-762）
```python
async def _delayed_single_leg_check(
    self,
    strategy_type: str,
    exec_result: Dict,
    binance_account: Account,
    bybit_account: Account
):
    """
    10秒延时 + 双重校验的单腿检查

    流程：
    1. 等待10秒（数据同步）
    2. 第一次校验：获取实际持仓，检查是否一致
    3. 如果一致：无风险，返回
    4. 如果不一致：等待1秒，进行第二次校验
    5. 第二次校验：再次获取持仓
    6. 如果两次都不一致：确认单腿风险，发送警报
    7. 如果第二次一致：数据已同步，不发送警报
    """
```

### 关键优化点

#### 1. 非阻塞执行
- 使用`asyncio.create_task`异步执行检查
- 不影响平仓/开仓主流程的继续执行
- 10秒延时不会阻塞策略

#### 2. 双重校验机制
```python
# 第一次校验（10秒后）
pos_diff = abs(binance_qty - bybit_qty)
if pos_diff < 0.01:
    return  # 持仓一致，无风险

# 第二次校验（11秒后）
await asyncio.sleep(1)
pos_diff2 = abs(binance_qty2 - bybit_qty2)
if pos_diff2 >= 0.01:
    # 两次都不一致，确认单腿
    send_alert()
else:
    # 第二次一致，排除误报
    logger.info("Data synced, false positive avoided")
```

#### 3. 容错处理
- 添加try-except捕获异常
- 异常时不发送警报，避免误报
- 详细日志记录每一步的检查结果

#### 4. 精确的持仓对比
- 使用0.01 XAU作为容差阈值（最小交易单位）
- Bybit持仓从Lot转换为XAU（×100）
- 避免浮点精度问题

## 修复效果

### 修复前
```
订单执行完成 → 立即检查持仓 → 发现不一致（数据未同步）→ 误报警报
```

### 修复后
```
订单执行完成 → 等待10秒 → 第一次检查 → 持仓一致 → 无警报
订单执行完成 → 等待10秒 → 第一次检查 → 不一致 → 等待1秒 → 第二次检查 → 一致 → 无警报
订单执行完成 → 等待10秒 → 第一次检查 → 不一致 → 等待1秒 → 第二次检查 → 不一致 → 确认单腿 → 发送警报
```

## 验证方法

### 1. 日志监控
```bash
tail -f backend/app.log | grep "SINGLE_LEG_CHECK"
```

关键日志输出：
```
[SINGLE_LEG_CHECK] Starting 10-second delayed verification for reverse_closing
[SINGLE_LEG_CHECK] First verification (10s delay): Binance=1.0 XAU, Bybit=1.0 XAU, Diff=0.0
[SINGLE_LEG_CHECK] First verification passed: positions are consistent, no alert needed
```

或者：
```
[SINGLE_LEG_CHECK] First verification (10s delay): Binance=1.0 XAU, Bybit=0.0 XAU, Diff=1.0
[SINGLE_LEG_CHECK] Second verification (11s delay): Binance=1.0 XAU, Bybit=1.0 XAU, Diff=0.0
[SINGLE_LEG_CHECK] Second verification passed: positions synced, first check was due to data delay
```

### 2. 测试场景

| 场景 | 预期结果 |
|------|----------|
| 正常双边成交 | 10秒后第一次校验通过，无警报 |
| 数据同步延迟 | 第一次不一致，第二次一致，无警报 |
| 真实单腿 | 两次校验都不一致，发送警报 |
| API异常 | 捕获异常，不发送警报 |

## 相关文件
- `backend/app/services/continuous_executor.py` - 主要修复文件
  - 第360-368行：触发延时检查
  - 第648-762行：延时检查实现
- `backend/app/services/order_executor_v2.py` - 单腿检测逻辑（保持不变）

## 注意事项

1. **不影响真单腿检测**：真实的单腿问题仍然会被检测并报警
2. **延时可调整**：如果10秒不够，可以调整为更长时间
3. **异步执行**：不会阻塞策略执行，不影响性能
4. **日志完整**：每一步都有详细日志，便于排查问题

## 修复日期
2026-03-16

## 影响范围
- 反向开仓策略
- 反向平仓策略
- 正向开仓策略
- 正向平仓策略

所有使用`_execute_ladder`方法的策略都会受益于此修复。
