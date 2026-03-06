# 订单持久化和恢复机制实现方案

## 功能概述

实现4个关键功能以提高系统可靠性：
1. 订单ID持久化
2. 网络中断恢复
3. MT5成交量检查
4. 阶梯跳过功能

---

## 1. 订单ID持久化

### 数据库设计

**新增表：pending_orders**

```sql
CREATE TABLE pending_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id),
    strategy_type VARCHAR(20) NOT NULL,  -- 'forward_opening', 'reverse_closing', etc.
    platform VARCHAR(20) NOT NULL,       -- 'binance', 'bybit'
    order_id VARCHAR(100) NOT NULL,      -- 交易所订单ID
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,           -- 'BUY', 'SELL'
    quantity DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8),
    order_type VARCHAR(20) NOT NULL,     -- 'LIMIT', 'MARKET'
    status VARCHAR(20) NOT NULL,         -- 'PENDING', 'FILLED', 'CANCELLED', 'FAILED'
    filled_quantity DECIMAL(20, 8) DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,                -- 订单过期时间
    metadata JSONB,                      -- 额外信息（如ladder_index等）

    INDEX idx_user_status (user_id, status),
    INDEX idx_created_at (created_at),
    INDEX idx_expires_at (expires_at)
);
```

### 实现流程

**下单时**：
```python
# 1. 创建订单记录（状态：PENDING）
pending_order = await create_pending_order(
    user_id=user_id,
    strategy_type="reverse_opening",
    platform="binance",
    order_id=None,  # 先创建记录
    symbol="XAUUSDT",
    side="SELL",
    quantity=100,
    price=2000.0,
    order_type="LIMIT",
    status="PENDING",
    expires_at=datetime.now() + timedelta(seconds=10)
)

# 2. 下单到交易所
try:
    order = await exchange.create_order(...)

    # 3. 立即更新订单ID
    await update_pending_order(
        pending_order.id,
        order_id=order['id'],
        status="PENDING"
    )
except Exception as e:
    # 4. 下单失败，标记为FAILED
    await update_pending_order(
        pending_order.id,
        status="FAILED",
        metadata={"error": str(e)}
    )
    raise
```

**查询订单状态时**：
```python
# 更新成交量和状态
await update_pending_order(
    pending_order.id,
    filled_quantity=filled_qty,
    status="FILLED" if filled_qty >= quantity else "PARTIAL"
)
```

**取消订单时**：
```python
await update_pending_order(
    pending_order.id,
    status="CANCELLED"
)
```

---

## 2. 网络中断恢复

### 启动时恢复机制

**在应用启动时执行**：

```python
async def recover_pending_orders():
    """恢复未完成的订单"""

    # 1. 查询所有PENDING状态的订单
    pending_orders = await db.execute(
        select(PendingOrder).where(
            PendingOrder.status == "PENDING",
            PendingOrder.created_at > datetime.now() - timedelta(hours=1)
        )
    )

    for order in pending_orders:
        try:
            # 2. 查询订单实际状态
            if order.platform == "binance":
                status = await check_binance_order_status(
                    account, order.symbol, order.order_id
                )
            else:
                status = await check_mt5_order_status(
                    account, order.order_id
                )

            # 3. 更新订单状态
            if status['filled_qty'] >= order.quantity:
                await update_pending_order(order.id, status="FILLED")
            elif status['status'] == 'CANCELLED':
                await update_pending_order(order.id, status="CANCELLED")
            else:
                # 4. 订单仍在挂单，检查是否过期
                if order.expires_at and datetime.now() > order.expires_at:
                    # 取消过期订单
                    await cancel_order(order)
                    await update_pending_order(order.id, status="CANCELLED")

        except Exception as e:
            logger.error(f"Failed to recover order {order.id}: {e}")
            # 标记为需要人工处理
            await update_pending_order(
                order.id,
                metadata={"recovery_error": str(e)}
            )
```

### 定期清理任务

```python
async def cleanup_old_orders():
    """清理旧订单记录"""

    # 删除7天前的已完成/已取消订单
    await db.execute(
        delete(PendingOrder).where(
            PendingOrder.status.in_(["FILLED", "CANCELLED", "FAILED"]),
            PendingOrder.created_at < datetime.now() - timedelta(days=7)
        )
    )
```

---

## 3. MT5成交量检查

### 实现方案

**在 order_executor.py 中增强 place_mt5_order**：

