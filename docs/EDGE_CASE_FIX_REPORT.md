# 策略执行异常场景修复报告

## 修复时间
2026-03-06

## 修复内容

### ✅ 已修复的高风险问题

#### 1. 多个策略同时执行冲突 🔴

**问题描述**：
- 开仓和平仓策略可以同时执行
- 可能导致订单冲突、持仓混乱

**修复方案**：
添加全局策略执行锁 `executingAnyStrategy`

**修改文件**：`frontend/src/components/trading/StrategyPanel.vue`

**修改内容**：
```javascript
// 添加全局执行锁
const executingAnyStrategy = computed(() => executingOpening.value || executingClosing.value)

// 在执行函数中检查全局锁
async function executeLadderOpening(ladderIndex, ladder) {
  if (executingAnyStrategy.value) {
    console.log('Another strategy is executing, skipping opening')
    return
  }
  // ...
}

async function executeLadderClosing(ladderIndex, ladder) {
  if (executingAnyStrategy.value) {
    console.log('Another strategy is executing, skipping closing')
    return
  }
  // ...
}
```

**效果**：
- ✅ 任何策略执行时，其他策略会自动跳过
- ✅ 防止订单冲突和持仓混乱
- ✅ 下次触发时会自动重试

---

#### 2. 用户在策略执行中禁用策略 🟡

**问题描述**：
- 用户可以在策略执行中点击禁用按钮
- 可能导致订单执行到一半被中断

**修复方案**：
在禁用策略前检查执行状态

**修改文件**：`frontend/src/components/trading/StrategyPanel.vue`

**修改内容**：
```javascript
function toggleOpening() {
  if (config.value.openingEnabled) {
    // 禁用策略前检查是否正在执行
    if (executingOpening.value) {
      notificationStore.showStrategyNotification('策略执行中，请稍后再试', 'warning')
      return
    }
    config.value.openingEnabled = false
    // ...
  }
}

async function toggleClosing() {
  if (config.value.closingEnabled) {
    // 禁用策略前检查是否正在执行
    if (executingClosing.value) {
      notificationStore.showStrategyNotification('策略执行中，请稍后再试', 'warning')
      return
    }
    config.value.closingEnabled = false
    // ...
  }
}
```

**效果**：
- ✅ 策略执行中无法禁用
- ✅ 显示友好提示信息
- ✅ 防止订单执行中断

---

#### 3. 阶梯进度丢失（页面刷新） 🟡

**问题描述**：
- 阶梯进度只保存在内存中
- 页面刷新后进度丢失
- 可能导致重复执行已完成的阶梯

**修复方案**：
将阶梯进度持久化到 localStorage

**修改文件**：`frontend/src/components/trading/StrategyPanel.vue`

**修改内容**：
```javascript
// 1. 添加 localStorage key
const STORAGE_KEY_LADDER_PROGRESS = `strategy_${props.type}_ladder_progress`

// 2. 添加加载和保存函数
function loadLadderProgress() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_LADDER_PROGRESS)
    if (saved) {
      return JSON.parse(saved)
    }
  } catch (error) {
    console.error('Failed to load ladder progress:', error)
  }
  return {
    opening: { currentLadderIndex: 0, completedQty: 0 },
    closing: { currentLadderIndex: 0, completedQty: 0 }
  }
}

function saveLadderProgress() {
  try {
    localStorage.setItem(STORAGE_KEY_LADDER_PROGRESS, JSON.stringify(ladderProgress.value))
  } catch (error) {
    console.error('Failed to save ladder progress:', error)
  }
}

// 3. 初始化时加载进度
const ladderProgress = ref(loadLadderProgress())

// 4. 进度更新时保存
ladderProgress.value.opening.completedQty += actualFilled
saveLadderProgress()  // 持久化进度
```

**效果**：
- ✅ 页面刷新后进度不丢失
- ✅ 防止重复执行已完成的阶梯
- ✅ 提高系统可靠性

---

## 未修复的问题（需要后端支持）

