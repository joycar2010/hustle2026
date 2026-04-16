<template>
  <div class="px-2 py-2">
    <div class="flex items-center justify-between mb-2">
      <h1 class="text-sm font-bold">挂单查询</h1>
      <!-- 产品对选择器 -->
      <select v-model="currentPair"
        class="text-xs px-2 py-1 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary text-primary font-semibold">
        <option v-for="p in TRADING_PAIRS" :key="p.code" :value="p.code">{{ p.label }}</option>
      </select>
    </div>

    <!-- Filters -->
    <div class="card mb-2">
      <div class="flex flex-wrap items-center gap-2">
        <div class="flex items-center gap-1">
          <label class="text-xs text-gray-400">来源:</label>
          <select
            v-model="filterSource"
            class="px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
          >
            <option value="">全部</option>
            <option value="strategy">策略交易</option>
            <option value="manual">人工操作</option>
          </select>
        </div>

        <div class="flex items-center gap-1">
          <label class="text-xs text-gray-400">状态:</label>
          <select
            v-model="filterStatus"
            class="px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
          >
            <option value="new,pending">挂单中</option>
            <option value="">全部状态</option>
            <option value="filled">已成交</option>
            <option value="canceled,cancelled">已取消</option>
          </select>
        </div>

        <button @click="fetchOrders" class="btn-primary text-xs px-2 py-1">
          刷新
        </button>
      </div>
    </div>

    <!-- Orders Table -->
    <div class="card">
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-1.5 pr-2">时间</th>
              <th class="pb-1.5 pr-2">平台</th>
              <th class="pb-1.5 pr-2">交易对</th>
              <th class="pb-1.5 pr-2">方向</th>
              <th class="pb-1.5 pr-2">委托量</th>
              <th class="pb-1.5 pr-2">已成交量</th>
              <th class="pb-1.5 pr-2">价格</th>
              <th class="pb-1.5 pr-2">类型</th>
              <th class="pb-1.5 pr-2">状态</th>
              <th class="pb-1.5 pr-2">来源</th>
              <th class="pb-1.5">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="orders.length === 0">
              <td colspan="11" class="text-center py-4 text-gray-500 text-xs">暂无数据</td>
            </tr>
            <tr v-for="order in orders" :key="order.id" class="border-b border-gray-800">
              <td class="py-1.5 pr-2">{{ formatDateTimeBeijing(order.timestamp) }}</td>
              <td class="text-xs text-gray-400 pr-2">{{ order.exchange }}</td>
              <td class="pr-2">{{ order.symbol }}</td>
              <td class="pr-2">
                <span :class="order.side === 'buy' ? 'text-green-500' : 'text-red-500'">
                  {{ order.side === 'buy' ? '买入' : '卖出' }}
                </span>
              </td>
              <td class="pr-2">{{ order.quantity }}</td>
              <td class="pr-2 text-green-400">{{ order.filled_qty != null ? Number(order.filled_qty).toFixed(2) : '0.00' }}</td>
              <td class="pr-2">{{ order.price != null && order.price > 0 ? Number(order.price).toFixed(2) : '市价' }}</td>
              <td class="pr-2 text-xs text-gray-400">{{ order.order_type || order.type || '-' }}</td>
              <td class="pr-2">
                <span :class="getStatusClass(order.status)">
                  {{ getStatusText(order.status) }}
                </span>
              </td>
              <td class="pr-2">
                <span class="text-xs px-1.5 py-0.5 rounded" :class="getSourceClass(order.source)">
                  {{ getSourceText(order.source) }}
                </span>
              </td>
              <td>
                <button
                  v-if="order.status === 'new' || order.status === 'pending'"
                  @click="manualProcessOrder(order.id)"
                  class="text-xs px-2 py-0.5 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors"
                >
                  人工补单
                </button>
                <span v-else class="text-xs text-gray-500">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'
import { formatDateTimeBeijing } from '@/utils/timeUtils'
import { useTradingPair, TRADING_PAIRS } from '@/composables/useTradingPair'

const marketStore = useMarketStore()
const { currentPair } = useTradingPair()
const orders = ref([])
const filterSource = ref('')
const filterStatus = ref('new,pending')

onMounted(() => {
  // 初始加载
  fetchOrders()

  // 监听 WebSocket 推送的挂单更新
  watch(() => marketStore.lastMessage, (message) => {
    if (message && message.type === 'pending_orders') {
      // 如果当前筛选条件是挂单中，直接使用推送的数据
      if (filterStatus.value === 'new,pending' && !filterSource.value) {
        orders.value = message.data.slice(0, 8)
      }
    }
  })
})

watch([filterSource, filterStatus, currentPair], () => {
  fetchOrders()
})

async function fetchOrders() {
  try {
    // 所有状态都走实时 API（直接调 Binance，不依赖空数据库）
    const params = { status: filterStatus.value || 'new,pending', limit: 50, pair_code: currentPair.value }
    // 历史订单默认查最近7天
    if (filterStatus.value && filterStatus.value !== 'new,pending') {
      params.days = 7
    }
    if (filterSource.value) {
      params.source = filterSource.value
    }
    const response = await api.get('/api/v1/trading/orders/realtime', { params })
    orders.value = response.data.slice(0, 50)
  } catch (error) {
    console.error('Failed to fetch orders:', error)
  }
}

async function manualProcessOrder(orderId) {
  if (!confirm('确定要将此订单标记为已人工处理吗？')) return

  try {
    await api.post(`/api/v1/trading/orders/${orderId}/manual-process`)
    alert('订单已标记为人工处理')
    await fetchOrders()
  } catch (error) {
    console.error('Failed to process order:', error)
    alert('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function getStatusClass(status) {
  const classes = {
    new: 'text-yellow-500',
    pending: 'text-yellow-500',
    filled: 'text-green-500',
    canceled: 'text-red-500',
    cancelled: 'text-red-500',
    manually_processed: 'text-blue-500',
  }
  return classes[status] || 'text-gray-400'
}

function getStatusText(status) {
  const texts = {
    new: '挂单中',
    pending: '挂单中',
    filled: '已成交',
    canceled: '已取消',
    cancelled: '已取消',
    manually_processed: '已人工处理',
  }
  return texts[status] || status
}

function getSourceClass(source) {
  const classes = {
    manual: 'bg-blue-500/20 text-blue-400',
    strategy: 'bg-purple-500/20 text-purple-400',
    sync: 'bg-gray-500/20 text-gray-400',
  }
  return classes[source] || 'bg-gray-500/20 text-gray-400'
}

function getSourceText(source) {
  const texts = {
    manual: '人工',
    strategy: '策略',
    sync: '同步',
  }
  return texts[source] || source
}
</script>
