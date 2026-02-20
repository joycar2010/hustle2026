<template>
  <div class="h-full flex flex-col p-3">
    <h3 class="text-sm font-bold mb-3">挂单监控</h3>
    <div class="flex-1 overflow-y-auto">
      <table class="w-full text-xs">
        <thead class="sticky top-0 bg-[#1e2329]">
          <tr class="text-left text-gray-400 border-b border-[#2b3139]">
            <th class="p-2">时间</th>
            <th class="p-2">平台</th>
            <th class="p-2">方向</th>
            <th class="p-2">数量</th>
            <th class="p-2">价格</th>
            <th class="p-2">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="orders.length === 0">
            <td colspan="6" class="p-4 text-center text-gray-400">暂无挂单数据</td>
          </tr>
          <tr
            v-for="order in orders"
            :key="order.id"
            class="border-b border-[#2b3139] hover:bg-[#252930]"
          >
            <td class="p-2 text-gray-400">{{ formatTime(order.timestamp) }}</td>
            <td class="p-2">{{ order.exchange }}</td>
            <td class="p-2">
              <span :class="order.side === 'buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                {{ order.side === 'buy' ? '买入' : '卖出' }}
              </span>
            </td>
            <td class="p-2 font-mono">{{ order.quantity }}</td>
            <td class="p-2 font-mono">{{ order.price.toFixed(2) }} USDT</td>
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
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const orders = ref([])
let updateInterval = null

onMounted(() => {
  fetchOrders()
  updateInterval = setInterval(fetchOrders, 5000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchOrders() {
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(
      'http://localhost:8000/api/v1/trading/orders?limit=50',
      {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      }
    )

    if (!response.ok) {
      throw new Error('Failed to fetch orders')
    }

    const data = await response.json()
    orders.value = data
  } catch (error) {
    console.error('Failed to fetch orders:', error)
    // Keep existing orders on error
  }
}

function formatTime(timestamp) {
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
    pending: 'text-[#f0b90b]',
    filled: 'text-[#0ecb81]',
    cancelled: 'text-[#f6465d]',
  }
  return classes[status] || 'text-gray-400'
}

function getStatusText(status) {
  const texts = {
    pending: '挂单中',
    filled: '已成交',
    cancelled: '已取消',
  }
  return texts[status] || status
}
</script>