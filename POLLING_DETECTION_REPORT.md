# 轮询残留检测报告

**扫描时间：** 2026-02-24T16:46:07.784024
**发现问题总数：** 22

## 问题统计

| 轮询频率 | 数量 | 优先级 |
|---------|------|--------|
| 🔴 高频 (≤1秒) | 6 | 紧急改造 |
| 🟡 中频 (1-5秒) | 11 | 优先改造 |
| 🟢 低频 (>5秒) | 5 | 可选改造 |

---

## 详细问题列表


### 📄 components\trading\SpreadChart.vue

#### 🔴 第114行 - 1.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchProfitData, 1000)
```

**上下文：**
```javascript
  initChart()
  fetchProfitData()
  updateInterval = setInterval(fetchProfitData, 1000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\SpreadDataTable.vue

#### 🔴 第45行 - 1.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchSpreadData, 1000)
```

**上下文：**
```javascript
onMounted(() => {
  fetchSpreadData()
  updateInterval = setInterval(fetchSpreadData, 1000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\StrategyPanel.vue

#### 🔴 第289行 - 1.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchStrategyData, 1000)
```

**上下文：**
```javascript

  fetchStrategyData()
  updateInterval = setInterval(fetchStrategyData, 1000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 views\Dashboard.vue

#### 🔴 第183行 - 1.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(updateLastUpdated, 1000)
```

**上下文：**
```javascript
  updateLastUpdated()
  fetchPrices()
  updateInterval = setInterval(updateLastUpdated, 1000)
  priceInterval = setInterval(fetchPrices, 1000)
})
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---

#### 🔴 第184行 - 1.0秒轮询

**问题代码：**
```javascript
priceInterval = setInterval(fetchPrices, 1000)
```

**上下文：**
```javascript
  fetchPrices()
  updateInterval = setInterval(updateLastUpdated, 1000)
  priceInterval = setInterval(fetchPrices, 1000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---

#### 🔴 第218行 - 1.0秒轮询

**问题代码：**
```javascript
await new Promise(resolve => setTimeout(resolve, 1000))
```

**上下文：**
```javascript
  } catch (error) {
    console.error('Failed to fetch prices:', error)
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await fetchPrices()
    await new Promise(resolve => setTimeout(resolve, 1000))
  } finally {
    refreshing.value = false
  }
}

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\modals\EditProfileModal.vue

#### 🟡 第145行 - 1.5秒轮询

**问题代码：**
```javascript
setTimeout(() => {
```

**上下文：**
```javascript
  try {
    const response = await api.put('/api/v1/users/profile', formData.value)

    // Update auth store with new user data
    authStore.updateUser(response.data)

    successMessage.value = '个人信息更新成功！'

    // Close modal after 1.5 seconds
    setTimeout(() => {
      emit('updated')
      closeModal()
    }, 1500)
  } catch (error) {
    console.error('Failed to update profile:', error)
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\MarketCards.vue

#### 🟡 第172行 - 2.0秒轮询

**问题代码：**
```javascript
lagTimer = setInterval(() => {
```

**上下文：**
```javascript
onMounted(() => {
  marketStore.connect()
  lagTimer = setInterval(() => {
    if (Date.now() - lastUpdateTime > 2000) {
      bybitLagCount.value++
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\OrderMonitor.vue

#### 🟡 第109行 - 3.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(() => {
```

**上下文：**
```javascript
  fetchOrders()
  fetchPendingOrders()
  updateInterval = setInterval(() => {
    fetchOrders()
    fetchPendingOrders()
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\ManualTrading.vue

#### 🟡 第156行 - 4.0秒轮询

**问题代码：**
```javascript
setTimeout(() => { statusMsg.value = '' }, 4000)
```

**上下文：**
```javascript
    recentOrders.value = response.data
  } catch (e) {
    console.error('Failed to fetch recent orders:', e)
  }
}

function showStatus(msg, ok = true) {
  statusMsg.value = msg
  statusOk.value = ok
  setTimeout(() => { statusMsg.value = '' }, 4000)
}

async function executeTrade(side) {
  if (loading.value) return
  loading.value = true
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---

#### 🟡 第133行 - 5.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchRecentOrders, 5000)
```

**上下文：**
```javascript
onMounted(() => {
  fetchRecentOrders()
  updateInterval = setInterval(fetchRecentOrders, 5000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\dashboard\SpreadChart.vue

#### 🟡 第94行 - 5.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchSpreadData, 5000)
```

**上下文：**
```javascript
  initChart()
  fetchSpreadData()
  updateInterval = setInterval(fetchSpreadData, 5000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\OpenOrders.vue

#### 🟡 第67行 - 5.0秒轮询

**问题代码：**
```javascript
setInterval(fetchOrders, 5000)
```

**上下文：**
```javascript
onMounted(() => {
  fetchOrders()
  setInterval(fetchOrders, 5000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\RiskDashboard.vue

#### 🟡 第86行 - 5.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchRiskData, 5000)
```

**上下文：**
```javascript
onMounted(() => {
  fetchRiskData()
  updateInterval = setInterval(fetchRiskData, 5000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 views\Risk.vue

#### 🟡 第300行 - 5.0秒轮询

**问题代码：**
```javascript
setInterval(fetchRiskData, 5000)
```

**上下文：**
```javascript
  fetchRiskData()
  fetchAlertSettings()
  setInterval(fetchRiskData, 5000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 views\System.vue

#### 🟡 第1256行 - 5.0秒轮询

**问题代码：**
```javascript
logRefreshInterval = setInterval(refreshLogs, 5000) // 每5秒刷新一次
```

**上下文：**
```javascript
  if (logRefreshInterval) return
  refreshLogs() // 立即刷新一次
  logRefreshInterval = setInterval(refreshLogs, 5000) // 每5秒刷新一次
}

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 composables\useAlertMonitoring.js

#### 🟡 第64行 - 5.0秒轮询

**问题代码：**
```javascript
marketCheckInterval = setInterval(checkMarketData, 5000)
```

**上下文：**
```javascript

    // Check market data every 5 seconds
    marketCheckInterval = setInterval(checkMarketData, 5000)

    // Check account data every 10 seconds
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---

#### 🟢 第67行 - 10.0秒轮询

**问题代码：**
```javascript
accountCheckInterval = setInterval(checkAccountData, 10000)
```

**上下文：**
```javascript

    // Check account data every 10 seconds
    accountCheckInterval = setInterval(checkAccountData, 10000)

    // Check MT5 status every 15 seconds
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---

#### 🟢 第70行 - 15.0秒轮询

**问题代码：**
```javascript
mt5CheckInterval = setInterval(checkMT5Status, 15000)
```

**上下文：**
```javascript

    // Check MT5 status every 15 seconds
    mt5CheckInterval = setInterval(checkMT5Status, 15000)

    // Initial checks
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\dashboard\AssetDashboard.vue

#### 🟢 第208行 - 10.0秒轮询

**问题代码：**
```javascript
refreshInterval = setInterval(fetchDashboardData, 10000)
```

**上下文：**
```javascript
  fetchDashboardData()
  // Refresh every 10 seconds
  refreshInterval = setInterval(fetchDashboardData, 10000)
})

```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 stores\notification.js

#### 🟢 第233行 - 10.0秒轮询

**问题代码：**
```javascript
await new Promise(resolve => setTimeout(resolve, 10000)) // 10 seconds
```

**上下文：**
```javascript
        : soundFile

      // Play the sound file the specified number of times
      const audio = new Audio(soundUrl)

      for (let i = 0; i < repeatCount; i++) {
        try {
          audio.currentTime = 0
          await audio.play()
          await new Promise(resolve => setTimeout(resolve, 10000)) // 10 seconds
          audio.pause()
        } catch (audioError) {
          // Fallback to Web Audio API if file not found
          console.log('Audio file not found, using Web Audio API')
          await playHelloMotoTone()
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


### 📄 components\trading\AccountStatusPanel.vue

#### 🟢 第170行 - 30.0秒轮询

**问题代码：**
```javascript
updateInterval = setInterval(fetchAccountData, 30000)
```

**上下文：**
```javascript
onMounted(() => {
  fetchAccountData()
  updateInterval = setInterval(fetchAccountData, 30000)
  // Restore WebSocket connection state from localStorage
  // Only auto-connect if it was connected before the page refresh
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---


## 改造优先级建议

### 🔴 紧急改造 (高频轮询 ≤1秒)

共 6 处，严重影响性能和服务器负载。

**文件列表：**
- components\trading\SpreadChart.vue (1处)
- components\trading\SpreadDataTable.vue (1处)
- components\trading\StrategyPanel.vue (1处)
- views\Dashboard.vue (3处)

### 🟡 优先改造 (中频轮询 1-5秒)

共 11 处，影响用户体验和资源消耗。

**文件列表：**
- components\dashboard\SpreadChart.vue (1处)
- components\modals\EditProfileModal.vue (1处)
- components\trading\ManualTrading.vue (2处)
- components\trading\MarketCards.vue (1处)
- components\trading\OpenOrders.vue (1处)
- components\trading\OrderMonitor.vue (1处)
- components\trading\RiskDashboard.vue (1处)
- composables\useAlertMonitoring.js (1处)
- views\Risk.vue (1处)
- views\System.vue (1处)

### 🟢 可选改造 (低频轮询 >5秒)

共 5 处，影响较小，可后续优化。

**文件列表：**
- components\dashboard\AssetDashboard.vue (1处)
- components\trading\AccountStatusPanel.vue (1处)
- composables\useAlertMonitoring.js (2处)
- stores\notification.js (1处)

---

## WebSocket改造指南

### 1. 引入market store

```javascript
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
```

### 2. 建立WebSocket连接

```javascript
onMounted(() => {
  marketStore.connect()
})

onUnmounted(() => {
  // 如果需要，可以断开连接
  // marketStore.disconnect()
})
```

### 3. 监听数据更新

```javascript
import { watch } from 'vue'

watch(() => marketStore.marketData, (newData) => {
  if (newData) {
    // 处理新数据
    console.log('收到市场数据:', newData)
  }
})
```

### 4. 移除轮询代码

```javascript
// ❌ 删除这些代码
// const timer = setInterval(fetchData, 1000)
// onUnmounted(() => clearInterval(timer))
```

---

**报告生成时间：** {datetime.utcnow().isoformat()}
