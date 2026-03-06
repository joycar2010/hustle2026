# 策略执行异常场景测试报告

## 测试目的
模拟四个策略（反向开仓、反向平仓、正向开仓、正向平仓）启用后可能遇到的各种异常情况，检查系统是否有逻辑漏洞。

---

## 场景分类

### 🔴 高风险场景（可能导致资金损失）
### 🟡 中风险场景（可能导致策略失效）
### 🟢 低风险场景（用户体验问题）

---

## 场景 1: 🔴 多个策略同时触发冲突

### 1.1 反向开仓 + 反向平仓同时触发

**场景描述**：
- 当前持仓：Binance SHORT 100手，Bybit LONG 1手
- 价差满足反向开仓条件（继续做空 Binance）
- 同时价差也满足反向平仓条件（平掉现有持仓）
- 两个策略同时触发

**预期行为**：
- 应该有互斥锁防止同时执行
- 或者有优先级机制（平仓优先于开仓）

**当前代码检查**：
```javascript
// executeLadderOpening
if (executingOpening.value) return  // ✅ 有锁

// executeLadderClosing
if (executingClosing.value) return  // ✅ 有锁
```

**问题**：
- ❌ 两个锁是独立的，无法防止开仓和平仓同时执行
- ❌ 可能导致：开仓订单和平仓订单同时下单，持仓混乱

**风险等级**：🔴 高风险

**建议修复**：
```javascript
// 添加全局执行锁
const executingAnyStrategy = computed(() =>
  executingOpening.value || executingClosing.value
)

async function executeLadderOpening(ladderIndex, ladder) {
  if (executingAnyStrategy.value) return  // 任何策略执行中都不允许
  // ...
}
```

---

### 1.2 正向策略 + 反向策略同时触发

**场景描述**：
- 正向开仓和反向开仓同时满足条件
- 两个策略都尝试在 Binance 开仓，但方向相反

**预期行为**：
- 应该只执行一个策略
- 或者有优先级机制

**当前代码检查**：
- ❌ 没有跨策略类型的互斥机制
- ❌ 可能导致：Binance 同时开多单和空单，对冲掉了

**风险等级**：🔴 高风险

---

## 场景 2: 🔴 网络中断导致单腿交易

### 2.1 Binance 下单成功后网络断开

**场景描述**：
1. Binance 下单成功（SHORT 100手）
2. 网络突然断开
3. 无法查询 Binance 订单状态
4. 无法在 Bybit 开对冲仓位

**当前代码检查**：
```python
# order_executor_v2.py - execute_reverse_opening
# Step 1: Place Binance order
binance_result = await self.base_executor.place_binance_order(...)

# Step 2: Wait and check Binance order
filled_qty = await self._wait_and_check_binance_order(...)

if filled_qty == 0:
    return {"success": False, ...}  # ✅ 如果未成交，不执行 Bybit

# Step 3: Place Bybit order
bybit_result = await self.base_executor.place_mt5_order(...)
```

**问题分析**：
- ✅ 如果网络断开在 Step 1 和 Step 2 之间，会超时返回 filled_qty=0，不执行 Bybit
- ❌ 但如果 Binance 实际已成交，但因网络问题查询失败返回 0，就会漏掉 Bybit 对冲

**风险等级**：🔴 高风险

**建议修复**：
- 增加重试机制
- 记录订单 ID 到数据库，即使网络断开也能恢复

---

### 2.2 Bybit MT5 连接断开

**场景描述**：
1. Binance 下单并成交 100手
2. 准备在 Bybit 开对冲仓位
3. MT5 连接断开，无法下单

**当前代码检查**：
```python
# order_executor.py - place_mt5_order
mt5_client = MT5Client(account.mt5_login, account.mt5_password, account.mt5_server)
if not mt5_client.initialize():
    return {"success": False, "error": "MT5初始化失败"}
```

**问题分析**：
- ✅ 会返回失败
- ❌ 但 Binance 订单已经成交，形成单腿

**风险等级**：🔴 高风险

**当前保护**：
- ✅ 有三层持仓检查（pre-check）
- ✅ 会发送单腿报警

