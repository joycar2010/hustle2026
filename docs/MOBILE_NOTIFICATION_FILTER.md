# 移动端通知过滤优化

## 实施时间
2026-03-12

## 问题描述

在 iPad 和手机端，频繁的通知弹窗会影响用户的下单操作，特别是：
- 套利开仓/平仓机会提醒（每次点差变化都可能触发）
- MT5 卡顿预警
- 策略执行成功/失败通知

这些通知在移动端会遮挡操作按钮，影响用户体验。

## 解决方案

### 实施策略

**桌面端（≥768px）**：
- 显示所有通知类型
- 保持原有行为不变

**移动端/iPad（<768px）**：
- 只显示关键通知（critical notifications）
- 过滤掉非关键通知，避免干扰下单操作

### 移动端显示的通知类型

只显示以下 6 种关键通知：

1. **单腿交易警告** (`single_leg_alert`)
   - 最高优先级
   - 表示套利交易只有一边成交，存在风险
   - 必须立即处理

2. **总资产预警** (`total_asset`)
   - 账户总资产低于阈值
   - 可能影响持仓安全

3. **Binance 净资产预警** (`binance_asset`)
   - Binance 账户净资产不足
   - 可能导致爆仓风险

4. **Bybit MT5 净资产预警** (`bybit_asset`)
   - Bybit MT5 账户净资产不足
   - 可能导致爆仓风险

5. **Binance 爆仓价预警** (`binance_liquidation`)
   - 当前价格接近 Binance 爆仓价
   - 紧急风险提示

6. **Bybit 爆仓价预警** (`bybit_liquidation`)
   - 当前价格接近 Bybit 爆仓价
   - 紧急风险提示

### 移动端不显示的通知类型

以下通知在移动端不弹窗显示（但仍会记录在通知列表中）：

1. **套利开仓机会** (`forward_open`, `reverse_open`)
   - 频繁触发
   - 用户可以通过点差数据自行判断

2. **套利平仓机会** (`forward_close`, `reverse_close`)
   - 频繁触发
   - 用户可以通过点差数据自行判断

3. **MT5 卡顿预警** (`mt5_lag`)
   - 非紧急通知
   - 不影响当前操作

4. **策略执行通知** (`strategy_notification`)
   - 成功/失败通知
   - 用户已经在操作界面，不需要额外弹窗

5. **风险警报** (`risk_alert`)
   - 取决于具体类型
   - 如果是 critical 级别，会通过其他类型显示

## 技术实现

### 修改文件
`frontend/src/components/NotificationPopup.vue`

### 核心代码

```vue
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useNotificationStore } from '@/stores/notification'
import dayjs from 'dayjs'

const notificationStore = useNotificationStore()
const isMobile = ref(false)

function checkMobile() {
  isMobile.value = window.innerWidth < 768
}

// Filter notifications for mobile devices
const shouldShowPopup = computed(() => {
  if (!notificationStore.activePopup) return false

  // On desktop, show all notifications
  if (!isMobile.value) return true

  // On mobile/iPad, only show critical notifications
  const popup = notificationStore.activePopup
  const criticalTypes = [
    'single_leg_alert',      // 单腿交易警告
    'total_asset',           // 总资产预警
    'binance_asset',         // Binance净资产预警
    'bybit_asset',           // Bybit MT5净资产预警
    'binance_liquidation',   // 爆仓价预警
    'bybit_liquidation'      // 爆仓价预警
  ]

  return criticalTypes.includes(popup.type)
})
</script>

<template>
  <Transition :name="isMobile ? 'slide-down' : 'slide-up'">
    <div v-if="shouldShowPopup" class="...">
      <!-- Notification content -->
    </div>
  </Transition>
</template>
```

### 关键改动

1. **添加 `shouldShowPopup` computed 属性**
   - 替代原来的 `notificationStore.activePopup` 直接判断
   - 根据设备类型和通知类型决定是否显示

2. **移动端检测**
   - 使用 `window.innerWidth < 768` 判断移动端
   - 响应窗口大小变化

3. **通知类型白名单**
   - 定义 `criticalTypes` 数组
   - 只有在白名单中的通知类型才在移动端显示

## 用户体验改进

### 改进前
- ❌ 移动端频繁弹窗，遮挡操作按钮
- ❌ 套利机会提醒每次点差变化都弹窗
- ❌ 策略执行成功也弹窗，干扰用户
- ❌ 用户需要频繁关闭通知才能继续操作

### 改进后
- ✅ 移动端只显示关键风险通知
- ✅ 套利机会提醒不弹窗，用户可通过点差数据判断
- ✅ 策略执行通知不弹窗，减少干扰
- ✅ 用户可以专注于下单操作
- ✅ 关键风险（单腿、资产不足、爆仓）仍会及时提醒

## 其他建议

### 建议 1: 添加通知中心
在移动端添加一个通知中心图标，用户可以主动查看所有通知：

