<template>
  <div class="h-full flex flex-col gap-2 md:gap-3 p-2 md:p-3 min-h-0">
    <!-- Strategy Pending Orders -->
    <div class="flex-1 flex flex-col min-h-0 flex-shrink-0">
      <h3 class="text-xs md:text-sm font-bold mb-2 md:mb-3">策略挂单</h3>
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

    <!-- Spread Data Table -->
    <div class="flex-1 flex flex-col min-h-0">
      <SpreadDataTable />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'
import SpreadDataTable from './SpreadDataTable.vue'
import { formatTimeBeijing } from '@/utils/timeUtils'

const marketStore = useMarketStore()
const orders = ref([])
const pendingOrders = ref([])
const filterSource = ref('')
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

  // Removed polling - rely entirely on WebSocket
})

onUnmounted(() => {
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
    // 使用实时API获取Binance挂单
    const response = await api.get('/api/v1/trading/orders/realtime')
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
  return formatTimeBeijing(timestamp)
}
</script>
