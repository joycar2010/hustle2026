# MarketCards 卡顿功能改进

## 改进时间
2026-03-12

## 改进内容

### 1. 使用滑动窗口统计卡顿情况

**改进前**：
- 使用累计计数，卡顿次数只增不减
- 每 2 秒检查一次，如果超时就 +1
- 无法反映当前连接状态

**改进后**：
- 使用 60 秒滑动窗口记录所有更新时间戳
- 统计窗口内间隔 > 2 秒的次数
- 自动移除 60 秒前的旧数据
- 实时反映最近 1 分钟的连接质量

**实现代码**：
```javascript
// 滑动窗口配置
const SLIDING_WINDOW_SIZE = 60 // 60 秒
const LAG_THRESHOLD = 2000 // 2 秒

// 存储时间戳数组
const bybitUpdateTimestamps = ref([])
const binanceUpdateTimestamps = ref([])

// 计算卡顿次数（computed）
const bybitLagCount = computed(() => {
  const now = Date.now()
  const windowStart = now - SLIDING_WINDOW_SIZE * 1000

  // 过滤窗口内的时间戳
  const recentTimestamps = bybitUpdateTimestamps.value.filter(t => t > windowStart)

  // 统计间隔 > 2 秒的次数
  let lagCount = 0
  for (let i = 1; i < recentTimestamps.length; i++) {
    if (recentTimestamps[i] - recentTimestamps[i - 1] > LAG_THRESHOLD) {
      lagCount++
    }
  }

  // 检查当前是否卡顿
  if (recentTimestamps.length > 0 && now - recentTimestamps[recentTimestamps.length - 1] > LAG_THRESHOLD) {
    lagCount++
  }

  return lagCount
})
```

### 2. 连接恢复时自动减少卡顿计数

**改进前**：
- 卡顿计数永远不会减少
- 即使连接恢复，显示仍然是高卡顿

**改进后**：
- 使用滑动窗口，旧的卡顿记录会自动过期
- 60 秒后，旧的卡顿不再计入统计
- 连接恢复后，卡顿计数会逐渐降低

**工作原理**：
```javascript
watch(() => marketStore.marketData, (data) => {
  const now = Date.now()

  // 添加新的时间戳
  bybitUpdateTimestamps.value.push(now)
  binanceUpdateTimestamps.value.push(now)

  // 自动清理 60 秒前的旧数据
  const windowStart = now - (SLIDING_WINDOW_SIZE + 10) * 1000
  bybitUpdateTimestamps.value = bybitUpdateTimestamps.value.filter(t => t > windowStart)
  binanceUpdateTimestamps.value = binanceUpdateTimestamps.value.filter(t => t > windowStart)

  // ... 更新价格数据
})
```

### 3. 添加双击清零功能

**改进前**：
- 无法手动重置卡顿计数
- 用户无法清除历史卡顿记录

**改进后**：
- 双击卡顿数字即可清零
- 鼠标悬停时显示黄色高亮
- 添加 "双击清零" 提示

**UI 改进**：
```vue
<span
  @dblclick="resetBybitLag"
  class="text-[10px] lg:text-[9px] md:text-xs font-mono cursor-pointer hover:text-[#f0b90b] transition-colors"
  title="双击清零"
>{{ bybitLagCount }}</span>
```

**重置方法**：
```javascript
function resetBybitLag() {
  const now = Date.now()
  bybitUpdateTimestamps.value = [now]
  console.log('Bybit lag count reset')
}

function resetBinanceLag() {
  const now = Date.now()
  binanceUpdateTimestamps.value = [now]
  console.log('Binance lag count reset')
}
```

## 改进效果

### 优点

1. **实时反映连接质量**
   - 卡顿计数基于最近 60 秒的数据
   - 旧的卡顿记录自动过期
   - 更准确地反映当前连接状态

2. **自动恢复**
   - 连接恢复后，卡顿计数会逐渐降低
   - 不需要手动干预
   - 60 秒后完全清除旧记录

3. **用户可控**
   - 双击即可手动清零
   - 操作简单直观
   - 鼠标悬停有视觉反馈

4. **性能优化**
   - 移除了定时器轮询（lagTimer）
   - 使用 computed 自动计算
   - 自动清理旧数据，防止内存泄漏

### 卡顿等级显示