```vue
<!-- 在顶部导航栏添加 -->
<button @click="showNotificationCenter" class="relative">
  <BellIcon class="w-5 h-5" />
  <span v-if="unreadCount > 0" class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center">
    {{ unreadCount }}
  </span>
</button>
```

### 建议 2: 添加通知优先级设置
允许用户自定义哪些通知在移动端显示：

```vue
<!-- 在设置页面添加 -->
<div class="notification-settings">
  <h3>移动端通知设置</h3>
  <label>
    <input type="checkbox" v-model="settings.showSingleLeg" />
    单腿交易警告
  </label>
  <label>
    <input type="checkbox" v-model="settings.showAssetWarning" />
    资产预警
  </label>
  <label>
    <input type="checkbox" v-model="settings.showLiquidation" />
    爆仓价预警
  </label>
  <label>
    <input type="checkbox" v-model="settings.showSpreadOpportunity" />
    套利机会提醒
  </label>
</div>
```

### 建议 3: 使用 Toast 替代弹窗
对于非关键通知，使用轻量级的 Toast 提示：

```vue
<!-- Toast 组件 -->
<div class="fixed top-16 left-1/2 -translate-x-1/2 z-40">
  <div class="bg-gray-800 text-white px-4 py-2 rounded-lg shadow-lg text-sm">
    {{ message }}
  </div>
</div>
```

### 建议 4: 添加"勿扰模式"
在交易高峰期，允许用户临时关闭所有非关键通知：

```vue
<button @click="toggleDoNotDisturb" class="...">
  <span v-if="doNotDisturb">🔕 勿扰模式</span>
  <span v-else>🔔 通知开启</span>
</button>
```

### 建议 5: 通知分组和折叠
相同类型的通知可以分组显示，避免重复弹窗：

```vue
<div v-if="groupedNotifications.spread.length > 1">
  <div class="notification-group">
    <span>套利机会 ({{ groupedNotifications.spread.length }})</span>
    <button @click="expandGroup('spread')">展开</button>
  </div>
</div>
```

## 测试验证

### 测试场景 1: 桌面端
1. 在桌面浏览器（宽度 ≥ 768px）打开应用
2. 触发各种类型的通知
3. **预期结果**: 所有通知都正常弹窗显示

### 测试场景 2: 移动端 - 关键通知
1. 在移动设备或 iPad（宽度 < 768px）打开应用
2. 触发单腿交易警告
3. **预期结果**: 通知正常弹窗显示

### 测试场景 3: 移动端 - 非关键通知
1. 在移动设备或 iPad（宽度 < 768px）打开应用
2. 触发套利开仓机会提醒
3. **预期结果**: 通知不弹窗，但记录在通知列表中

### 测试场景 4: 响应式切换
1. 在桌面浏览器打开应用
2. 触发套利开仓机会提醒（应该显示）
3. 调整浏览器窗口到移动端尺寸
4. 再次触发套利开仓机会提醒
5. **预期结果**: 第二次不显示弹窗

### 测试场景 5: 多个通知
1. 在移动端触发多个通知（包括关键和非关键）
2. **预期结果**: 只有关键通知弹窗，非关键通知不弹窗

## 监控指标

### 用户体验指标
- 移动端通知弹窗频率（应该显著降低）
- 用户手动关闭通知的次数（应该减少）
- 下单操作的完成时间（应该缩短）

### 风险指标
- 单腿交易的响应时间（不应该增加）
- 资产预警的触达率（应该保持 100%）
- 爆仓价预警的触达率（应该保持 100%）

## 总结

### 核心改进
✅ 移动端只显示关键通知（单腿、资产不足、爆仓）
✅ 桌面端保持原有行为不变
✅ 响应式设计，自动适配设备尺寸
✅ 不影响通知记录和历史查询

### 用户收益
- 移动端操作更流畅，不被频繁弹窗打断
- 关键风险仍能及时提醒，不会遗漏
- 可以专注于交易决策，减少干扰

### 技术优势
- 实现简单，只修改一个组件
- 性能无影响，使用 computed 属性
- 易于扩展，可以轻松调整白名单
- 向后兼容，不影响现有功能

## 附录：通知类型完整列表

### 市场通知
- `forward_open`: 正向套利开仓机会
- `forward_close`: 正向套利平仓机会
- `reverse_open`: 反向套利开仓机会
- `reverse_close`: 反向套利平仓机会

### 账户通知
- `binance_asset`: Binance 净资产预警 ✅ 移动端显示
- `bybit_asset`: Bybit MT5 净资产预警 ✅ 移动端显示
- `total_asset`: 总资产预警 ✅ 移动端显示

### 风险通知
- `binance_liquidation`: Binance 爆仓价预警 ✅ 移动端显示
- `bybit_liquidation`: Bybit 爆仓价预警 ✅ 移动端显示
- `single_leg_alert`: 单腿交易警告 ✅ 移动端显示

### 系统通知
- `mt5_lag`: MT5 卡顿预警
- `strategy_notification`: 策略执行通知
- `risk_alert`: 风险警报（取决于具体类型）
