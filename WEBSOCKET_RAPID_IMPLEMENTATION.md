# WebSocket改造快速实施指南

**目标：** 快速完成剩余20个组件的WebSocket改造
**预计时间：** 2-3天
**执行策略：** 扩展后端 → 批量改造 → 建立监控

---

## 第一阶段：后端WebSocket扩展 ✅ 已完成

### 新增推送类型

已在 `backend/app/websocket/manager.py` 中添加以下方法：

```python
# 1. 策略状态推送
async def broadcast_strategy_status(strategy_data: dict)

# 2. 账户余额推送
async def broadcast_account_balance(balance_data: dict)

# 3. 持仓更新推送
async def broadcast_position_update(position_data: dict)

# 4. 风险指标推送
async def broadcast_risk_metrics(risk_data: dict)
```

### 消息格式规范

所有WebSocket消息遵循统一格式：

```json
{
  "type": "message_type",
  "data": {
    // 具体数据
  },
  "timestamp": "2026-02-24T10:30:00Z"  // 可选
}
```

**支持的消息类型：**
- `market_data` - 市场数据（已实现）
- `risk_alert` - 风险警报（已实现）
- `order_update` - 订单更新（已实现）
- `strategy_status` - 策略状态（新增）
- `account_balance` - 账户余额（新增）
- `position_update` - 持仓更新（新增）
- `risk_metrics` - 风险指标（新增）

---

## 第二阶段：批量改造组件

### 改造优先级

#### 🔴 高优先级（立即执行）- 4个组件

**1. StrategyPanel.vue**
```
位置：frontend/src/components/trading/StrategyPanel.vue
轮询：1秒
改造模式：完全WebSocket化
需要消息：strategy_status
```

**改造代码模板：**
```javascript
import { useMarketStore } from '@/stores/market'
import { watch } from 'vue'

const marketStore = useMarketStore()

onMounted(() => {
  if (!marketStore.connected) {
    marketStore.connect()
  }
})

// 监听策略状态更新
watch(() => marketStore.marketData, (newData) => {
  if (newData && newData.type === 'strategy_status') {
    // 更新策略数据
    updateStrategyData(newData.data)
  }
})
```

---

**2. Dashboard.vue**
```
位置：frontend/src/views/Dashboard.vue
轮询：1秒（2处）
改造模式：完全WebSocket化
需要消息：account_balance, position_update
```

**改造要点：**
- 移除 `setInterval(updateLastUpdated, 1000)`
- 移除 `setInterval(fetchPrices, 1000)`
- 监听 `account_balance` 和 `position_update` 消息

---

**3. SpreadChart.vue (dashboard)**
```
位置：frontend/src/components/dashboard/SpreadChart.vue
轮询：5秒
改造模式：混合模式（复用trading版本）
需要消息：market_data
```

**改造要点：**
- 直接复用 `components/trading/SpreadChart.vue` 的改造方案
- 首次加载历史数据 + WebSocket实时更新

---

#### 🟡 中优先级（本周完成）- 11个组件

**主要组件列表：**
1. RiskDashboard.vue - 5秒轮询 → risk_metrics
2. OrderMonitor.vue - 轮询 → order_update
3. Risk.vue - 5秒轮询 → risk_metrics
4. AssetDashboard.vue - 10秒轮询 → account_balance
5. AccountStatusPanel.vue - 30秒轮询 → account_balance
6. 其他6个组件

---

### 快速改造流程

#### 步骤1：确定改造模式

**完全WebSocket化：**
- 适用于：实时数据流组件
- 特点：无HTTP请求，纯WebSocket
- 示例：SpreadDataTable.vue

**混合模式：**
- 适用于：需要历史数据的图表
- 特点：首次加载API + WebSocket追加
- 示例：SpreadChart.vue

---

#### 步骤2：修改组件代码

**模板A：完全WebSocket化**

```javascript
<script setup>
import { ref, onMounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
const data = ref([])

onMounted(() => {
  if (!marketStore.connected) {
    marketStore.connect()
  }
})

watch(() => marketStore.marketData, (newData) => {
  if (newData) {
    // 处理新数据
    data.value = processData(newData)
  }
})

// ❌ 删除这些代码
// let updateInterval = null
// onMounted(() => {
//   updateInterval = setInterval(fetchData, 1000)
// })
// onUnmounted(() => {
//   clearInterval(updateInterval)
// })
</script>
```

---

**模板B：混合模式**

