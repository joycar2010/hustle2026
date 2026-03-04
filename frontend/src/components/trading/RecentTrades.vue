<template>
  <div class="h-full flex flex-col p-3">
    <div class="flex-1 overflow-y-auto space-y-1">
      <div v-if="recentOrders.length === 0" class="text-xs text-gray-500 text-center py-4">
        暂无记录
      </div>
      <div
        v-for="order in recentOrders"
        :key="order.id"
        class="flex items-center justify-between text-xs bg-[#252930] rounded px-2 py-2 hover:bg-[#2b3139] transition-colors"
      >
        <div class="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
          <span class="text-gray-500">{{ formatTime(order.timestamp) }}</span>
          <span class="text-gray-400">{{ order.exchange }}</span>
          <span :class="order.side === 'buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ order.side === 'buy' ? '买' : '卖' }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-mono">{{ order.quantity }}</span>
          <span :class="getStatusClass(order.status)" class="text-xs">
            {{ getStatusText(order.status) }}
          </span>
        </div>
      </div>
    </div>
    <button
      @click="viewMore"
      class="w-full mt-2 text-xs text-[#f0b90b] hover:text-[#f0b90b]/80 transition-colors py-2"
    >
      查看更多 →
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'
import { formatTimeBeijing } from '@/utils/timeUtils'

const router = useRouter()
const marketStore = useMarketStore()
const recentOrders = ref([])

onMounted(async () => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Initial fetch
  await fetchRecentOrders()
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
  // If it's a manual order, update the recent orders list
  if (orderData.source === 'manual') {
    const index = recentOrders.value.findIndex(o => o.id === orderData.id)
    if (index !== -1) {
      recentOrders.value[index] = { ...recentOrders.value[index], ...orderData }
    } else {
      // New order, add to top and keep only 10
      recentOrders.value = [orderData, ...recentOrders.value].slice(0, 10)
    }
  }
}

async function fetchRecentOrders() {
  try {
    const response = await api.get('/api/v1/trading/orders', {
      params: { limit: 10, source: 'manual' }
    })
    recentOrders.value = response.data
  } catch (e) {
    console.error('Failed to fetch recent orders:', e)
  }
}

function viewMore() {
  router.push('/trading')
}

function formatTime(timestamp) {
  return formatTimeBeijing(timestamp)
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
    new: '挂单',
    pending: '挂单',
    filled: '成交',
    canceled: '取消',
    cancelled: '取消',
    manually_processed: '人工处理',
  }
  return texts[status] || status
}
</script>
