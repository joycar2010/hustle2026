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

      <!-- Health Status -->
      <div class="bg-[#252930] rounded p-3">
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-bold">健康状态</div>
          <div :class="['px-2 py-0.5 rounded text-xs font-bold', getHealthStatusClass(healthStatus.status)]">
            {{ getHealthStatusText(healthStatus.status) }}
          </div>
        </div>
        <div v-if="healthStatus.issues.length > 0" class="space-y-1">
          <div
            v-for="(issue, index) in healthStatus.issues"
            :key="index"
            class="flex items-start space-x-2 text-xs"
          >
            <span :class="issue.level === 'critical' ? 'text-[#f6465d]' : 'text-[#FF9500]'">⚠</span>
            <span class="text-gray-300">{{ issue.message }}</span>
          </div>
        </div>
        <div v-else class="text-xs text-gray-400">
          所有指标正常
        </div>
      </div>

      <!-- Performance Metrics -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs font-bold mb-3">性能指标</div>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <div class="text-xs text-gray-400">平均延迟</div>
            <div class="text-sm font-mono font-bold">{{ performanceMetrics.avgLatency.toFixed(0) }}ms</div>
          </div>
          <div>
            <div class="text-xs text-gray-400">最大延迟</div>
            <div class="text-sm font-mono font-bold">{{ performanceMetrics.maxLatency === 0 ? '-' : performanceMetrics.maxLatency.toFixed(0) + 'ms' }}</div>
          </div>
          <div>
            <div class="text-xs text-gray-400">重连次数</div>
            <div class="text-sm font-mono font-bold">{{ performanceMetrics.reconnectCount }}</div>
          </div>
          <div>
            <div class="text-xs text-gray-400">丢失消息</div>
            <div class="text-sm font-mono font-bold">{{ performanceMetrics.lostMessages }}</div>
          </div>
        </div>
      </div>

      <!-- Message Type Breakdown -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs font-bold mb-3">消息类型统计</div>
        <div class="space-y-2 max-h-48 overflow-y-auto">
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

      <!-- Message Rate Trend Chart -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs font-bold mb-3">消息速率趋势（最近5分钟）</div>
        <div class="h-48">
          <Line :data="messageRateChartData" :options="messageRateChartOptions" />
        </div>
      </div>

      <!-- Latency Trend Chart -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs font-bold mb-3">延迟趋势（最近5分钟）</div>
        <div class="h-48">
          <Line :data="latencyChartData" :options="latencyChartOptions" />
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
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

const marketStore = useMarketStore()

const stats = ref({
  totalMessages: 0,
  uptime: 0,
  messageRate: 0,
  messageTypes: {},
  lastMessageTime: null
})

const performanceMetrics = ref({
  avgLatency: 0,
  maxLatency: 0,
  minLatency: Infinity,
  lostMessages: 0,
  reconnectCount: 0,
  lastReconnectTime: null
})

const healthStatus = ref({
  status: 'healthy',  // healthy | warning | critical
  issues: []
})

const recentMessages = ref([])
const connected = computed(() => marketStore.connected)
const connectionStartTime = ref(null)
let uptimeInterval = null
let rateInterval = null
let healthCheckInterval = null
let messageCountLastSecond = 0
let lastSequenceNumber = 0

// Historical data for charts (last 5 minutes)
const messageRateHistory = ref([])
const latencyHistory = ref([])
const maxHistoryPoints = 300 // 5 minutes at 1 second intervals

// Chart data
const messageRateChartData = computed(() => ({
  labels: messageRateHistory.value.map(d => dayjs(d.time).format('HH:mm:ss')),
  datasets: [{
    label: '消息速率 (msg/s)',
    data: messageRateHistory.value.map(d => d.rate),
    borderColor: '#0ecb81',
    backgroundColor: 'rgba(14, 203, 129, 0.1)',
    fill: true,
    tension: 0.4,
    pointRadius: 0,
    borderWidth: 2
  }]
}))

const latencyChartData = computed(() => ({
  labels: latencyHistory.value.map(d => dayjs(d.time).format('HH:mm:ss')),
  datasets: [{
    label: '平均延迟 (ms)',
    data: latencyHistory.value.map(d => d.latency),
    borderColor: '#f0b90b',
    backgroundColor: 'rgba(240, 185, 11, 0.1)',
    fill: true,
    tension: 0.4,
    pointRadius: 0,
    borderWidth: 2
  }]
}))