**建议增强**：
- 自动重试 MT5 连接
- 记录失败订单，提供手动补单功能

---

## 场景 3: 🟡 部分成交导致持仓不平衡

### 3.1 Binance 部分成交 50%

**场景描述**：
- 计划开仓 100手
- Binance 只成交 50手
- Bybit 按 50手开对冲仓位
- 剩余 50手未执行

**当前代码检查**：
```python
# order_executor_v2.py
filled_qty = await self._wait_and_check_binance_order(...)
# 使用实际成交量计算 Bybit 数量
bybit_quantity_lot = filled_qty / 100.0
```

**问题分析**：
- ✅ 使用实际成交量，不会过度对冲
- ✅ 前端会更新阶梯进度，下次继续执行剩余数量

**风险等级**：🟢 低风险（逻辑正确）

---

### 3.2 Bybit 部分成交

**场景描述**：
- Binance 成交 100手
- Bybit 计划开 1手，但只成交 0.5手
- 剩余 0.5手未对冲

**当前代码检查**：
```python
# order_executor.py - place_mt5_order
result = mt5_client.place_order(...)
# ❌ 没有检查 MT5 订单是否部分成交
# MT5 订单通常是市价单，应该立即全部成交
```

**问题分析**：
- 🟡 MT5 市价单理论上应该立即全部成交
- ❌ 但如果流动性不足，可能部分成交
- ❌ 当前代码没有检查 MT5 实际成交量

**风险等级**：🟡 中风险

**建议修复**：
```python
# 检查 MT5 实际成交量
actual_filled = mt5_client.get_order_filled_volume(ticket)
if actual_filled < bybit_quantity_lot:
    logger.warning(f"MT5 partial fill: {actual_filled}/{bybit_quantity_lot}")
    # 补单或报警
```

---

## 场景 4: 🟡 订单被交易所拒绝

### 4.1 Binance 余额不足

**场景描述**：
- 计划开仓 100手（约 $200,000）
- Binance 账户余额只有 $50,000
- 订单被拒绝

**当前代码检查**：
```python
# order_executor.py - place_binance_order
order = await exchange.create_order(...)
# ✅ 如果余额不足，ccxt 会抛出异常
except Exception as e:
    return {"success": False, "error": str(e)}
```

**问题分析**：
- ✅ 会捕获异常并返回失败
- ✅ 不会执行 Bybit 对冲
- ✅ 策略会显示错误通知

**风险等级**：🟢 低风险（逻辑正确）

---

### 4.2 Bybit 保证金不足

**场景描述**：
- Binance 成交 100手
- Bybit 保证金不足，无法开 1手
- MT5 下单失败

**当前代码检查**：
```python
# order_executor.py - place_mt5_order
result = mt5_client.place_order(...)
if result is None:
    return {"success": False, "error": "MT5下单失败"}
```

**问题分析**：
- ✅ 会返回失败
- ❌ 但 Binance 已成交，形成单腿
- ✅ 会触发单腿报警

**风险等级**：🟡 中风险（有报警机制）

---

## 场景 5: 🟡 价格剧烈波动

### 5.1 挂单期间价格快速移动

**场景描述**：
- Binance 挂单价格 2000.00
- 市场价格快速上涨到 2005.00
- 挂单永远无法成交
- 超时后取消订单

**当前代码检查**：
```python
# order_executor_v2.py
timeout = 0.4  # 400ms 超时
filled_qty = await self._wait_and_check_binance_order(..., timeout)
if filled_qty == 0:
    # 取消订单
    await self.base_executor.cancel_binance_order(...)
```

**问题分析**：
- ✅ 有超时机制
- ✅ 超时后取消订单
- ✅ 返回 filled_qty=0，不执行 Bybit
- ✅ 前端显示警告，策略保持启用，等待下次重试

**风险等级**：🟢 低风险（逻辑正确）

---

## 场景 6: 🔴 持仓数据不一致

### 6.1 前端持仓数据过期

