# Phase 3: 阶梯跳过功能 - 实施完成

## 实施日期
2026-03-06

## 功能概述
实现阶梯自动跳过机制，当某个阶梯连续失败达到最大次数（5次）时，自动跳过该阶梯并移动到下一个阶梯，避免策略卡在失败的阶梯上无法继续执行。

## 实施内容

### 1. 新增状态：`ladderFailureCounts`
**文件**: `frontend/src/components/trading/StrategyPanel.vue`

**定义**:
```javascript
const MAX_LADDER_FAILURES = 5
const ladderFailureCounts = ref({
  opening: {},  // {0: 3, 1: 0, 2: 5}
  closing: {}
})
```

**说明**:
- `MAX_LADDER_FAILURES`: 最大失败次数阈值（5次）
- `ladderFailureCounts.opening`: 开仓阶梯失败计数，键为ladder index
- `ladderFailureCounts.closing`: 平仓阶梯失败计数，键为ladder index

### 2. 新增方法：失败计数管理

#### `loadLadderFailureCounts()`
```javascript
function loadLadderFailureCounts() {
  try {
    const saved = localStorage.getItem(`ladder_failures_${configId.value}`)
    if (saved) {
      ladderFailureCounts.value = JSON.parse(saved)
    }
  } catch (error) {
    console.error('Failed to load ladder failure counts:', error)
  }
}
```

**功能**: 从localStorage加载失败计数（按configId区分不同策略）

#### `saveLadderFailureCounts()`
```javascript
function saveLadderFailureCounts() {
  try {
    localStorage.setItem(
      `ladder_failures_${configId.value}`,
      JSON.stringify(ladderFailureCounts.value)
    )
  } catch (error) {
    console.error('Failed to save ladder failure counts:', error)
  }
}
```

**功能**: 保存失败计数到localStorage

#### `resetLadderFailures(type)`
```javascript
function resetLadderFailures(type) {
  if (confirm(`确定要重置所有${type === 'opening' ? '开仓' : '平仓'}阶梯的失败计数吗？`)) {
    ladderFailureCounts.value[type] = {}
    saveLadderFailureCounts()
    notificationStore.showStrategyNotification('失败计数已重置', 'success')
  }
}
```

**功能**: 手动重置指定类型（开仓/平仓）的所有失败计数

### 3. 增强：`executeLadderOpening()` - 开仓阶梯跳过

**在函数开头添加跳过检查**:
```javascript
async function executeLadderOpening(ladderIndex, ladder) {
  // Phase 3: 检查阶梯失败次数，决定是否跳过
  const failureCount = ladderFailureCounts.value.opening[ladderIndex] || 0

  if (failureCount >= MAX_LADDER_FAILURES) {
    console.log(`Skipping ladder ${ladderIndex + 1} due to ${failureCount} consecutive failures`)

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

  // ... 原有执行逻辑
}
```

**成功时重置计数**:
```javascript
if (response.data.success) {
  // Phase 3: 成功执行，重置失败计数
  ladderFailureCounts.value.opening[ladderIndex] = 0
  saveLadderFailureCounts()

  // ... 原有成功处理逻辑
}
```

**失败时增加计数**:
```javascript
} else {
  // Phase 3: 失败时增加失败计数
  const currentFailures = ladderFailureCounts.value.opening[ladderIndex] || 0
  ladderFailureCounts.value.opening[ladderIndex] = currentFailures + 1
  saveLadderFailureCounts()

  console.log(`Ladder ${ladderIndex + 1} failed ${currentFailures + 1}/${MAX_LADDER_FAILURES} times`)

  // 如果达到最大失败次数，提示下次将自动跳过
  if (currentFailures + 1 >= MAX_LADDER_FAILURES) {
    notificationStore.showStrategyNotification(
      `阶梯 ${ladderIndex + 1} 已连续失败${currentFailures + 1}次，下次将自动跳过`,
      'error'
    )
  }

  // ... 原有失败处理逻辑
}
```

**异常时也增加计数**:
```javascript
} catch (error) {
  // Phase 3: 异常也算失败
  const currentFailures = ladderFailureCounts.value.opening[ladderIndex] || 0
  ladderFailureCounts.value.opening[ladderIndex] = currentFailures + 1
  saveLadderFailureCounts()

  // ... 原有异常处理逻辑
}
```

### 4. 增强：`executeLadderClosing()` - 平仓阶梯跳过

**实现与开仓相同的逻辑**:
- 函数开头检查失败次数并决定是否跳过
- 成功时重置失败计数
- 失败时增加失败计数
- 异常时增加失败计数

### 5. UI显示：失败计数徽章

**在阶梯配置中显示失败计数**:
```vue
<div class="flex items-center space-x-2">
  <span class="text-xs text-gray-400">阶梯 {{ index + 1 }}</span>
  <!-- Phase 3: 失败计数显示 -->
  <span
    v-if="(ladderFailureCounts.opening[index] || 0) > 0 || (ladderFailureCounts.closing[index] || 0) > 0"
    class="text-xs px-2 py-0.5 rounded bg-[#f6465d] bg-opacity-20 text-[#f6465d]"
  >
    失败: 开{{ ladderFailureCounts.opening[index] || 0 }}/平{{ ladderFailureCounts.closing[index] || 0 }}
  </span>
</div>
```

**显示效果**:
- 只在有失败记录时显示
- 红色背景徽章
- 格式：`失败: 开3/平2` （开仓失败3次，平仓失败2次）

### 6. UI控制：重置按钮