### 🔴 高风险问题

#### 4. 网络中断导致单腿交易

**问题描述**：
- Binance 下单成功后网络断开
- 无法查询订单状态，无法在 Bybit 对冲

**当前保护**：
- ✅ 有超时机制
- ✅ 有三层持仓检查
- ✅ 有单腿报警

**建议修复**：
- 将订单ID持久化到数据库
- 添加订单恢复机制
- 增加重试机制

---

#### 5. 订单ID丢失

**问题描述**：
- 订单ID只保存在内存中
- 程序崩溃后无法恢复
- 无法取消挂单

**建议修复**：
- 在数据库中添加 `pending_orders` 表
- 下单后立即保存订单ID
- 启动时检查并恢复未完成订单

---

### 🟡 中风险问题

#### 6. Bybit MT5 部分成交

**问题描述**：
- MT5 订单可能部分成交
- 当前代码没有检查实际成交量

**建议修复**：
```python
# order_executor.py - place_mt5_order
result = mt5_client.place_order(...)
actual_filled = mt5_client.get_order_filled_volume(ticket)
if actual_filled < bybit_quantity_lot:
    logger.warning(f"MT5 partial fill: {actual_filled}/{bybit_quantity_lot}")
    # 补单或报警
```

---

#### 7. 阶梯执行卡住

**问题描述**：
- 某个阶梯因余额不足一直失败
- 无法跳过，卡住整个策略

**建议修复**：
- 添加阶梯跳过功能
- 连续失败N次后自动禁用策略

---

## 已验证正确的逻辑

### ✅ Binance 部分成交
- 使用实际成交量计算 Bybit 数量
- 阶梯进度正确更新
- 下次继续执行剩余数量

### ✅ 订单被交易所拒绝
- 捕获异常并返回失败
- 不执行对冲操作
- 显示错误通知

### ✅ 价格波动导致未成交
- 有超时机制（400ms）
- 超时后取消订单
- 策略保持启用，等待下次重试

### ✅ 持仓数据不一致
- 启用策略前重新获取持仓
- 后端执行前有 pre-check
- 有持仓比例检查（容差 0.01手）

---

## 测试建议

### 1. 测试多策略冲突
```
步骤：
1. 同时启用反向开仓和反向平仓
2. 手动触发两个策略同时满足条件
3. 观察：只有一个策略执行，另一个跳过
4. 观察：下次触发时被跳过的策略会执行
```

### 2. 测试禁用保护
```
步骤：
1. 启用开仓策略
2. 触发策略执行
3. 在执行过程中点击禁用按钮
4. 观察：显示"策略执行中，请稍后再试"
5. 等待执行完成后再次点击禁用
6. 观察：成功禁用
```

### 3. 测试阶梯进度持久化
```
步骤：
1. 启用开仓策略，配置3个阶梯
2. 执行第一个阶梯到50%
3. 刷新页面
4. 观察：阶梯进度保持在50%
5. 继续执行，观察从50%继续而不是从0%开始
```

### 4. 测试订单未成交
```
步骤：
1. 启用开仓策略
2. 设置挂单价格远离市场价（确保不成交）
3. 等待超时（400ms）
4. 观察：显示"等待下次自动重试"
5. 观察：策略保持启用状态
6. 调整价格到合理范围
7. 观察：下次触发时自动重试
```

---

## 总结

### 本次修复
- ✅ 修复了 3 个高/中风险问题
- ✅ 所有修复都在前端完成，无需后端改动
- ✅ 提高了系统稳定性和可靠性

### 剩余问题
- 🔴 2 个高风险问题需要后端支持
- 🟡 2 个中风险问题需要后端支持
- 📋 已在 EDGE_CASE_SCENARIOS.md 中详细记录

### 建议
1. 优先修复订单ID持久化（防止订单丢失）
2. 添加订单恢复机制（防止网络中断导致单腿）
3. 增强 MT5 成交量检查（防止部分成交）
4. 添加阶梯跳过功能（防止卡住）
