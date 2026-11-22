<template>
  <div class="card">
    <h3 class="text-lg font-bold mb-4">Open Orders</h3>

    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-gray-400 border-b border-gray-700">
            <th class="pb-2">Time</th>
            <th class="pb-2">Symbol</th>
            <th class="pb-2">Direction</th>
            <th class="pb-2">Quantity</th>
            <th class="pb-2">Status</th>
            <th class="pb-2">P&L</th>
            <th class="pb-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="order in orders" :key="order.id" class="border-b border-gray-800">
            <td class="py-3">{{ formatTime(order.created_at) }}</td>
            <td>{{ order.symbol }}</td>
            <td>
              <span :class="order.direction === 'forward' ? 'text-green-500' : 'text-red-500'">
                {{ order.direction }}
              </span>
            </td>
            <td>{{ order.quantity }}</td>
            <td>
              <span class="px-2 py-1 rounded text-xs" :class="getStatusClass(order.status)">
                {{ order.status }}
              </span>
            </td>
            <td :class="order.pnl >= 0 ? 'text-green-500' : 'text-red-500'">
              {{ formatPnL(order.pnl) }}
            </td>
            <td>
              <button
                v-if="order.status === 'open'"
                @click="closeOrder(order.id)"
                class="text-red-500 hover:text-red-400 text-xs"
              >
                Close
              </button>
            </td>
          </tr>

          <tr v-if="!orders.length">
            <td colspan="7" class="text-center text-gray-400 py-8">
              No open orders
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import dayjs from 'dayjs'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
const orders = ref([])

onMounted(async () => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Initial fetch
  await fetchOrders()
})

onUnmounted(() => {
  // No cleanup needed - WebSocket stays connected
})

// Watch for order updates via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'order_update') {
    handleOrderUpdate(message.data)
  }
})

function handleOrderUpdate(orderData) {
  // Update or add order in the list
  const index = orders.value.findIndex(o => o.order_id === orderData.order_id)
  if (index !== -1) {
    orders.value[index] = { ...orders.value[index], ...orderData }
  } else {
    // New order, fetch full list to ensure consistency
    fetchOrders()
  }
}

async function fetchOrders() {
  try {
    const response = await api.get('/api/v1/strategies/tasks?status=open')
    orders.value = response.data
  } catch (error) {
    console.error('Failed to fetch orders:', error)
  }
}

async function closeOrder(orderId) {
  try {
    await api.post(`/api/v1/strategies/tasks/${orderId}/close`)
    await fetchOrders()
  } catch (error) {
    console.error('Failed to close order:', error)
  }
}

function formatTime(time) {
  return dayjs(time).format('MM-DD HH:mm:ss')
}

function formatPnL(pnl) {
  return pnl ? `$${pnl.toFixed(2)}` : '$0.00'
}

function getStatusClass(status) {
  const classes = {
    open: 'bg-blue-500/20 text-blue-400',
    closed: 'bg-gray-500/20 text-gray-400',
    filled: 'bg-green-500/20 text-green-400',
    cancelled: 'bg-red-500/20 text-red-400'
  }
  return classes[status] || 'bg-gray-500/20 text-gray-400'
}
</script>
