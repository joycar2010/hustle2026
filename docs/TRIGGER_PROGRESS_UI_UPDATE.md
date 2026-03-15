# 触发累积进度UI更新

## 更新内容

已在运行状态栏中添加触发累积进度的可视化显示，让用户能够直观地看到系统正在累积触发次数。

## 修改的文件

### 后端修改

#### 1. `backend/app/services/continuous_executor.py`

**修改内容**:
- 修改 `_push_trigger_progress` 方法，添加 `strategy_type` 参数
- 在推送的数据中添加 `action` 字段（'opening' 或 'closing'）
- 修改 `_push_trigger_reset` 方法，添加 `strategy_type` 参数和 `action` 字段

**关键代码**:
```python
async def _push_trigger_progress(
    self,
    ladder_idx: int,
    current_count: int,
    required_count: int,
    strategy_type: str  # 新增参数
):
    """Push trigger progress update via WebSocket"""
    if self.user_id:
        # Extract action from strategy_type
        action = 'opening' if 'opening' in strategy_type else 'closing'

        await status_pusher.push_custom_event(
            self.strategy_id,
            'trigger_progress',
            {
                'ladder_index': ladder_idx,
                'current_count': current_count,
                'required_count': required_count,
                'progress_percent': (current_count / required_count) * 100,
                'action': action,  # 新增字段
                'strategy_type': strategy_type  # 新增字段
            },
            self.user_id
        )
```

### 前端修改

#### 2. `frontend/src/components/trading/StrategyPanel.vue`

**修改内容**:

1. **添加响应式变量** (第 621 行):
```javascript
const continuousExecutionTriggerProgress = ref({
  opening: { current: 0, required: 0 },
  closing: { current: 0, required: 0 }
})
```

2. **更新 `handleTriggerProgress` 函数** (第 846-868 行):
```javascript
function handleTriggerProgress(data) {
  if (data.strategy_id !== configId.value) return

  const isContinuous = continuousExecutionEnabled.value[data.action]

  if (isContinuous) {
    // 更新连续执行触发进度
    continuousExecutionTriggerProgress.value[data.action] = {
      current: data.current_count,
      required: data.required_count
    }
  } else {
    // 更新普通触发计数
    if (data.action === 'opening') {
      triggerCount.value.opening = data.current_count
    } else if (data.action === 'closing') {
      triggerCount.value.closing = data.current_count
    }
  }
}
```

3. **添加 `handleTriggerReset` 函数** (第 870-890 行):
```javascript
function handleTriggerReset(data) {
  if (data.strategy_id !== configId.value) return

  const isContinuous = continuousExecutionEnabled.value[data.action]

  if (isContinuous) {
    // 重置连续执行触发进度
    continuousExecutionTriggerProgress.value[data.action] = {
      current: 0,
      required: continuousExecutionTriggerProgress.value[data.action].required
    }
  } else {
    // 重置普通触发计数
    if (data.action === 'opening') {
      triggerCount.value.opening = 0
    } else if (data.action === 'closing') {
      triggerCount.value.closing = 0
    }
  }
}
```

4. **在 WebSocket 消息处理中添加 trigger_reset 事件** (第 833 行):
```javascript
} else if (message.type === 'strategy_trigger_reset') {
  handleTriggerReset(message.data)
}
```

5. **在开仓状态显示中添加触发进度UI** (第 272-284 行):
```vue
<!-- Trigger Progress -->
<div v-if="continuousExecutionStatus.opening.status === 'running' && continuousExecutionTriggerProgress.opening.required > 0" class="mb-0.5">
  <div class="flex justify-between text-gray-400 mb-0.5">
    <span>触发进度:</span>
    <span class="text-white">{{ continuousExecutionTriggerProgress.opening.current }} / {{ continuousExecutionTriggerProgress.opening.required }}</span>
  </div>
  <div class="w-full bg-[#0d1117] rounded-full h-1.5">
    <div
      class="bg-[#0ecb81] h-1.5 rounded-full transition-all duration-300"
      :style="{ width: `${Math.min(100, (continuousExecutionTriggerProgress.opening.current / continuousExecutionTriggerProgress.opening.required) * 100)}%` }"
    ></div>
  </div>
</div>
```