```javascript
<script setup>
import { ref, onMounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const marketStore = useMarketStore()
const data = ref([])

onMounted(() => {
  // 首次加载历史数据
  fetchInitialData()

  // 建立WebSocket连接
  if (!marketStore.connected) {
    marketStore.connect()
  }
})

// WebSocket实时追加
watch(() => marketStore.marketData, (newData) => {
  if (newData && data.value.length > 0) {
    // 追加新数据点
    data.value = [...data.value, newData].slice(-maxPoints)
  }
})

// 首次加载历史数据
async function fetchInitialData() {
  const response = await api.get('/api/v1/...')
  data.value = response.data
}

// ❌ 删除轮询代码
// let updateInterval = null
// onMounted(() => {
//   updateInterval = setInterval(fetchData, 1000)
// })
</script>
```

---

#### 步骤3：测试验证

**验证清单：**
- [ ] WebSocket连接正常
- [ ] 数据实时更新
- [ ] Network标签无轮询请求
- [ ] 组件功能正常
- [ ] 无控制台错误

**测试命令：**
```bash
# 运行轮询检测
python scripts/detect_polling.py --project-root frontend/src --output report.md

# 查看剩余轮询数量
grep "Total polling issues found" report.md
```

---

## 第三阶段：建立监控机制

### 1. 前端WebSocket状态监控

**创建监控组件：** `frontend/src/components/WebSocketMonitor.vue`

```vue
<template>
  <div v-if="showMonitor" class="fixed bottom-4 right-4 bg-dark-200 rounded p-3 shadow-lg">
    <div class="flex items-center space-x-2">
      <div :class="statusClass" class="w-3 h-3 rounded-full"></div>
      <span class="text-sm">WebSocket: {{ statusText }}</span>
    </div>
    <div class="text-xs text-gray-400 mt-1">
      消息数: {{ messageCount }} | 延迟: {{ latency }}ms
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
const showMonitor = ref(true)
const messageCount = ref(0)
const latency = ref(0)
const lastMessageTime = ref(Date.now())

const statusClass = computed(() => {
  if (!marketStore.connected) return 'bg-red-500'
  if (latency.value > 5000) return 'bg-yellow-500'
  return 'bg-green-500'
})

const statusText = computed(() => {
  if (!marketStore.connected) return '未连接'
  if (latency.value > 5000) return '延迟高'
  return '已连接'
})

watch(() => marketStore.marketData, () => {
  messageCount.value++
  const now = Date.now()
  latency.value = now - lastMessageTime.value
  lastMessageTime.value = now
})
</script>
```

---

### 2. 后端性能监控

**添加监控端点：** `backend/app/api/v1/websocket_stats.py`

```python
from fastapi import APIRouter, Depends
from app.websocket.manager import manager
from app.core.auth import get_current_user_id

router = APIRouter()

@router.get("/websocket/stats")
async def get_websocket_stats(user_id: str = Depends(get_current_user_id)):
    """获取WebSocket连接统计"""
    return {
        "total_connections": manager.get_connection_count(),
        "user_connections": manager.get_user_connection_count(user_id),
        "active_users": len(manager.active_connections),
    }
```

---

### 3. 防回归机制

#### Pre-commit Hook

**创建：** `.git/hooks/pre-commit`

```bash
#!/bin/bash

echo "🔍 检查WebSocket改造..."

# 检查是否新增setInterval
if git diff --cached --name-only | grep -E '\.(vue|js|ts)$' | xargs grep -n 'setInterval' 2>/dev/null; then
    echo "❌ 发现新增setInterval，请使用WebSocket替代轮询"
    echo "参考文档: WEBSOCKET_QUICK_GUIDE.md"
    exit 1
fi

# 检查是否新增setTimeout递归
if git diff --cached --name-only | grep -E '\.(vue|js|ts)$' | xargs grep -n 'setTimeout.*function' 2>/dev/null; then
    echo "⚠️  发现setTimeout，请确认不是递归轮询"
fi

echo "✅ WebSocket检查通过"
exit 0
```

**安装：**
```bash
chmod +x .git/hooks/pre-commit
```

---

#### CI/CD检查

**GitHub Actions：** `.github/workflows/websocket-check.yml`

```yaml
name: WebSocket Check

on: [push, pull_request]

jobs:
  check-polling:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'

      - name: Run polling detection
        run: |
          python scripts/detect_polling.py --project-root frontend/src --output report.md

      - name: Check for high frequency polling
        run: |
          if grep -q "HIGH frequency.*: [1-9]" report.md; then
            echo "❌ 发现高频轮询，请改为WebSocket"
            cat report.md
            exit 1
          fi
          echo "✅ 无高频轮询"
```