// Chart options
const messageRateChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: false
    },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      titleColor: '#fff',
      bodyColor: '#fff',
      borderColor: '#0ecb81',
      borderWidth: 1
    }
  },
  scales: {
    x: {
      display: true,
      grid: {
        color: 'rgba(255, 255, 255, 0.05)'
      },
      ticks: {
        color: '#888',
        maxTicksLimit: 10
      }
    },
    y: {
      display: true,
      beginAtZero: true,
      grid: {
        color: 'rgba(255, 255, 255, 0.05)'
      },
      ticks: {
        color: '#888'
      }
    }
  },
  interaction: {
    mode: 'nearest',
    axis: 'x',
    intersect: false
  }
}

const latencyChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: false
    },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      titleColor: '#fff',
      bodyColor: '#fff',
      borderColor: '#f0b90b',
      borderWidth: 1
    }
  },
  scales: {
    x: {
      display: true,
      grid: {
        color: 'rgba(255, 255, 255, 0.05)'
      },
      ticks: {
        color: '#888',
        maxTicksLimit: 10
      }
    },
    y: {
      display: true,
      beginAtZero: true,
      grid: {
        color: 'rgba(255, 255, 255, 0.05)'
      },
      ticks: {
        color: '#888',
        callback: function(value) {
          return value + 'ms'
        }
      }
    }
  },
  interaction: {
    mode: 'nearest',
    axis: 'x',
    intersect: false
  }
}

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
    const now = Date.now()

    // Update message rate
    stats.value.messageRate = messageCountLastSecond

    // Record message rate history
    messageRateHistory.value.push({
      time: now,
      rate: messageCountLastSecond
    })

    // Record latency history
    latencyHistory.value.push({
      time: now,
      latency: performanceMetrics.value.avgLatency
    })

    // Keep only last 5 minutes of data
    const fiveMinutesAgo = now - 5 * 60 * 1000
    messageRateHistory.value = messageRateHistory.value.filter(d => d.time > fiveMinutesAgo)
    latencyHistory.value = latencyHistory.value.filter(d => d.time > fiveMinutesAgo)

    // Limit to maxHistoryPoints
    if (messageRateHistory.value.length > maxHistoryPoints) {
      messageRateHistory.value = messageRateHistory.value.slice(-maxHistoryPoints)
    }
    if (latencyHistory.value.length > maxHistoryPoints) {
      latencyHistory.value = latencyHistory.value.slice(-maxHistoryPoints)
    }

    messageCountLastSecond = 0
  }, 1000)

  // Health check every 5 seconds
  healthCheckInterval = setInterval(checkHealth, 5000)
})

onUnmounted(() => {
  if (uptimeInterval) clearInterval(uptimeInterval)
  if (rateInterval) clearInterval(rateInterval)
  if (healthCheckInterval) clearInterval(healthCheckInterval)
})

// Watch for connection state changes
watch(() => marketStore.connected, (isConnected, wasConnected) => {
  if (isConnected) {
    connectionStartTime.value = Date.now()
    stats.value.uptime = 0

    // Count reconnections (not initial connection)
    if (wasConnected === false && performanceMetrics.value.reconnectCount > 0) {
      performanceMetrics.value.reconnectCount++
      performanceMetrics.value.lastReconnectTime = Date.now()
    } else if (performanceMetrics.value.reconnectCount === 0) {
      // First connection
      performanceMetrics.value.reconnectCount = 0
    }
  } else {
    connectionStartTime.value = null
    if (wasConnected === true) {
      // Connection lost, increment reconnect counter
      performanceMetrics.value.reconnectCount++
    }
  }
})

// Watch for new messages
watch(() => marketStore.lastMessage, (message) => {
  if (!message) return

  // Update stats
  stats.value.totalMessages++
  messageCountLastSecond++
  stats.value.lastMessageTime = Date.now()

  // Calculate latency if message has timestamp
  if (message.timestamp) {
    const now = Date.now()
    const latency = now - message.timestamp

    // Update average latency
    if (stats.value.totalMessages === 1) {
      performanceMetrics.value.avgLatency = latency
    } else {
      performanceMetrics.value.avgLatency =
        (performanceMetrics.value.avgLatency * (stats.value.totalMessages - 1) + latency) /
        stats.value.totalMessages
    }

    // Update max/min latency
    performanceMetrics.value.maxLatency = Math.max(
      performanceMetrics.value.maxLatency,
      latency
    )
    performanceMetrics.value.minLatency = Math.min(
      performanceMetrics.value.minLatency,
      latency
    )
  }

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
    // 市场数据
    market_data: '市场数据',

    // 账户数据
    account_balance: '账户余额',
    risk_metrics: '风险指标',

    // 交易数据
    order_update: '订单更新',
    position_update: '持仓更新',

    // 策略执行
    strategy_status: '策略状态',
    strategy_trigger_progress: '策略触发进度',
    strategy_position_change: '策略持仓变化',
    strategy_execution_started: '策略执行开始',
    strategy_execution_completed: '策略执行完成',
    strategy_execution_error: '策略执行错误',
    strategy_order_executed: '策略订单执行',

    // 系统状态
    mt5_connection_status: 'MT5连接状态',
    system_notification: '系统通知',
    risk_alert: '风险警报',

    unknown: '未知'
  }
  return typeMap[type] || type
}

