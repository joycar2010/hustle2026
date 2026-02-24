<template>
  <div class="card-elevated">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-lg font-bold">WebSocket 连接监控</h3>
      <div class="flex items-center space-x-2">
        <div
          :class="[
            'w-3 h-3 rounded-full',
            connected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]'
          ]"
        ></div>
        <span :class="['text-sm font-bold', connected ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
          {{ connected ? '已连接' : '未连接' }}
        </span>
      </div>
    </div>

    <div class="space-y-4">
      <!-- Connection Stats -->
      <div class="grid grid-cols-3 gap-3">
        <div class="bg-[#252930] rounded p-3">
          <div class="text-xs text-gray-400 mb-1">消息总数</div>
          <div class="text-xl font-mono font-bold">{{ stats.totalMessages }}</div>
        </div>
        <div class="bg-[#252930] rounded p-3">
          <div class="text-xs text-gray-400 mb-1">连接时长</div>
          <div class="text-xl font-mono font-bold">{{ formatUptime(stats.uptime) }}</div>
        </div>
        <div class="bg-[#252930] rounded p-3">
          <div class="text-xs text-gray-400 mb-1">消息速率</div>
          <div class="text-xl font-mono font-bold">{{ stats.messageRate }}/s</div>
        </div>
      </div>

      <!-- Message Type Breakdown -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs font-bold mb-3">消息类型统计</div>
        <div class="space-y-2">
          <div
            v-for="(count, type) in stats.messageTypes"
            :key="type"
            class="flex items-center justify-between text-sm"
          >
            <div class="flex items-center space-x-2">
              <div :class="['w-2 h-2 rounded-full', getTypeColor(type)]"></div>
              <span class="text-gray-300">{{ formatMessageType(type) }}</span>
            </div>
            <span class="font-mono text-gray-400">{{ count }}</span>
          </div>
        </div>
      </div>

      <!-- Recent Messages -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs font-bold mb-3">最近消息</div>
        <div class="space-y-1 max-h-48 overflow-y-auto">
          <div
            v-for="msg in recentMessages"
            :key="msg.id"
            class="flex items-center justify-between text-xs bg-[#1a1d21] rounded px-2 py-1.5"
          >
            <div class="flex items-center space-x-2">
              <span class="text-gray-500">{{ formatTime(msg.timestamp) }}</span>
              <span :class="['font-bold', getTypeTextColor(msg.type)]">
                {{ formatMessageType(msg.type) }}
              </span>
            </div>
            <span class="text-gray-400 font-mono text-xs">
              {{ msg.size }} bytes
            </span>
          </div>
        </div>
      </div>

      <!-- Connection Controls -->
      <div class="flex space-x-2">
        <button
          v-if="!connected"
          @click="reconnect"
          class="flex-1 px-4 py-2 bg-[#0ecb81] text-white rounded font-bold hover:bg-[#0db774] transition-colors"
        >
          重新连接
        </button>
        <button
          v-else
          @click="disconnect"
          class="flex-1 px-4 py-2 bg-[#f6465d] text-white rounded font-bold hover:bg-[#e03d52] transition-colors"
        >
          断开连接
        </button>
        <button
          @click="clearStats"
          class="px-4 py-2 bg-[#252930] text-white rounded hover:bg-[#2b3139] transition-colors"
        >
          清除统计
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import dayjs from 'dayjs'

const marketStore = useMarketStore()

const stats = ref({
  totalMessages: 0,
  uptime: 0,
  messageRate: 0,
  messageTypes: {},
  lastMessageTime: null
})

const recentMessages = ref([])
const connected = computed(() => marketStore.connected)
const connectionStartTime = ref(null)
let uptimeInterval = null
let rateInterval = null
let messageCountLastSecond = 0

onMounted(() => {
  if (marketStore.connected) {
    connectionStartTime.value = Date.now()
  }

  // Update uptime every second
  uptimeInterval = setInterval(() => {
    if (connectionStartTime.value) {
      stats.value.uptime = Date.now() - connectionStartTime.value
    }
  }, 1000)

  // Calculate message rate every second
  rateInterval = setInterval(() => {
    stats.value.messageRate = messageCountLastSecond
    messageCountLastSecond = 0
  }, 1000)
})

onUnmounted(() => {
  if (uptimeInterval) clearInterval(uptimeInterval)
  if (rateInterval) clearInterval(rateInterval)
})

// Watch for connection state changes
watch(() => marketStore.connected, (isConnected) => {
  if (isConnected) {
    connectionStartTime.value = Date.now()
    stats.value.uptime = 0
  } else {
    connectionStartTime.value = null
  }
})

// Watch for new messages
watch(() => marketStore.lastMessage, (message) => {
  if (!message) return

  // Update stats
  stats.value.totalMessages++
  messageCountLastSecond++
  stats.value.lastMessageTime = Date.now()

  // Update message type count
  const type = message.type || 'unknown'
  stats.value.messageTypes[type] = (stats.value.messageTypes[type] || 0) + 1

  // Add to recent messages
  const messageSize = JSON.stringify(message).length
  recentMessages.value = [
    {
      id: Date.now() + Math.random(),
      type: type,
      timestamp: Date.now(),
      size: messageSize
    },
    ...recentMessages.value
  ].slice(0, 10) // Keep only last 10 messages
})

function formatUptime(ms) {
  if (!ms) return '0s'
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  } else {
    return `${seconds}s`
  }
}

function formatTime(timestamp) {
  return dayjs(timestamp).format('HH:mm:ss')
}

function formatMessageType(type) {
  const typeMap = {
    market_data: '市场数据',
    order_update: '订单更新',
    risk_alert: '风险警报',
    risk_metrics: '风险指标',
    strategy_status: '策略状态',
    account_balance: '账户余额',
    position_update: '持仓更新',
    unknown: '未知'
  }
  return typeMap[type] || type
}

function getTypeColor(type) {
  const colorMap = {
    market_data: 'bg-[#0ecb81]',
    order_update: 'bg-[#f0b90b]',
    risk_alert: 'bg-[#f6465d]',
    risk_metrics: 'bg-[#FF9500]',
    strategy_status: 'bg-[#00C98B]',
    account_balance: 'bg-[#5AC8FA]',
    position_update: 'bg-[#AF52DE]',
    unknown: 'bg-gray-500'
  }
  return colorMap[type] || 'bg-gray-500'
}

function getTypeTextColor(type) {
  const colorMap = {
    market_data: 'text-[#0ecb81]',
    order_update: 'text-[#f0b90b]',
    risk_alert: 'text-[#f6465d]',
    risk_metrics: 'text-[#FF9500]',
    strategy_status: 'text-[#00C98B]',
    account_balance: 'text-[#5AC8FA]',
    position_update: 'text-[#AF52DE]',
    unknown: 'text-gray-500'
  }
  return colorMap[type] || 'text-gray-500'
}

function reconnect() {
  marketStore.connect()
}

function disconnect() {
  marketStore.disconnect()
}

function clearStats() {
  stats.value = {
    totalMessages: 0,
    uptime: stats.value.uptime,
    messageRate: 0,
    messageTypes: {},
    lastMessageTime: null
  }
  recentMessages.value = []
  messageCountLastSecond = 0
}
</script>