6. **在平仓状态显示中添加触发进度UI** (第 312-324 行):
```vue
<!-- Trigger Progress -->
<div v-if="continuousExecutionStatus.closing.status === 'running' && continuousExecutionTriggerProgress.closing.required > 0" class="mb-0.5">
  <div class="flex justify-between text-gray-400 mb-0.5">
    <span>触发进度:</span>
    <span class="text-white">{{ continuousExecutionTriggerProgress.closing.current }} / {{ continuousExecutionTriggerProgress.closing.required }}</span>
  </div>
  <div class="w-full bg-[#0d1117] rounded-full h-1.5">
    <div
      class="bg-[#f6465d] h-1.5 rounded-full transition-all duration-300"
      :style="{ width: `${Math.min(100, (continuousExecutionTriggerProgress.closing.current / continuousExecutionTriggerProgress.closing.required) * 100)}%` }"
    ></div>
  </div>
</div>
```

7. **在启动连续执行时初始化触发进度** (第 1954-1959 行):
```javascript
// Initialize trigger progress
const triggerCount = action === 'opening' ? config.value.openingSyncQty : config.value.closingSyncQty
continuousExecutionTriggerProgress.value[action] = {
  current: 0,
  required: triggerCount || 1
}
```

8. **在停止连续执行时重置触发进度** (第 1989 行):
```javascript
continuousExecutionTriggerProgress.value[action] = { current: 0, required: 0 }
```

## UI 效果

### 开仓状态显示

```
┌─────────────────────────────────┐
│ 开仓状态                         │
├─────────────────────────────────┤
│ 状态: 运行中                     │
│ 触发进度: 1 / 2                  │
│ ████████████░░░░░░░░░░░░ 50%    │
│ 当前阶梯: 1                      │
│ 已执行交易: 0                    │
└─────────────────────────────────┘
```

### 平仓状态显示

```
┌─────────────────────────────────┐
│ 平仓状态                         │
├─────────────────────────────────┤
│ 状态: 运行中                     │
│ 触发进度: 2 / 2                  │
│ ████████████████████████ 100%   │
│ 当前阶梯: 1                      │
│ 已执行交易: 3                    │
└─────────────────────────────────┘
```

## 工作流程

1. **用户点击"连续开仓"按钮**
   - 前端初始化触发进度为 0/2（假设配置的触发次数是2）
   - 显示"开仓状态"面板

2. **系统开始累积触发**
   - 后端检测到点差满足条件，触发计数 +1
   - 通过 WebSocket 推送 `trigger_progress` 事件
   - 前端更新进度条：1/2 (50%)

3. **继续累积触发**
   - 后端再次检测到点差满足条件，触发计数 +1
   - 推送 `trigger_progress` 事件
   - 前端更新进度条：2/2 (100%)

4. **执行交易**
   - 触发次数达到要求，系统执行交易
   - 交易完成后，触发计数不重置，继续累积

5. **点差跌破阈值**
   - 后端检测到点差不再满足条件
   - 推送 `trigger_reset` 事件
   - 前端重置进度条：0/2 (0%)

## 优势

1. **直观可视化**: 用户可以清楚地看到触发累积的进度
2. **实时更新**: 通过 WebSocket 实时推送，无延迟
3. **区分状态**: 区分连续执行和普通执行的触发进度
4. **进度条动画**: 使用 CSS transition 实现平滑的进度条动画
5. **颜色区分**: 开仓使用绿色，平仓使用红色，易于识别

## 测试建议

1. **启动连续开仓**
   - 观察触发进度从 0 开始累积
   - 验证进度条动画流畅

2. **触发累积过程**
   - 观察触发计数逐步增加
   - 验证进度条百分比正确

3. **触发重置**
   - 在累积过程中，让点差跌破阈值
   - 观察进度条重置为 0

4. **交易执行**
   - 触发次数达到要求后
   - 观察交易执行，进度条继续显示

5. **停止执行**
   - 点击"停止开仓"按钮
   - 验证状态面板消失，进度重置

## 注意事项

1. **前端刷新**: 修改后需要硬刷新浏览器（Ctrl+F5）以加载最新代码
2. **WebSocket 连接**: 确保 WebSocket 连接正常，否则无法接收进度更新
3. **触发次数配置**: 触发进度基于配置的 `openingSyncQty` 和 `closingSyncQty`
4. **后端重启**: 后端代码修改后需要重启服务

---

**更新时间**: 2026-03-10
**版本**: v2.1 (触发进度可视化版本)
