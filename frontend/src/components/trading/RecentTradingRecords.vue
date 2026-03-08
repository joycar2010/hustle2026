<template>
  <div class="recent-records-container">
    <div class="header">
      <h3 class="title">最近交易记录</h3>
      <button @click="viewMore" class="view-more-btn">
        查看更多 →
      </button>
    </div>

    <div class="content">
      <div v-if="recentOrders.length === 0" class="empty-state">
        暂无记录
      </div>

      <div
        v-for="order in recentOrders"
        :key="order.id"
        class="order-item"
      >
        <div class="order-left">
          <span class="order-time">{{ formatTime(order.timestamp) }}</span>
          <span class="order-exchange">{{ order.exchange }}</span>
          <span :class="['order-side', order.side === 'buy' ? 'side-buy' : 'side-sell']">
            {{ order.side === 'buy' ? '买' : '卖' }}
          </span>
        </div>
        <div class="order-right">
          <span class="order-quantity">{{ order.quantity }}</span>
          <span :class="['order-status', getStatusClass(order.status)]">
            {{ getStatusText(order.status) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
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
      // New order, add to top and keep only 8
      recentOrders.value = [orderData, ...recentOrders.value].slice(0, 8)
    }
  }
}

async function fetchRecentOrders() {
  try {
    const response = await api.get('/api/v1/trading/orders', {
      params: { limit: 8, source: 'manual' }
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
    new: 'status-pending',
    pending: 'status-pending',
    filled: 'status-filled',
    canceled: 'status-canceled',
    cancelled: 'status-canceled',
    manually_processed: 'status-processed',
  }
  return classes[status] || 'status-default'
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

// Expose refresh method for parent component
defineExpose({
  fetchRecentOrders
})
</script>

<style scoped>
.recent-records-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: #1e2329;
  border-radius: 8px;
  overflow: hidden;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #2b3139;
  flex-shrink: 0;
}

.title {
  font-size: 14px;
  font-weight: bold;
  color: #ffffff;
  margin: 0;
}

.view-more-btn {
  font-size: 12px;
  color: #f0b90b;
  background: none;
  border: none;
  cursor: pointer;
  transition: color 0.2s;
  padding: 4px 8px;
}

.view-more-btn:hover {
  color: rgba(240, 185, 11, 0.8);
}

.content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}

.empty-state {
  text-align: center;
  padding: 32px 16px;
  font-size: 12px;
  color: #848e9c;
}

.order-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #252930;
  border-radius: 4px;
  padding: 10px 12px;
  font-size: 12px;
}

.order-left,
.order-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.order-time {
  color: #848e9c;
}

.order-exchange {
  color: #848e9c;
}

.order-side {
  font-weight: bold;
}

.side-buy {
  color: #0ecb81;
}

.side-sell {
  color: #f6465d;
}

.order-quantity {
  font-family: 'Courier New', monospace;
  color: #ffffff;
}

.order-status {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
}

.status-pending {
  color: #f0b90b;
  background-color: rgba(240, 185, 11, 0.1);
}

.status-filled {
  color: #0ecb81;
  background-color: rgba(14, 203, 129, 0.1);
}

.status-canceled {
  color: #f6465d;
  background-color: rgba(246, 70, 93, 0.1);
}

.status-processed {
  color: #3b82f6;
  background-color: rgba(59, 130, 246, 0.1);
}

.status-default {
  color: #848e9c;
  background-color: rgba(132, 142, 156, 0.1);
}

/* 移动端H5竖屏适配 */
@media (orientation: portrait), (max-width: 750px) {
  .recent-records-container {
    width: 100%;
    max-height: 400px;
    box-sizing: border-box;
  }

  .content {
    padding: 6px;
  }

  .order-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .order-left,
  .order-right {
    width: 100%;
    justify-content: space-between;
  }

  .view-more-btn {
    min-height: 44px; /* 移动端最小点击区域 */
    min-width: 44px;
  }
}

/* PC端保持原有布局 */
@media (min-width: 751px) and (orientation: landscape) {
  .recent-records-container {
    /* PC端样式保持不变 */
  }
}
</style>
