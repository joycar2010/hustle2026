<template>
  <div class="h-full flex flex-col p-3 min-h-0">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-bold">紧急手动交易</h3>
      <div class="flex items-center space-x-1">
        <div class="w-2 h-2 rounded-full bg-[#f6465d] animate-pulse"></div>
        <span class="text-xs text-[#f6465d] font-bold">紧急模式</span>
      </div>
    </div>
    <div class="flex-1 overflow-y-auto space-y-3 min-h-0">
      <!-- Exchange Selection -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">交易平台</label>
        <select
          v-model="exchange"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
        >
          <option value="binance">Binance (XAUUSDT)</option>
          <option value="bybit">Bybit MT5 (XAUUSD.s)</option>
        </select>
      </div>

      <!-- Quantity -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">数量</label>
        <input
          v-model.number="quantity"
          type="number"
          step="0.01"
          min="0.01"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
          placeholder="0.01"
        />
      </div>

      <!-- Action Buttons -->
      <div class="grid grid-cols-2 gap-2">
        <button
          @click="executeTrade('buy')"
          :disabled="loading"
          class="px-4 py-0.5 bg-[#0ecb81] text-white rounded text-sm font-bold hover:bg-[#0db774] transition-colors disabled:opacity-50"
        >
          买入开多
        </button>
        <button
          @click="executeTrade('sell')"
          :disabled="loading"
          class="px-4 py-0.5 bg-[#f6465d] text-white rounded text-sm font-bold hover:bg-[#e03d52] transition-colors disabled:opacity-50"
        >
          卖出开空
        </button>
      </div>

      <!-- Status message -->
      <div v-if="statusMsg" :class="['text-xs px-2 py-1 rounded', statusOk ? 'text-[#0ecb81] bg-[#0ecb81]/10' : 'text-[#f6465d] bg-[#f6465d]/10']">
        {{ statusMsg }}
      </div>

      <!-- Quick Actions -->
      <div class="pt-3 border-t border-[#2b3139]">
        <div class="grid grid-cols-2 gap-2">
          <button
            @click="closeAllPositions"
            :disabled="loading"
            class="px-4 py-1.5 bg-[#f6465d] text-white rounded text-sm font-bold hover:bg-[#e03d52] transition-colors disabled:opacity-50"
          >
            ⚠️ 平仓所有持仓
          </button>
          <button
            @click="cancelAllOrders"
            :disabled="loading"
            class="px-4 py-1.5 bg-[#252930] text-white rounded text-sm hover:bg-[#2b3139] transition-colors disabled:opacity-50"
          >
            取消所有挂单
          </button>
        </div>
      </div>

      <!-- Recent Trades -->
      <div class="pt-3 border-t border-[#2b3139]">
        <div class="text-xs text-gray-400 mb-2">最近交易记录</div>
        <div class="space-y-1">
          <div v-if="recentOrders.length === 0" class="text-xs text-gray-500 text-center py-2">
            暂无记录
          </div>
          <div
            v-for="order in recentOrders"
            :key="order.id"
            class="flex items-center justify-between text-xs bg-[#252930] rounded px-2 py-1.5"
          >
            <div class="flex items-center gap-2">
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
          class="w-full mt-2 text-xs text-[#f0b90b] hover:text-[#f0b90b]/80 transition-colors"
        >
          查看更多 →
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const router = useRouter()
const marketStore = useMarketStore()
const exchange = ref('binance')
const quantity = ref(0.01)
const loading = ref(false)
const statusMsg = ref('')
const statusOk = ref(true)
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
      // New order, add to top and keep only 4
      recentOrders.value = [orderData, ...recentOrders.value].slice(0, 4)
    }
  }
}

async function fetchRecentOrders() {
  try {
    const response = await api.get('/api/v1/trading/orders', {
      params: { limit: 4, source: 'manual' }
    })
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
  try {
    await api.post('/api/v1/trading/manual/order', {
      exchange: exchange.value,
      side,
      quantity: quantity.value,
    })
    showStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '下单失败', false)
  } finally {
    loading.value = false
  }
}

async function closeAllPositions() {
  if (!confirm('确定要平仓所有持仓吗？')) return
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/close-all')
    showStatus(`平仓指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '平仓失败', false)
  } finally {
    loading.value = false
  }
}

async function cancelAllOrders() {
  if (!confirm('确定要取消所有挂单吗？')) return
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/cancel-all')
    showStatus(`撤单指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '撤单失败', false)
  } finally {
    loading.value = false
  }
}

function viewMore() {
  router.push('/trading')
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
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
  }
  return texts[status] || status
}
</script>