**场景描述**：
- 实际持仓：Binance SHORT 100手，Bybit LONG 1手
- 前端缓存显示：Binance SHORT 50手，Bybit LONG 0.5手
- 用户基于错误数据启用平仓策略

**当前代码检查**：
```javascript
// StrategyPanel.vue - checkPositionForClosing
const positions = await api.get('/api/v1/accounts/positions')
// ✅ 每次启用策略前都会重新获取最新持仓
```

**问题分析**：
- ✅ 启用策略前会重新获取持仓
- ✅ 后端也会在执行前检查持仓（pre-check）

**风险等级**：🟢 低风险（有双重检查）

---

### 6.2 Binance 和 Bybit 持仓比例失衡

**场景描述**：
- 正常比例应该是 100:1（Binance 100手 = Bybit 1手）
- 实际持仓：Binance SHORT 100手，Bybit LONG 0.3手
- 比例失衡，可能是之前的单腿交易导致

**当前代码检查**：
```javascript
// StrategyPanel.vue - checkPositionForClosing
const binanceTotal = binancePositions.reduce(...)
const bybitTotal = bybitPositions.reduce(...)
const expectedBybitQty = binanceTotal / 100.0
const bybitDeficit = expectedBybitQty - bybitTotal

if (Math.abs(bybitDeficit) > 0.01) {
  return { valid: false, message: `持仓不平衡...` }
}
```

**问题分析**：
- ✅ 有持仓比例检查
- ✅ 如果失衡超过 0.01手，会阻止策略启用

**风险等级**：🟢 低风险（有检查机制）

---

## 场景 7: 🟡 阶梯执行中断

### 7.1 第一阶梯成功，第二阶梯失败

**场景描述**：
- 配置 3个阶梯，每个 100手
- 第一阶梯执行成功
- 第二阶梯因余额不足失败

**当前代码检查**：
```javascript
// StrategyPanel.vue
ladderProgress.value.opening.completedQty += actualFilled
if (ladderProgress.value.opening.completedQty >= ladder.qtyLimit) {
  ladderProgress.value.opening.currentLadderIndex++
  ladderProgress.value.opening.completedQty = 0
}
```

**问题分析**：
- ✅ 阶梯进度会保存
- ✅ 下次触发时会从当前阶梯继续
- ❌ 但如果第二阶梯一直失败（余额不足），会卡住无法继续

**风险等级**：🟡 中风险

**建议**：
- 添加阶梯跳过功能
- 或者在连续失败 N 次后自动禁用策略

---

### 7.2 阶梯进度丢失（页面刷新）

**场景描述**：
- 第一阶梯执行到 50%
- 用户刷新页面
- 阶梯进度丢失，从头开始

**当前代码检查**：
```javascript
// StrategyPanel.vue
const ladderProgress = ref({
  opening: { currentLadderIndex: 0, completedQty: 0 },
  closing: { currentLadderIndex: 0, completedQty: 0 }
})
// ❌ 没有持久化到 localStorage
```

**问题分析**：
- ❌ 阶梯进度只保存在内存中
- ❌ 页面刷新后会丢失
- ❌ 可能导致重复执行已完成的阶梯

**风险等级**：🟡 中风险

**建议修复**：
```javascript
// 保存阶梯进度到 localStorage
function saveLadderProgress() {
  localStorage.setItem(`ladder_progress_${configId.value}`,
    JSON.stringify(ladderProgress.value))
}

// 页面加载时恢复
onMounted(() => {
  const saved = localStorage.getItem(`ladder_progress_${configId.value}`)
  if (saved) {
    ladderProgress.value = JSON.parse(saved)
  }
})
```

---

## 场景 8: 🔴 策略冲突

### 8.1 开仓和平仓同时操作同一持仓

**场景描述**：
- 当前持仓：Binance SHORT 100手
- 反向平仓策略触发，准备平掉 50手
- 同时反向开仓策略触发，准备再开 50手空单
- 两个操作同时进行

**当前代码检查**：
```javascript
if (executingOpening.value) return
if (executingClosing.value) return
// ❌ 两个锁是独立的
```

**问题分析**：
- ❌ 可能同时执行
- ❌ 持仓数据可能混乱

