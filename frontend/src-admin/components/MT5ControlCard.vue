<template>
  <div class="bg-dark-100 rounded-2xl border p-4 space-y-3 transition-all"
    :class="getBorderColor()">

    <!-- 头部 -->
    <div class="flex items-start justify-between">
      <div class="flex-1 min-w-0">
        <div class="font-bold text-sm">{{ client.client_name }}</div>
        <div class="flex items-center gap-1.5 mt-1 flex-wrap">
          <span class="px-1.5 py-0.5 rounded text-xs" :class="getStatusClass()">
            {{ statusText }}
          </span>
          <span v-if="hasAlerts" class="px-1.5 py-0.5 rounded text-xs bg-[#f6465d]/20 text-[#f6465d]">
            告警
          </span>
        </div>
      </div>
    </div>

    <!-- 详情 -->
    <div class="text-xs space-y-1.5">
      <div class="flex justify-between">
        <span class="text-text-tertiary">MT5 登录:</span>
        <span class="font-mono">{{ client.mt5_login }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-text-tertiary">服务器:</span>
        <span class="font-mono">{{ client.mt5_server }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-text-tertiary">实例状态:</span>
        <span :class="isRunning ? 'text-[#0ecb81]' : 'text-text-tertiary'">
          {{ isRunning ? '运行中' : '已停止' }}
        </span>
      </div>
    </div>

    <!-- 健康状态 -->
    <div v-if="healthStatus && isRunning" class="bg-dark-200 rounded-lg p-2 text-xs space-y-1">
      <div class="flex justify-between">
        <span class="text-text-tertiary">CPU 使用率:</span>
        <span :class="healthStatus.cpu_high ? 'text-[#f6465d]' : ''">
          {{ healthStatus.details?.cpu_percent?.toFixed(1) || 0 }}%
        </span>
      </div>
      <div class="flex justify-between">
        <span class="text-text-tertiary">内存使用:</span>
        <span :class="healthStatus.memory_high ? 'text-[#f6465d]' : ''">
          {{ healthStatus.details?.memory_mb?.toFixed(0) || 0 }} MB
        </span>
      </div>
      <div v-if="healthStatus.is_frozen" class="text-[#f6465d] text-center mt-1">
        ⚠️ 检测到卡顿
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="flex gap-2">
      <button @click="handleStart"
        :disabled="isRunning || loading"
        class="flex-1 py-1.5 rounded-lg text-xs border transition-colors"
        :class="isRunning || loading ? 'bg-dark-200 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] border-[#0ecb81]/20'">
        {{ loading === 'start' ? '启动中...' : '启动' }}
      </button>
      <button @click="handleStop"
        :disabled="!isRunning || loading"
        class="flex-1 py-1.5 rounded-lg text-xs border transition-colors"
        :class="!isRunning || loading ? 'bg-dark-200 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] border-[#f6465d]/20'">
        {{ loading === 'stop' ? '停止中...' : '停止' }}
      </button>
      <button @click="handleRestart"
        :disabled="!isRunning || loading"
        class="flex-1 py-1.5 rounded-lg text-xs border transition-colors"
        :class="!isRunning || loading ? 'bg-dark-200 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] border-[#f0b90b]/20'">
        {{ loading === 'restart' ? '重启中...' : '重启' }}
      </button>
    </div>

    <!-- 最后更新时间 -->
    <div class="text-xs text-text-tertiary text-right">
      最后更新: {{ lastUpdateTime }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/services/api.js'

const props = defineProps({
  client: {
    type: Object,
    required: true
  }
})

const isRunning = ref(false)
const healthStatus = ref(null)
const loading = ref(null)
const lastUpdateTime = ref('--')

let refreshTimer = null

const statusText = computed(() => {
  if (loading.value) return '操作中...'
  return isRunning.value ? '运行中' : '已停止'
})

const hasAlerts = computed(() => {
  if (!healthStatus.value) return false
  return healthStatus.value.is_frozen ||
         healthStatus.value.cpu_high ||
         healthStatus.value.memory_high
})

const getBorderColor = () => {
  if (!isRunning.value) return 'border-border-primary'
  if (hasAlerts.value) return 'border-[#f6465d]'
  return 'border-[#0ecb81]'
}

const getStatusClass = () => {
  if (loading.value) return 'bg-dark-200 text-text-tertiary'
  if (!isRunning.value) return 'bg-dark-200 text-text-tertiary'
  if (hasAlerts.value) return 'bg-[#f6465d]/20 text-[#f6465d]'
  return 'bg-[#0ecb81]/20 text-[#0ecb81]'
}

const instanceName = computed(() => {
  if (props.client.agent_instance_name) {
    return props.client.agent_instance_name
  }
  return props.client.client_name
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
})

async function fetchStatus() {
  try {
    const response = await api.get(`/api/v1/mt5-agent/instances/${instanceName.value}`)
    isRunning.value = response.data.is_running
    healthStatus.value = response.data.health_status
    lastUpdateTime.value = new Date().toLocaleTimeString('zh-CN')
  } catch (error) {
    console.error('Failed to fetch status:', error)
    if (error.response?.status === 503) {
      isRunning.value = false
      healthStatus.value = null
    }
  }
}

function showToast(message, type = 'success') {
  const toast = document.createElement('div')
  toast.className = `fixed top-4 right-4 px-4 py-2 rounded-lg text-sm z-50 ${
    type === 'success' ? 'bg-[#0ecb81] text-white' : 'bg-[#f6465d] text-white'
  }`
  toast.textContent = message
  document.body.appendChild(toast)
  setTimeout(() => toast.remove(), 3000)
}

async function handleStart() {
  const confirmed = confirm(`确定要启动 ${props.client.client_name} 吗？`)
  if (!confirmed) return

  try {
    loading.value = 'start'
    const response = await api.post(
      `/api/v1/mt5-agent/instances/${instanceName.value}/start`,
      null,
      { params: { wait_seconds: 5 } }
    )

    if (response.data.success) {
      showToast('启动成功', 'success')
      setTimeout(fetchStatus, 3000)
    } else {
      showToast(`启动失败: ${response.data.message}`, 'error')
    }
  } catch (error) {
    showToast('启动失败，请检查 MT5 Agent 服务', 'error')
    console.error('Start failed:', error)
  } finally {
    loading.value = null
  }
}

async function handleStop() {
  const confirmed = confirm(`确定要停止 ${props.client.client_name} 吗？这将关闭 MT5 客户端。`)
  if (!confirmed) return

  try {
    loading.value = 'stop'
    const response = await api.post(
      `/api/v1/mt5-agent/instances/${instanceName.value}/stop`,
      null,
      { params: { force: true } }
    )

    if (response.data.success) {
      showToast('停止成功', 'success')
      await fetchStatus()
    } else {
      showToast(`停止失败: ${response.data.message}`, 'error')
    }
  } catch (error) {
    showToast('停止失败，请检查 MT5 Agent 服务', 'error')
    console.error('Stop failed:', error)
  } finally {
    loading.value = null
  }
}

async function handleRestart() {
  const confirmed = confirm(`确定要重启 ${props.client.client_name} 吗？这将关闭并重新启动 MT5 客户端。`)
  if (!confirmed) return

  try {
    loading.value = 'restart'
    const response = await api.post(
      `/api/v1/mt5-agent/instances/${instanceName.value}/restart`,
      null,
      { params: { wait_seconds: 5 } }
    )

    if (response.data.success) {
      showToast('重启成功', 'success')
      setTimeout(fetchStatus, 5000)
    } else {
      showToast(`重启失败: ${response.data.message}`, 'error')
    }
  } catch (error) {
    showToast('重启失败，请检查 MT5 Agent 服务', 'error')
    console.error('Restart failed:', error)
  } finally {
    loading.value = null
  }
}

onMounted(() => {
  fetchStatus()
  refreshTimer = setInterval(fetchStatus, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
/* 样式已内联到模板中，使用Tailwind CSS */
</style>