```python
async def place_mt5_order(
    self,
    account: Account,
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = "MARKET",
    price: Optional[float] = None
) -> Dict[str, Any]:
    """下单到MT5并检查实际成交量"""

    try:
        mt5_client = MT5Client(
            account.mt5_login,
            account.mt5_password,
            account.mt5_server
        )

        if not mt5_client.initialize():
            return {"success": False, "error": "MT5初始化失败"}

        # 1. 下单
        result = mt5_client.place_order(
            symbol=symbol,
            order_type=order_type,
            volume=quantity,
            price=price
        )

        if not result:
            return {"success": False, "error": "MT5下单失败"}

        ticket = result.get('ticket')

        # 2. 等待成交（最多1秒）
        await asyncio.sleep(0.5)

        # 3. 检查实际成交量
        actual_filled = await self._check_mt5_filled_volume(
            mt5_client, ticket
        )

        # 4. 比对成交量
        if actual_filled < quantity:
            # 部分成交
            logger.warning(
                f"MT5 partial fill: {actual_filled}/{quantity} "
                f"(ticket: {ticket})"
            )

            # 发送报警
            await self._send_partial_fill_alert(
                account.user_id,
                symbol,
                quantity,
                actual_filled,
                ticket
            )

            # 决定是否补单
            if actual_filled < quantity * 0.5:  # 成交不足50%
                # 尝试补单
                remaining = quantity - actual_filled
                logger.info(f"Attempting to fill remaining {remaining}")

                补单结果 = await self._fill_remaining_mt5_order(
                    mt5_client, symbol, side, remaining
                )

                if 补单结果['success']:
                    actual_filled += 补单结果['filled_qty']

        return {
            "success": True,
            "platform": "bybit",
            "ticket": ticket,
            "filled_qty": actual_filled,
            "requested_qty": quantity,
            "partial_fill": actual_filled < quantity
        }

    except Exception as e:
        logger.error(f"MT5 order error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        mt5_client.shutdown()


async def _check_mt5_filled_volume(
    self, mt5_client: MT5Client, ticket: int
) -> float:
    """检查MT5订单实际成交量"""

    try:
        # 查询订单历史
        deals = mt5_client.get_deals_by_ticket(ticket)

        if not deals:
            return 0.0

        # 累计成交量
        total_volume = sum(deal.volume for deal in deals)
        return total_volume

    except Exception as e:
        logger.error(f"Failed to check MT5 filled volume: {e}")
        return 0.0


async def _fill_remaining_mt5_order(
    self, mt5_client: MT5Client, symbol: str, side: str, quantity: float
) -> Dict[str, Any]:
    """补单剩余数量"""

    try:
        result = mt5_client.place_order(
            symbol=symbol,
            order_type="MARKET",
            volume=quantity,
            price=None
        )

        if result:
            ticket = result.get('ticket')
            await asyncio.sleep(0.3)
            filled = await self._check_mt5_filled_volume(mt5_client, ticket)

            return {
                "success": True,
                "filled_qty": filled,
                "ticket": ticket
            }
        else:
            return {"success": False, "filled_qty": 0}

    except Exception as e:
        logger.error(f"Failed to fill remaining: {e}")
        return {"success": False, "filled_qty": 0}
```

---

## 4. 阶梯跳过功能

### 数据库设计

**扩展 strategy_configs 表**：

```sql
ALTER TABLE strategy_configs ADD COLUMN IF NOT EXISTS
    ladder_failure_counts JSONB DEFAULT '{}';

-- 存储格式：{"0": 3, "1": 0, "2": 5}
-- 键是ladder_index，值是连续失败次数
```

### 实现逻辑

**在 StrategyPanel.vue 中**：

