# 反向平仓1手后被打断问题修复

## 问题描述
反向平仓策略中，设置反下总手数为2，反平单手数为1时，双边成功完成1手后流程被打断，无法继续平仓到2手。

## 根本原因
在 `continuous_executor.py` 的 `_execute_ladder` 方法中，存在触发计数管理的逻辑错误：

### 原有逻辑（有问题）
```python
# Step 12: Handle Scenario 2 vs Scenario 3
if binance_filled >= order_qty * 0.95:
    # Scenario 2: Fully filled - DO NOT reset triggers
    logger.info(f"Scenario 2: Fully filled, keeping trigger count")
    # 问题：触发计数没有被重置！
else:
    # Scenario 3: Partially filled - Reset triggers
    self.trigger_mgr.reset()
```

### 问题分析
1. **第一次平仓**：触发计数累积到3（假设配置要求3次触发），执行1手平仓成功
2. **场景2判断**：因为是完全成交，触发计数**保持为3**，没有重置
3. **第二次循环**：
   - Step 3检查：`is_ready(3)` 返回 True（因为count=3 >= 3）
   - 直接跳过触发累积阶段
   - 但此时点差可能不满足条件，或者其他原因导致无法执行
4. **关键问题**：触发计数应该在每次成功执行后重置，让下一次循环重新累积触发条件

## 修复方案

### 修改内容
文件：`backend/app/services/continuous_executor.py`
位置：第406-424行

```python
# Step 12: Reset triggers after successful execution
# CRITICAL FIX: Always reset triggers after order execution
with open("ladder_debug.log", "a") as f:
    f.write(f"[DEBUG] Step 12 - Order executed successfully\n")
    f.write(f"[DEBUG] Step 12 - binance_filled={binance_filled}, order_qty={order_qty}\n")
    f.write(f"[DEBUG] Step 12 - Current trigger count before reset: {self.trigger_mgr.count}\n")
    f.write(f"[DEBUG] Step 12 - Resetting trigger count to allow next cycle\n")

logger.info(f"Order executed: {binance_filled}/{order_qty} filled, resetting triggers from {self.trigger_mgr.count} to 0")
self.trigger_mgr.reset()
await self._push_trigger_reset(ladder_idx, strategy_type)

with open("ladder_debug.log", "a") as f:
    f.write(f"[DEBUG] Step 12 - Trigger count after reset: {self.trigger_mgr.count}\n")
```

### 核心改动
1. **移除场景2和场景3的区分**：无论完全成交还是部分成交，都重置触发计数
2. **统一重置逻辑**：每次成功执行订单后，触发计数归0
3. **增强日志**：添加详细的调试日志，记录触发计数的变化

## 修复后的执行流程

### 第一次平仓（1手）
1. 触发计数从0累积到3
2. 执行1手平仓成功
3. **触发计数重置为0** ✓
4. 累计平仓数量：1手

### 第二次平仓（1手）
1. 触发计数从0重新累积到3
2. 执行1手平仓成功
3. **触发计数重置为0** ✓
4. 累计平仓数量：2手

### 完成
- 累计平仓数量达到总手数2手
- 阶梯完成，退出循环

## 验证方法

### 1. 查看调试日志
```bash
tail -f backend/ladder_debug.log
```

关键日志输出：
```
[DEBUG] ===== Loop iteration 1 =====
[DEBUG] trigger_count at loop start: 0
[DEBUG] Step 12 - Current trigger count before reset: 3
[DEBUG] Step 12 - Trigger count after reset: 0

[DEBUG] ===== Loop iteration 2 =====
[DEBUG] trigger_count at loop start: 0
[DEBUG] Step 12 - Current trigger count before reset: 3
[DEBUG] Step 12 - Trigger count after reset: 0
```

### 2. 测试步骤
1. 设置反向平仓策略：
   - 反下总手数：2
   - 反平单手数：1
   - 触发次数：3
   - 反向平仓点差：合适的值
2. 点击反向平仓按钮
3. 观察日志和前端状态
4. 验证是否完成2手平仓

## 相关文件
- `backend/app/services/continuous_executor.py` - 主要修复文件
- `backend/app/services/trigger_manager.py` - 触发计数管理器
- `backend/ladder_debug.log` - 调试日志输出

## 修复日期
2026-03-16

## 影响范围
- 反向平仓策略
- 正向平仓策略（使用相同的执行逻辑）
- 反向开仓策略（使用相同的执行逻辑）
- 正向开仓策略（使用相同的执行逻辑）

所有使用 `_execute_ladder` 方法的策略都会受益于此修复。