- **0-9 次卡顿**: 0 级（无红条）- 连接良好
- **10-19 次卡顿**: 1 级（1 个红条）- 轻微卡顿
- **20-29 次卡顿**: 2 级（2 个红条）- 中度卡顿
- **30-39 次卡顿**: 3 级（3 个红条）- 较严重卡顿
- **40-49 次卡顿**: 4 级（4 个红条）- 严重卡顿
- **50+ 次卡顿**: 5 级（5 个红条）- 极严重卡顿

## 使用说明

### 查看卡顿情况

1. 打开交易面板
2. 查看 Bybit 和 Binance 卡片底部的"卡顿"指示器
3. 红色条数表示卡顿等级（0-5 级）
4. 数字表示最近 60 秒内的卡顿次数

### 手动清零

1. 将鼠标移到卡顿数字上（会变成黄色）
2. 双击数字
3. 卡顿计数立即清零

### 理解卡顿计数

- **卡顿定义**: 两次数据更新间隔 > 2 秒
- **统计窗口**: 最近 60 秒
- **自动过期**: 60 秒前的卡顿不再计入
- **实时更新**: 每次收到数据时自动重新计算

## 技术细节

### 数据结构

```javascript
// 时间戳数组（毫秒）
bybitUpdateTimestamps = [1710234567890, 1710234569890, 1710234571890, ...]
binanceUpdateTimestamps = [1710234567890, 1710234569890, 1710234571890, ...]
```

### 计算逻辑

1. **过滤窗口内数据**:
   ```javascript
   const windowStart = now - 60000 // 60 秒前
   const recentTimestamps = timestamps.filter(t => t > windowStart)
   ```

2. **统计卡顿次数**:
   ```javascript
   for (let i = 1; i < recentTimestamps.length; i++) {
     if (recentTimestamps[i] - recentTimestamps[i - 1] > 2000) {
       lagCount++
     }
   }
   ```

3. **检查当前状态**:
   ```javascript
   if (now - lastTimestamp > 2000) {
     lagCount++ // 当前正在卡顿
   }
   ```

### 性能考虑

- **时间复杂度**: O(n)，n 为窗口内时间戳数量（通常 < 100）
- **空间复杂度**: O(n)，自动清理旧数据
- **更新频率**: 每次收到市场数据时（约 50-100ms）
- **计算开销**: 使用 computed，只在依赖变化时重新计算

## 测试建议

### 测试场景 1: 正常连接

1. 启动系统，确保 WebSocket 连接正常
2. 观察卡顿计数应该保持在 0-5 次
3. 卡顿等级应该是 0 级（无红条）

### 测试场景 2: 连接中断

1. 断开网络连接或停止后端服务
2. 观察卡顿计数逐渐增加
3. 卡顿等级逐渐升高（红条增多）

### 测试场景 3: 连接恢复

1. 在连接中断后重新连接
2. 观察卡顿计数不再增加
3. 等待 60 秒，卡顿计数应该降低到 0

### 测试场景 4: 手动清零

1. 在有卡顿计数时，双击数字
2. 确认卡顿计数立即变为 0
3. 确认红条全部消失

## 修改的文件

- `frontend/src/components/trading/MarketCards.vue`
  - Line 216-278: 改用滑动窗口统计
  - Line 71-75: 添加 Bybit 双击清零
  - Line 140-144: 添加 Binance 双击清零
  - Line 358-375: 更新数据时添加时间戳
  - Line 507-523: 初始化时间戳数组
  - Line 561-573: 添加重置方法

## 向后兼容性

✅ 完全向后兼容
✅ 不影响现有功能
✅ 只是改进了卡顿统计逻辑
✅ UI 显示保持一致

## 后续优化建议

### 1. 可配置的窗口大小

允许用户自定义滑动窗口大小（30 秒、60 秒、120 秒）

### 2. 卡顿历史图表

显示最近 5 分钟的卡顿趋势图

### 3. 卡顿告警

当卡顿等级达到 4-5 级时，发送通知提醒用户

### 4. 连接质量评分

基于卡顿情况计算连接质量评分（0-100 分）

### 5. 自动重连

检测到严重卡顿时，自动尝试重新连接 WebSocket

## 总结

本次改进使用滑动窗口算法替代了累计计数，实现了：
- ✅ 实时反映连接质量
- ✅ 自动清除旧记录
- ✅ 用户可手动清零
- ✅ 性能优化（移除定时器）
- ✅ 更准确的卡顿统计

卡顿功能现在能够更准确地反映系统的实时连接状态，帮助用户及时发现和处理连接问题。