```javascript
// 配置：最大失败次数
const MAX_LADDER_FAILURES = 5

// 记录失败次数
const ladderFailureCounts = ref({
  opening: {},  // {0: 3, 1: 0, 2: 5}
  closing: {}
})

// 加载失败次数
function loadLadderFailureCounts() {
  const saved = localStorage.getItem(`ladder_failures_${configId.value}`)
  if (saved) {
    ladderFailureCounts.value = JSON.parse(saved)
  }
}

// 保存失败次数
function saveLadderFailureCounts() {
  localStorage.setItem(
    `ladder_failures_${configId.value}`,
    JSON.stringify(ladderFailureCounts.value)
  )
}

// 执行阶梯时检查失败次数
async function executeLadderOpening(ladderIndex, ladder) {
  // 检查是否应该跳过
  const failureCount = ladderFailureCounts.value.opening[ladderIndex] || 0

  if (failureCount >= MAX_LADDER_FAILURES) {
    console.log(`Skipping ladder ${ladderIndex + 1} due to ${failureCount} failures`)

    // 跳过到下一个阶梯
    ladderProgress.value.opening.currentLadderIndex++
    ladderProgress.value.opening.completedQty = 0
    saveLadderProgress()

    // 重置失败计数
    ladderFailureCounts.value.opening[ladderIndex] = 0
    saveLadderFailureCounts()

    // 通知用户
    notificationStore.showStrategyNotification(
      `阶梯 ${ladderIndex + 1} 连续失败${failureCount}次，已自动跳过`,
      'warning'
    )

    return
  }

  // 正常执行
  try {
    const response = await api.post(...)

    if (response.data.success) {
      // 成功：重置失败计数
      ladderFailureCounts.value.opening[ladderIndex] = 0
      saveLadderFailureCounts()

      // 更新进度...
    } else {
      // 失败：增加失败计数
      ladderFailureCounts.value.opening[ladderIndex] = failureCount + 1
      saveLadderFailureCounts()

      console.log(
        `Ladder ${ladderIndex + 1} failed ${failureCount + 1}/${MAX_LADDER_FAILURES} times`
      )

      // 如果达到最大失败次数，下次会自动跳过
      if (failureCount + 1 >= MAX_LADDER_FAILURES) {
        notificationStore.showStrategyNotification(
          `阶梯 ${ladderIndex + 1} 已连续失败${failureCount + 1}次，下次将自动跳过`,
          'error'
        )
      }
    }
  } catch (error) {
    // 异常也算失败
    ladderFailureCounts.value.opening[ladderIndex] = failureCount + 1
    saveLadderFailureCounts()
  }
}

// 手动重置失败计数
function resetLadderFailures(type) {
  if (confirm('确定要重置所有阶梯的失败计数吗？')) {
    ladderFailureCounts.value[type] = {}
    saveLadderFailureCounts()
    notificationStore.showStrategyNotification('失败计数已重置', 'success')
  }
}
```

**在UI中添加显示**：

```vue
<template>
  <div class="ladder-status">
    <div v-for="(ladder, index) in config.ladders" :key="index">
      <span>阶梯 {{ index + 1 }}</span>
      <span v-if="ladderFailureCounts.opening[index] > 0" class="failure-badge">
        失败 {{ ladderFailureCounts.opening[index]}/{{ MAX_LADDER_FAILURES }}
      </span>
    </div>
    <button @click="resetLadderFailures('opening')">重置失败计数</button>
  </div>
</template>
```

---

## 实施优先级

### Phase 1: 订单ID持久化（高优先级）

**工作量**：2-3小时
**文件**：
- 创建数据库迁移
- 修改 order_executor_v2.py
- 添加 pending_order 模型

### Phase 2: 网络中断恢复（高优先级）

**工作量**：2-3小时
**文件**：
- 修改 main.py（添加启动恢复）
- 添加恢复服务
- 添加定期清理任务

### Phase 3: MT5成交量检查（中优先级）

**工作量**：2-3小时
**文件**：
- 修改 order_executor.py
- 修改 mt5_client.py
- 添加报警服务

### Phase 4: 阶梯跳过功能（中优先级）

**工作量**：1-2小时
**文件**：
- 修改 StrategyPanel.vue
- 添加UI显示

---

## 测试计划

### 1. 订单持久化测试

- [ ] 下单后立即查询数据库，验证订单已保存
- [ ] 模拟程序崩溃，重启后验证订单恢复
- [ ] 验证订单状态更新正确

### 2. 网络中断测试

- [ ] 模拟网络中断（断开网络）
- [ ] 验证订单ID已保存
- [ ] 恢复网络后验证订单恢复

### 3. MT5成交量测试

- [ ] 模拟部分成交（小额订单）
- [ ] 验证报警发送
- [ ] 验证补单逻辑

### 4. 阶梯跳过测试

- [ ] 模拟阶梯连续失败5次
- [ ] 验证自动跳过
- [ ] 验证失败计数重置

---

## 风险评估

### 低风险
- 阶梯跳过功能（纯前端，易回滚）

### 中风险
- MT5成交量检查（可能影响执行速度）
- 订单持久化（需要数据库迁移）

### 高风险
- 网络中断恢复（可能影响启动时间）

---

## 回滚方案

### 订单持久化
- 保留旧代码分支
- 数据库迁移可回滚

### 网络中断恢复
- 可以禁用恢复逻辑
- 不影响正常流程

### MT5成交量检查
- 可以通过配置开关禁用
- 不影响现有逻辑

### 阶梯跳过
- 前端代码，可快速回滚
- localStorage数据可清除