**风险等级**：🔴 高风险

---

## 场景 9: 🟡 用户手动干预

### 9.1 策略执行中用户手动平仓

**场景描述**：
1. 策略准备平仓 100手
2. 策略在 Binance 下单并等待成交
3. 用户手动在交易所平掉了这 100手
4. 策略检测到 Binance 成交，准备在 Bybit 平仓
5. 但 Bybit 已经没有对应持仓了

**当前代码检查**：
```python
# order_executor_v2.py - execute_reverse_closing
# Step 0: Pre-check Bybit position
bybit_positions = mt5_client.get_positions("XAUUSD.s")
long_positions = [p for p in bybit_positions if p['type'] == 0]
if not long_positions:
    return {"success": False, "error": "Bybit没有LONG持仓可以平仓"}
```

**问题分析**：
- ✅ 有 pre-check 机制
- ❌ 但 pre-check 在 Binance 下单之前
- ❌ 如果用户在 Binance 下单后、Bybit 平仓前手动操作，仍会出问题

**风险等级**：🟡 中风险

**建议**：
- 在 Bybit 平仓前再次检查持仓
- 或者锁定策略执行期间的手动操作

---

### 9.2 策略执行中用户禁用策略

**场景描述**：
1. 策略正在执行（Binance 订单已下单）
2. 用户点击禁用策略按钮
3. 策略被禁用，但 Binance 订单还在执行中

**当前代码检查**：
```javascript
async function executeLadderOpening(ladderIndex, ladder) {
  if (executingOpening.value) return
  executingOpening.value = true
  // ... 执行逻辑
  executingOpening.value = false
}

async function toggleOpening() {
  config.value.openingEnabled = false
  // ❌ 没有检查是否正在执行
}
```

**问题分析**：
- ❌ 用户可以在执行中禁用策略
- ❌ 可能导致订单执行到一半被中断

**风险等级**：🟡 中风险

**建议修复**：
```javascript
async function toggleOpening() {
  if (executingOpening.value) {
    notificationStore.showStrategyNotification('策略执行中，请稍后再试', 'warning')
    return
  }
  config.value.openingEnabled = false
}
```

---

## 场景 10: 🔴 订单ID丢失

### 10.1 Binance 下单成功但未记录订单ID

**场景描述**：
1. Binance 下单成功
2. 返回订单ID前程序崩溃
3. 重启后无法查询订单状态
4. 无法取消订单

**当前代码检查**：
```python
# order_executor.py
order = await exchange.create_order(...)
order_id = order['id']
# ❌ 订单ID只保存在内存中，没有持久化
```

**问题分析**：
- ❌ 订单ID没有持久化
- ❌ 程序崩溃后无法恢复
- ❌ 可能导致订单无法取消，一直挂单

**风险等级**：🔴 高风险

**建议修复**：
- 将订单ID保存到数据库
- 添加订单恢复机制

---

## 总结

### 🔴 高风险问题（需要立即修复）

1. **多个策略同时执行冲突** - 缺少全局互斥锁
2. **网络中断导致单腿交易** - 缺少订单恢复机制
3. **订单ID丢失** - 缺少持久化
4. **开仓平仓策略冲突** - 缺少跨策略互斥

### 🟡 中风险问题（建议修复）

5. **Bybit 部分成交** - 缺少成交量检查
6. **阶梯进度丢失** - 缺少持久化
7. **用户手动干预** - 缺少二次检查

### 🟢 低风险问题（逻辑正确）

8. Binance 部分成交 - ✅ 已正确处理
9. 订单被拒绝 - ✅ 已正确处理
10. 价格波动导致未成交 - ✅ 已正确处理
11. 持仓数据不一致 - ✅ 有检查机制

---

## 建议优先修复顺序

1. **添加全局策略执行锁**（防止多策略冲突）
2. **订单ID持久化**（防止订单丢失）
3. **阶梯进度持久化**（防止重复执行）
4. **增强 Bybit 成交量检查**（防止部分成交）
5. **禁用策略时检查执行状态**（防止中断）
