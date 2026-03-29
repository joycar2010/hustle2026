<template>
  <div class="p-2 border-t border-[#2b3139]">
  </div>
</template>

<script setup>
</script>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'
import SystemStatusModal from '@/components/SystemStatusModal.vue'
import api from '@/services/api'

const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const redisStatus = ref({ healthy: false, last_error: null })

// System Status Modal
const showSystemStatusModal = ref(false)
const systemStatusText = ref('系统正常运行')
const systemHealthy = ref(true)

onMounted(async () => {
  await fetchRedisStatus()

  // 监听 Redis 状态推送
  watch(() => marketStore.lastMessage, (message) => {
    if (message && message.type === 'redis_status') {
      redisStatus.value = message.data
    }
  })

  // 初始化系统状态并开始轮询
  updateSystemStatus()
  const statusInterval = setInterval(updateSystemStatus, 10000)
  onUnmounted(() => {
    clearInterval(statusInterval)
  })
})

// System Status Update - 整合所有系统状态和服务状态
async function updateSystemStatus() {
  try {
    const response = await api.get('/api/v1/system/status')
    const data = response.data

    const statuses = []

    // WebSocket状态
    if (marketStore.connected) {
      statuses.push('WS已连接')
    } else {
      statuses.push('WS未连接')
    }

    // 数据库连接池状态
    if (data.dbPool) {
      const usage = Math.round((data.dbPool.active / data.dbPool.max) * 100)
      statuses.push(`DB连接池:${usage}%`)
    }

    // 后端服务状态
    if (data.backend) {
      statuses.push('后端API正常')
    }

    // 持仓监控状态
    if (data.positionMonitor) {
      statuses.push('持仓监控运行中')
    }

    // 策略管理状态
    if (data.strategyManager) {
      statuses.push('策略管理运行中')
    }

    // Binance连接状态
    if (data.binance) {
      statuses.push('Binance已连接')
    }

    // Bybit连接状态
    if (data.bybit) {
      statuses.push('Bybit已连接')
    }

    // MT5连接状态
    if (data.mt5) {
      statuses.push('MT5已连接')
    }

    // 飞书服务状态
    if (notificationStore.feishuServiceStatus) {
      statuses.push('飞书服务正常')
    } else {
      statuses.push('飞书服务异常')
    }

    // Redis状态
    if (redisStatus.value.healthy) {
      statuses.push('Redis正常')
    } else {
      statuses.push('Redis异常')
    }

    // 系统运行时间
    if (data.uptime) {
      statuses.push(`运行:${data.uptime}`)
    }

    systemStatusText.value = statuses.join(' | ') || '系统正常运行'

    // 判断系统健康状态
    const dbUsage = data.dbPool ? (data.dbPool.active / data.dbPool.max) : 0
    systemHealthy.value = data.backend &&
                          marketStore.connected &&
                          dbUsage < 0.8 &&
                          notificationStore.feishuServiceStatus &&
                          redisStatus.value.healthy
  } catch (error) {
    systemStatusText.value = '无法获取系统状态'
    systemHealthy.value = false
  }
}

async function fetchRedisStatus() {
  try {
    const response = await api.get('/api/v1/system/redis/status')
    redisStatus.value = response.data
  } catch (error) {
    console.error('Failed to fetch Redis status:', error)
    redisStatus.value = { healthy: false, last_error: 'Failed to fetch status' }
  }
}
</script>

<style scoped>
/* Marquee Animation */
.marquee-container {
  overflow: hidden;
  position: relative;
}

.marquee-content {
  display: inline-block;
  animation: marquee 20s linear infinite;
  padding-left: 100%;
}

.marquee-content:hover {
  animation-play-state: paused;
}

@keyframes marquee {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(-100%);
  }
}
</style>