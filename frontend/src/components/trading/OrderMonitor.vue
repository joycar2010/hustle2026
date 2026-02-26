<template>
  <div class="h-full flex gap-3 p-3 min-h-0">
    <!-- Left: Strategy Pending Orders -->
    <div class="w-1/3 flex flex-col min-h-0">
      <h3 class="text-sm font-bold mb-3">策略挂单</h3>
      <div class="flex-1 overflow-y-auto">
        <table class="w-full text-xs">
          <thead class="sticky top-0 bg-[#1e2329]">
            <tr class="text-left text-gray-400 border-b border-[#2b3139]">
              <th class="p-2">时间</th>
              <th class="p-2">平台</th>
              <th class="p-2">方向</th>
              <th class="p-2">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="pendingOrders.length === 0">
              <td colspan="4" class="p-4 text-center text-gray-400">暂无挂单</td>
            </tr>
            <tr
              v-for="order in pendingOrders"
              :key="order.id"
              class="border-b border-[#2b3139] hover:bg-[#252930]"
            >
              <td class="p-2 text-gray-400">{{ formatTime(order.timestamp) }}</td>
              <td class="p-2 text-xs">{{ order.exchange }}</td>
              <td class="p-2">
                <span :class="order.side === 'buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                  {{ order.side === 'buy' ? '买' : '卖' }}
                </span>
              </td>
              <td class="p-2 font-mono">{{ order.quantity }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Right: Order Records -->
    <div class="flex-1 flex flex-col min-h-0">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold">订单记录</h3>
        <select
          v-model="filterSource"
          class="bg-[#252930] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
        >
          <option value="">全部类型</option>
          <option value="strategy">策略交易</option>
          <option value="manual">人工操作</option>
        </select>
      </div>
      <div class="flex-1 overflow-y-auto">
        <table class="w-full text-xs">
          <thead class="sticky top-0 bg-[#1e2329]">
            <tr class="text-left text-gray-400 border-b border-[#2b3139]">
              <th class="p-2">时间</th>
              <th class="p-2">平台</th>
              <th class="p-2">品种</th>
              <th class="p-2">方向</th>
              <th class="p-2">数量</th>
              <th class="p-2">价格</th>
              <th class="p-2">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="orders.length === 0">
              <td colspan="7" class="p-4 text-center text-gray-400">暂无记录</td>
            </tr>
            <tr
              v-for="order in orders"
              :key="order.id"
              class="border-b border-[#2b3139] hover:bg-[#252930]"
            >
              <td class="p-2 text-gray-400">{{ formatTime(order.timestamp) }}</td>
              <td class="p-2">{{ order.exchange }}</td>
              <td class="p-2 font-mono">{{ order.symbol }}</td>
              <td class="p-2">
                <span :class="order.side === 'buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                  {{ order.side === 'buy' ? '买入' : '卖出' }}
                </span>
              </td>
              <td class="p-2 font-mono">{{ order.quantity }}</td>
              <td class="p-2 font-mono">{{ order.price != null ? Number(order.price).toFixed(2) : '-' }}</td>
              <td class="p-2">
                <span :class="getStatusClass(order.status)">
                  {{ getStatusText(order.status) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const marketStore = useMarketStore()
const orders = ref([])
const pendingOrders = ref([])
const filterSource = ref('')
let updateInterval = null
let unwatchOrders = null

onMounted(() => {
  // Connect to WebSocket if not already connected
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Initial fetch
  fetchOrders()
  fetchPendingOrders()

  // Watch for order_update WebSocket messages
  unwatchOrders = watch(() => marketStore.lastMessage, (message) => {
    if (message && message.type === 'order_update') {
      handleOrderUpdate(message.data)
    }
  })

  // Reduced polling frequency as fallback (30s instead of 3s)
  updateInterval = setInterval(() => {
    fetchOrders()
    fetchPendingOrders()
  }, 30000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
  if (unwatchOrders) {
    unwatchOrders()
  }
})

watch(filterSource, () => {
  fetchOrders()
})

async function fetchOrders() {
  try {
    const params = { limit: 10 }
    if (filterSource.value) {
      params.source = filterSource.value
    }
    const response = await api.get('/api/v1/trading/orders', { params })
    orders.value = response.data
  } catch (error) {
    console.error('Failed to fetch orders:', error)
  }
}

async function fetchPendingOrders() {
  try {
    const response = await api.get('/api/v1/trading/orders', {
      params: { limit: 10, source: 'strategy', status: 'new,pending' }
    })
    pendingOrders.value = response.data
  } catch (error) {
    console.error('Failed to fetch pending orders:', error)
  }
}

function handleOrderUpdate(data) {
  // Update orders list with new order data
  if (data.order) {
    const order = data.order

    // Update main orders list
    const orderIndex = orders.value.findIndex(o => o.id === order.id)
    if (orderIndex !== -1) {
      orders.value[orderIndex] = order
    } else {
      // Add new order to the beginning
      orders.value.unshift(order)
      // Keep only last 10 orders
      if (orders.value.length > 10) {
        orders.value = orders.value.slice(0, 10)
      }
    }

    // Update pending orders list
    if (order.status === 'new' || order.status === 'pending') {
      const pendingIndex = pendingOrders.value.findIndex(o => o.id === order.id)
      if (pendingIndex !== -1) {
        pendingOrders.value[pendingIndex] = order
      } else if (order.source === 'strategy') {
        pendingOrders.value.unshift(order)
        if (pendingOrders.value.length > 10) {
          pendingOrders.value = pendingOrders.value.slice(0, 10)
        }
      }
    } else {
      // Remove from pending if status changed
      pendingOrders.value = pendingOrders.value.filter(o => o.id !== order.id)
    }
  }
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

function getStatusClass(status) {
  const classes = {
    new: 'text-[#f0b90b]',
    pending: 'text-[#f0b90b]',
    filled: 'text-[#0ecb81]',
    canceled: 'text-[#f6465d]',
    cancelled: 'text-[#f6465d]',
    manually_processed: 'text-[#3b82f6]',
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
</script>