---

## 快速执行计划

### Day 1：高频组件改造

**上午：**
- [ ] 改造 StrategyPanel.vue
- [ ] 改造 Dashboard.vue

**下午：**
- [ ] 改造 SpreadChart.vue (dashboard)
- [ ] 测试验证所有高频组件
- [ ] 提交代码

**预期成果：**
- 高频组件改造完成率：100%（6/6）
- HTTP请求减少：240次/分钟

---

### Day 2：中频组件改造

**上午：**
- [ ] 改造 RiskDashboard.vue
- [ ] 改造 OrderMonitor.vue
- [ ] 改造 Risk.vue

**下午：**
- [ ] 改造 AssetDashboard.vue
- [ ] 改造 AccountStatusPanel.vue
- [ ] 改造其他6个中频组件

**预期成果：**
- 中频组件改造完成率：100%（11/11）
- HTTP请求减少：额外60次/分钟

---

### Day 3：监控和优化

**上午：**
- [ ] 创建WebSocket监控组件
- [ ] 添加后端统计端点
- [ ] 配置pre-commit hook

**下午：**
- [ ] 配置CI/CD检查
- [ ] 全面测试验证
- [ ] 性能测试和优化
- [ ] 更新文档

**预期成果：**
- 监控机制建立完成
- 防回归机制生效
- 全部22个组件改造完成

---

## 验证标准

### 功能验证

**检查清单：**
- [ ] 所有组件数据实时更新
- [ ] WebSocket连接稳定
- [ ] 无轮询残留
- [ ] 无控制台错误
- [ ] 用户体验良好

**验证命令：**
```bash
# 1. 运行轮询检测
python scripts/detect_polling.py --project-root frontend/src --output final_report.md

# 2. 检查结果
cat final_report.md | grep "Total polling issues found"
# 期望输出: Total polling issues found: 0

# 3. WebSocket连接测试
python scripts/test_websocket.py --timeout 30

# 4. 性能测试
# 打开Chrome DevTools
# Network标签 → 统计1分钟内的HTTP请求数
# 期望: ≤60次/分钟
```

---

### 性能验证

**对比指标：**

| 指标 | 改造前 | 改造后 | 目标 |
|------|--------|--------|------|
| HTTP请求/分钟 | 320 | ≤60 | -81% |
| 网络流量/小时 | 192MB | ≤20MB | -90% |
| 数据延迟 | 1-5秒 | <100ms | -98% |
| WebSocket连接数 | 0 | 1 | 稳定 |

---

## 常见问题

### Q1：改造后数据不更新？

**检查：**
1. WebSocket是否连接：`marketStore.connected`
2. 是否监听正确的消息类型
3. 数据处理逻辑是否正确

**解决：**
```javascript
// 添加调试日志
watch(() => marketStore.marketData, (newData) => {
  console.log('收到WebSocket消息:', newData)
  // 处理数据...
})
```

---

### Q2：页面刷新后无历史数据？

**解决：**
使用混合模式，首次加载时调用API获取历史数据：

```javascript
onMounted(() => {
  fetchInitialData()  // 获取历史数据
  marketStore.connect()  // 建立WebSocket
})
```

---

### Q3：WebSocket频繁断线重连？

**检查：**
1. 网络连接是否稳定
2. 服务器是否正常运行
3. 心跳机制是否正常

**优化：**
- 实现指数退避重连
- 添加显式心跳机制
- 增加连接超时时间

---

## 资源清单

**文档：**
- `WEBSOCKET_FINAL_SUMMARY.md` - 完整总结
- `WEBSOCKET_QUICK_GUIDE.md` - 快速参考
- `WEBSOCKET_MIGRATION_PROGRESS.md` - 进度跟踪

**工具：**
- `scripts/test_websocket.py` - 连接测试
- `scripts/detect_polling.py` - 轮询检测

**代码示例：**
- `SpreadDataTable.vue` - 完全WebSocket化
- `SpreadChart.vue` - 混合模式

---

## 总结

通过这个快速实施指南，您可以在2-3天内完成：

✅ 扩展后端WebSocket推送类型（4种新类型）
✅ 批量改造剩余20个组件
✅ 建立完整的监控和防回归机制

**最终成果：**
- 22个组件全部改造完成
- HTTP请求减少81%
- 数据实时性提升98%
- 建立完整的监控体系

**开始执行：**
1. 按照Day 1计划改造高频组件
2. 使用提供的代码模板快速实施
3. 每完成一个组件立即测试验证
4. 遇到问题参考常见问题解答

祝改造顺利！🚀
