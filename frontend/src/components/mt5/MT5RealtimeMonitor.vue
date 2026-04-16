<!-- MT5实时持仓监控组件示例 -->
<template>
  <div class="mt5-realtime-monitor">
    <div class="header">
      <h3>MT5实时持仓</h3>
      <span class="status" :class="{ connected: isConnected }">
        {{ isConnected ? '已连接' : '未连接' }}
      </span>
    </div>

    <div v-if="positions.length === 0" class="no-data">
      暂无持仓
    </div>

    <div v-else class="positions-list">
      <div
        v-for="pos in positions"
        :key="pos.ticket"
        class="position-card"
        :class="{ profit: pos.profit > 0, loss: pos.profit < 0 }"
      >
        <div class="position-header">
          <span class="symbol">{{ pos.symbol }}</span>
          <span class="type" :class="pos.type.toLowerCase()">
            {{ pos.type }}
          </span>
        </div>

        <div class="position-details">
          <div class="detail-row">
            <span class="label">手数:</span>
            <span class="value">{{ pos.volume }} Lot</span>
          </div>
          <div class="detail-row">
            <span class="label">开仓价:</span>
            <span class="value">{{ pos.price_open.toFixed(2) }}</span>
          </div>
          <div class="detail-row">
            <span class="label">当前价:</span>
            <span class="value">{{ pos.price_current.toFixed(2) }}</span>
          </div>
          <div class="detail-row">
            <span class="label">盈亏:</span>
            <span class="value profit-loss" :class="{ profit: pos.profit > 0, loss: pos.profit < 0 }">
              {{ pos.profit > 0 ? '+' : '' }}{{ pos.profit.toFixed(2) }} USDT
            </span>
          </div>
          <div class="detail-row">
            <span class="label">掉期费:</span>
            <span class="value">{{ pos.swap.toFixed(2) }} USDT</span>
          </div>
        </div>

        <div class="position-footer">
          <span class="account">{{ pos.account_name }}</span>
          <span class="update-time">{{ formatTime(lastUpdateTime) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
const positions = ref([])
const lastUpdateTime = ref(null)
const isConnected = ref(false)

let unwatchMessage = null

onMounted(() => {
  // 连接WebSocket
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // 监听WebSocket连接状态
  watch(() => marketStore.connected, (connected) => {
    isConnected.value = connected
  }, { immediate: true })

  // 监听MT5持仓更新消息
  unwatchMessage = watch(() => marketStore.lastMessage, (message) => {
    if (message && message.type === 'mt5_position_update') {
      // 更新持仓数据
      positions.value = message.data.positions || []
      lastUpdateTime.value = message.data.timestamp

      console.log('MT5持仓更新:', {
        count: positions.value.length,
        timestamp: lastUpdateTime.value
      })
    }
  })
})

onUnmounted(() => {
  if (unwatchMessage) {
    unwatchMessage()
  }
})

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}
</script>

<style scoped>
.mt5-realtime-monitor {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e0e0e0;
}

.header h3 {
  margin: 0;
  font-size: 18px;
  color: #333;
}

.status {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  background: #f5f5f5;
  color: #999;
}

.status.connected {
  background: #e8f5e9;
  color: #4caf50;
}

.no-data {
  text-align: center;
  padding: 40px;
  color: #999;
}

.positions-list {
  display: grid;
  gap: 16px;
}

.position-card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  transition: all 0.3s;
}

.position-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.position-card.profit {
  border-left: 4px solid #4caf50;
}

.position-card.loss {
  border-left: 4px solid #f44336;
}

.position-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.symbol {
  font-size: 16px;
  font-weight: bold;
  color: #333;
}

.type {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: bold;
}

.type.buy {
  background: #e3f2fd;
  color: #2196f3;
}

.type.sell {
  background: #fce4ec;
  color: #e91e63;
}

.position-details {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
}

.label {
  color: #666;
}

.value {
  color: #333;
  font-weight: 500;
}

.profit-loss.profit {
  color: #4caf50;
}

.profit-loss.loss {
  color: #f44336;
}

.position-footer {
  display: flex;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
  font-size: 12px;
  color: #999;
}

.account {
  font-weight: 500;
}

.update-time {
  font-style: italic;
}
</style>