**在保存策略按钮下方添加重置按钮**:
```vue
<div class="grid grid-cols-2 gap-2 mt-2">
  <button
    @click="resetLadderFailures('opening')"
    class="px-3 py-1.5 bg-[#2b3139] text-gray-300 rounded text-xs hover:bg-[#3b4149] transition-colors"
  >
    重置开仓失败计数
  </button>
  <button
    @click="resetLadderFailures('closing')"
    class="px-3 py-1.5 bg-[#2b3139] text-gray-300 rounded text-xs hover:bg-[#3b4149] transition-colors"
  >
    重置平仓失败计数
  </button>
</div>
```

**功能**:
- 两个独立按钮分别重置开仓和平仓失败计数
- 点击时弹出确认对话框
- 重置后显示成功提示

## 执行流程

### 正常执行流程
1. 用户启用策略
2. 触发阶梯执行
3. 检查失败计数 < 5，继续执行
4. 执行成功 → 重置失败计数为0
5. 更新阶梯进度

### 失败处理流程
1. 执行失败或异常
2. 失败计数 +1
3. 保存到localStorage
4. 如果失败计数 >= 5，提示"下次将自动跳过"
5. 禁用策略（等待用户重新启用）

### 自动跳过流程
1. 用户重新启用策略
2. 触发阶梯执行
3. 检查失败计数 >= 5
4. 自动跳过：
   - 移动到下一个阶梯（currentLadderIndex++）
   - 重置completedQty为0
   - 重置该阶梯失败计数为0
   - 显示跳过通知
5. 下次触发时执行新阶梯

## 数据持久化

### localStorage存储
- **键名**: `ladder_failures_${configId}`
- **格式**:
  ```json
  {
    "opening": {"0": 3, "1": 0, "2": 5},
    "closing": {"0": 1, "2": 4}
  }
  ```
- **特点**:
  - 按configId区分不同策略
  - 只存储有失败记录的阶梯
  - 跨会话持久化

### 加载时机
- `onMounted()` 中，在 `loadConfigFromDB()` 之后
- 确保configId已设置

## 用户通知

### 1. 失败计数提示
- **时机**: 失败次数达到5次时
- **内容**: "阶梯 X 已连续失败5次，下次将自动跳过"
- **类型**: error（红色）

### 2. 自动跳过通知
- **时机**: 检测到失败次数>=5，执行跳过时
- **内容**: "阶梯 X 连续失败5次，已自动跳过"
- **类型**: warning（黄色）

### 3. 重置成功提示
- **时机**: 手动重置失败计数后
- **内容**: "失败计数已重置"
- **类型**: success（绿色）

## 优势

### 1. 自动化
- 无需人工干预，自动跳过失败阶梯
- 策略可以继续执行后续阶梯
- 避免卡在某个阶梯无法继续

### 2. 可见性
- UI实时显示失败计数
- 清晰的通知提示
- 用户可随时了解阶梯状态

### 3. 可控性
- 用户可手动重置失败计数
- 分别控制开仓和平仓
- 灵活应对不同情况

### 4. 持久化
- 失败计数跨会话保存
- 页面刷新不丢失数据
- 按策略配置独立存储

## 使用场景

### 场景1：市场条件不满足
- 某个阶梯的点差条件长期无法满足
- 连续失败5次后自动跳过
- 继续执行下一个阶梯

### 场景2：账户余额不足
- 某个阶梯需要的资金超过可用余额
- 连续失败5次后自动跳过
- 执行更小数量的后续阶梯

### 场景3：网络或系统问题
- 临时性问题导致某阶梯反复失败
- 达到阈值后自动跳过
- 问题解决后用户可手动重置计数

## 测试建议

### 1. 正常执行测试
- 执行成功后验证失败计数为0
- 确认不显示失败徽章

### 2. 失败计数测试
- 模拟执行失败
- 验证失败计数递增
- 确认UI显示正确

### 3. 自动跳过测试
- 让某阶梯失败5次
- 重新启用策略
- 验证自动跳过并移动到下一阶梯

### 4. 重置功能测试
- 点击重置按钮
- 验证失败计数清零
- 确认UI徽章消失

### 5. 持久化测试
- 刷新页面
- 验证失败计数保持
- 确认跨会话有效

## 配置参数

### MAX_LADDER_FAILURES
- **当前值**: 5
- **含义**: 连续失败多少次后自动跳过
- **调整**: 可根据实际需求修改此常量

## 风险评估

### 低风险
- 纯前端逻辑，不影响后端
- localStorage存储，易于清理
- 可随时手动重置

### 注意事项
- 跳过阶梯意味着放弃该阶梯的执行
- 用户应定期检查失败计数
- 必要时手动重置并重新尝试

## 回滚方案
如果需要禁用此功能：
1. 移除跳过检查逻辑（函数开头的if判断）
2. 移除失败计数更新代码
3. 隐藏UI中的失败徽章和重置按钮
4. 保留数据结构和方法，不影响系统稳定性

## 后续优化建议

### 1. 可配置阈值
允许用户自定义最大失败次数：
```javascript
const maxFailures = config.value.maxLadderFailures || 5
```

### 2. 失败原因记录
记录每次失败的具体原因：
```javascript
{
  "0": {
    "count": 3,
    "reasons": ["余额不足", "点差不满足", "网络超时"]
  }
}
```

### 3. 自动重试机制
在跳过前尝试自动修复：
- 调整下单数量
- 等待更好的市场条件
- 重新连接网络

### 4. 统计分析
记录跳过历史，用于：
- 分析哪些阶梯经常失败
- 优化阶梯配置
- 改进策略参数