function getTypeColor(type) {
  const colorMap = {
    // 市场数据
    market_data: 'bg-[#0ecb81]',

    // 账户数据
    account_balance: 'bg-[#5AC8FA]',
    risk_metrics: 'bg-[#FF9500]',

    // 交易数据
    order_update: 'bg-[#f0b90b]',
    position_update: 'bg-[#AF52DE]',

    // 策略执行
    strategy_status: 'bg-[#00C98B]',
    strategy_trigger_progress: 'bg-[#34C759]',
    strategy_position_change: 'bg-[#30D158]',
    strategy_execution_started: 'bg-[#32ADE6]',
    strategy_execution_completed: 'bg-[#0ecb81]',
    strategy_execution_error: 'bg-[#f6465d]',
    strategy_order_executed: 'bg-[#FFD60A]',

    // 系统状态
    mt5_connection_status: 'bg-[#BF5AF2]',
    system_notification: 'bg-[#64D2FF]',
    risk_alert: 'bg-[#f6465d]',

    unknown: 'bg-gray-500'
  }
  return colorMap[type] || 'bg-gray-500'
}

function getTypeTextColor(type) {
  const colorMap = {
    // 市场数据
    market_data: 'text-[#0ecb81]',

    // 账户数据
    account_balance: 'text-[#5AC8FA]',
    risk_metrics: 'text-[#FF9500]',

    // 交易数据
    order_update: 'text-[#f0b90b]',
    position_update: 'text-[#AF52DE]',

    // 策略执行
    strategy_status: 'text-[#00C98B]',
    strategy_trigger_progress: 'text-[#34C759]',
    strategy_position_change: 'text-[#30D158]',
    strategy_execution_started: 'text-[#32ADE6]',
    strategy_execution_completed: 'text-[#0ecb81]',
    strategy_execution_error: 'text-[#f6465d]',
    strategy_order_executed: 'text-[#FFD60A]',

    // 系统状态
    mt5_connection_status: 'text-[#BF5AF2]',
    system_notification: 'text-[#64D2FF]',
    risk_alert: 'text-[#f6465d]',

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

function checkHealth() {
  const issues = []

  // Check connection status
  if (!marketStore.connected) {
    issues.push({ level: 'critical', message: 'WebSocket未连接' })
  }

  // Check message latency
  if (performanceMetrics.value.avgLatency > 1000) {
    issues.push({
      level: 'warning',
      message: `平均延迟过高: ${performanceMetrics.value.avgLatency.toFixed(0)}ms`
    })
  }

  // Check message rate (should receive at least 1 message per second for market_data)
  if (stats.value.messageRate === 0 && marketStore.connected && stats.value.uptime > 5000) {
    issues.push({ level: 'warning', message: '未收到消息（可能无数据推送）' })
  }

  // Check market_data frequency (should be ~1 per second)
  const marketDataCount = stats.value.messageTypes['market_data'] || 0
  const expectedCount = Math.floor(stats.value.uptime / 1000)
  if (expectedCount > 5 && marketDataCount < expectedCount * 0.7) {
    issues.push({
      level: 'warning',
      message: `market_data推送频率低于预期 (${marketDataCount}/${expectedCount})`
    })
  }

  // Check reconnection frequency
  if (performanceMetrics.value.reconnectCount > 5) {
    issues.push({
      level: 'warning',
      message: `频繁重连 (${performanceMetrics.value.reconnectCount}次)`
    })
  }

  healthStatus.value.issues = issues
  healthStatus.value.status = issues.some(i => i.level === 'critical') ? 'critical' :
                               issues.length > 0 ? 'warning' : 'healthy'
}

function getHealthStatusClass(status) {
  const classMap = {
    healthy: 'bg-[#0ecb81]/20 text-[#0ecb81]',
    warning: 'bg-[#FF9500]/20 text-[#FF9500]',
    critical: 'bg-[#f6465d]/20 text-[#f6465d]'
  }
  return classMap[status] || classMap.healthy
}

function getHealthStatusText(status) {
  const textMap = {
    healthy: '健康',
    warning: '警告',
    critical: '严重'
  }
  return textMap[status] || '未知'
}
</script>
