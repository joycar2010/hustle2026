<template>
  <div class="p-2 space-y-1.5 border-t border-[#2b3139]">
    <h3 class="text-xs font-bold mb-2 text-gray-400">系统状态</h3>

    <button
      v-for="item in navItems"
      :key="item.id"
      @click="handleNavClick(item.id)"
      :class="[
        'w-full px-2 rounded text-left transition-all flex items-center justify-between',
        'h-[32px]',
        activeNav === item.id
          ? 'bg-[#f0b90b]/20 text-[#f0b90b] border border-[#f0b90b]'
          : 'bg-[#252930] hover:bg-[#2b3139] text-gray-300'
      ]"
    >
      <div class="flex items-center space-x-1.5 flex-1 min-w-0">
        <component :is="iconComponents[item.icon]" class="w-4 h-4 flex-shrink-0" />
        <span class="text-xs font-medium truncate">{{ item.label }}</span>
      </div>
      <div v-if="item.badge" :class="['text-xs px-1.5 py-0.5 rounded flex-shrink-0 ml-1.5', item.badgeClass]">
        {{ item.badge }}
      </div>
    </button>

    <!-- System Alerts -->
    <div class="mt-2 bg-[#252930] rounded-lg border border-[#2b3139] p-2">
      <div class="text-xs font-semibold mb-2 text-[#f0b90b]">系统提醒</div>
      <div class="space-y-1.5">
        <div v-for="alert in systemAlerts" :key="alert.id" class="flex items-start space-x-1.5 text-xs">
          <div class="w-1.5 h-1.5 rounded-full mt-0.5 flex-shrink-0" :class="getAlertColor(alert.type)"></div>
          <div class="flex-1">
            <div class="text-gray-300">{{ alert.message }}</div>
            <div v-if="alert.value" class="text-gray-500 mt-0.5">{{ alert.value }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'
import api from '@/services/api'

const router = useRouter()
const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const activeNav = ref('strategy')
const redisStatus = ref({ healthy: false, last_error: null })
let redisCheckInterval = null

// Combine notification store alerts with Redis status
const systemAlerts = computed(() => {
  const alerts = [...notificationStore.systemAlerts]

  // Add Redis status alert
  if (redisStatus.value.healthy) {
    alerts.push({
      id: 4,
      type: 'success',
      message: 'Redis服务',
      value: '运行正常'
    })
  } else {
    alerts.push({
      id: 4,
      type: 'danger',
      message: 'Redis服务异常',
      value: redisStatus.value.last_error || '连接失败'
    })
  }

  return alerts
})

onMounted(async () => {
  await fetchSystemAlerts()
  await fetchRedisStatus()

  // Keep Redis status polling (30s) - no WebSocket alternative yet
  redisCheckInterval = setInterval(fetchRedisStatus, 30000)

  // Watch for account_balance WebSocket messages (backend broadcasts every 10s)
  watch(() => marketStore.lastMessage, (message) => {
    if (message && message.type === 'account_balance') {
      notificationStore.updateSystemAlerts(message.data)
    }
  })
})

onUnmounted(() => {
  if (redisCheckInterval) {
    clearInterval(redisCheckInterval)
  }
})

async function fetchSystemAlerts() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data
    notificationStore.updateSystemAlerts(data)
  } catch (error) {
    console.error('Failed to fetch system alerts:', error)
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

function getAlertColor(type) {
  const colors = {
    success: 'bg-[#0ecb81]',
    warning: 'bg-[#f0b90b]',
    danger: 'bg-[#f6465d]',
    info: 'bg-[#2196F3]'
  }
  return colors[type] || 'bg-gray-500'
}

// Icon components
const DashboardIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" /></svg>`
}

const HistoryIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`
}

const StrategyIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>`
}

const SpreadIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>`
}

const AccountIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" /></svg>`
}

const RiskIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>`
}

const SystemIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>`
}

// Icon mapping object
const iconComponents = {
  DashboardIcon,
  HistoryIcon,
  StrategyIcon,
  SpreadIcon,
  AccountIcon,
  RiskIcon,
  SystemIcon
}

const navItems = [
  {
    id: 'strategy',
    label: '策略控制',
    icon: 'StrategyIcon',
    route: '/strategies',
    badge: '运行中',
    badgeClass: 'bg-[#0ecb81] text-white',
  },
  {
    id: 'monitor',
    label: '策略监控',
    icon: 'DashboardIcon',
    externalUrl: '/feishu-widget/index.html',
    badge: '实时',
    badgeClass: 'bg-[#2196F3] text-white',
  },
  {
    id: 'risk',
    label: '风控提醒',
    icon: 'RiskIcon',
    route: '/risk',
    badge: '正常',
    badgeClass: 'bg-[#0ecb81] text-white',
  },
]

function handleNavClick(id) {
  activeNav.value = id
  const item = navItems.find(i => i.id === id)
  if (item?.externalUrl) {
    // Open external URL in new tab
    window.open(item.externalUrl, '_blank')
  } else if (item?.route) {
    router.push(item.route)
  }
}
</script>