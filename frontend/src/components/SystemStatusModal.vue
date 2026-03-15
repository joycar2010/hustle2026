<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4"
        @click.self="$emit('close')"
      >
        <div class="bg-dark-100 rounded-lg shadow-xl border border-border-primary w-full max-w-2xl max-h-[90vh] overflow-y-auto">
          <!-- Header -->
          <div class="flex items-center justify-between p-6 border-b border-border-secondary">
            <h2 class="text-xl font-semibold">系统状态监控</h2>
            <button
              @click="$emit('close')"
              class="text-text-tertiary hover:text-text-primary transition-colors"
            >
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Content -->
          <div class="p-6 space-y-6">
            <!-- Loading State -->
            <div v-if="loading" class="flex items-center justify-center py-12">
              <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
            </div>

            <!-- Status Grid -->
            <div v-else class="space-y-4">
              <!-- WebSocket Status -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between">
                  <div class="flex items-center space-x-3">
                    <div :class="['w-3 h-3 rounded-full', statusData.websocket ? 'bg-success animate-pulse' : 'bg-danger']"></div>
                    <span class="font-medium">WebSocket连接</span>
                  </div>
                  <span :class="['text-sm', statusData.websocket ? 'text-success' : 'text-danger']">
                    {{ statusData.websocket ? '已连接' : '未连接' }}
                  </span>
                </div>
              </div>

              <!-- Database Pool Status -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between mb-3">
                  <div class="flex items-center space-x-3">
                    <div :class="['w-3 h-3 rounded-full', getDbPoolStatus()]"></div>
                    <span class="font-medium">数据库连接池</span>
                  </div>
                  <span :class="['text-sm', getDbPoolStatusColor()]">
                    {{ getDbPoolUsageText() }}
                  </span>
                </div>
                <div v-if="statusData.dbPool" class="space-y-2">
                  <div class="flex justify-between text-sm">
                    <span class="text-text-tertiary">活跃连接</span>
                    <span>{{ statusData.dbPool.active }}</span>
                  </div>
                  <div class="flex justify-between text-sm">
                    <span class="text-text-tertiary">空闲连接</span>
                    <span>{{ statusData.dbPool.idle }}</span>
                  </div>
                  <div class="flex justify-between text-sm">
                    <span class="text-text-tertiary">最大连接数</span>
                    <span>{{ statusData.dbPool.max }}</span>
                  </div>
                  <!-- Progress Bar -->
                  <div class="mt-3">
                    <div class="w-full bg-dark-300 rounded-full h-2">
                      <div
                        :class="['h-2 rounded-full transition-all', getDbPoolBarColor()]"
                        :style="{ width: getDbPoolUsagePercent() + '%' }"
                      ></div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Backend Services -->
              <div class="bg-dark-200 rounded-lg p-4">
                <h3 class="font-medium mb-3">后端服务</h3>
                <div class="space-y-2">
                  <div class="flex items-center justify-between">
                    <span class="text-sm text-text-tertiary">API服务</span>
                    <div class="flex items-center space-x-2">
                      <div :class="['w-2 h-2 rounded-full', statusData.backend ? 'bg-success' : 'bg-danger']"></div>
                      <span :class="['text-sm', statusData.backend ? 'text-success' : 'text-danger']">
                        {{ statusData.backend ? '运行中' : '停止' }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="text-sm text-text-tertiary">持仓监控</span>
                    <div class="flex items-center space-x-2">
                      <div :class="['w-2 h-2 rounded-full', statusData.positionMonitor ? 'bg-success' : 'bg-danger']"></div>
                      <span :class="['text-sm', statusData.positionMonitor ? 'text-success' : 'text-danger']">
                        {{ statusData.positionMonitor ? '运行中' : '停止' }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="text-sm text-text-tertiary">策略管理</span>
                    <div class="flex items-center space-x-2">
                      <div :class="['w-2 h-2 rounded-full', statusData.strategyManager ? 'bg-success' : 'bg-danger']"></div>
                      <span :class="['text-sm', statusData.strategyManager ? 'text-success' : 'text-danger']">
                        {{ statusData.strategyManager ? '运行中' : '停止' }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Exchange Connections -->
              <div class="bg-dark-200 rounded-lg p-4">
                <h3 class="font-medium mb-3">交易所连接</h3>
                <div class="space-y-2">
                  <div class="flex items-center justify-between">
                    <span class="text-sm text-text-tertiary">Binance</span>
                    <div class="flex items-center space-x-2">
                      <div :class="['w-2 h-2 rounded-full', statusData.binance ? 'bg-success' : 'bg-danger']"></div>
                      <span :class="['text-sm', statusData.binance ? 'text-success' : 'text-danger']">
                        {{ statusData.binance ? '已连接' : '未连接' }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="text-sm text-text-tertiary">Bybit</span>
                    <div class="flex items-center space-x-2">
                      <div :class="['w-2 h-2 rounded-full', statusData.bybit ? 'bg-success' : 'bg-danger']"></div>
                      <span :class="['text-sm', statusData.bybit ? 'text-success' : 'text-danger']">
                        {{ statusData.bybit ? '已连接' : '未连接' }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center justify-between">
                    <span class="text-sm text-text-tertiary">MT5</span>
                    <div class="flex items-center space-x-2">
                      <div :class="['w-2 h-2 rounded-full', statusData.mt5 ? 'bg-success' : 'bg-danger']"></div>
                      <span :class="['text-sm', statusData.mt5 ? 'text-success' : 'text-danger']">
                        {{ statusData.mt5 ? '已连接' : '未连接' }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- System Info -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between">
                  <span class="text-sm text-text-tertiary">系统运行时间</span>
                  <span class="text-sm">{{ statusData.uptime || 'N/A' }}</span>
                </div>
                <div class="flex items-center justify-between mt-2">
                  <span class="text-sm text-text-tertiary">最后更新</span>
                  <span class="text-sm">{{ formatTimestamp(statusData.timestamp) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between p-6 border-t border-border-secondary">
            <span class="text-sm text-text-tertiary">自动刷新: 5秒</span>
            <button
              @click="fetchStatus"
              class="px-4 py-2 bg-primary hover:bg-primary-hover rounded-lg transition-colors"
            >
              立即刷新
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'
import api from '@/services/api'

const props = defineProps({
  isOpen: {
    type: Boolean,
    required: true
  }
})

const emit = defineEmits(['close'])

const loading = ref(false)
const statusData = ref({
  backend: false,
  positionMonitor: false,
  strategyManager: false,
  binance: false,
  bybit: false,
  mt5: false,
  websocket: false,
  dbPool: null,
  uptime: '',
  timestamp: ''
})

let refreshInterval = null

async function fetchStatus() {
  try {
    loading.value = true
    const response = await api.get('/api/v1/system/status')
    statusData.value = response.data
  } catch (error) {
    console.error('Failed to fetch system status:', error)
  } finally {
    loading.value = false
  }
}

function getDbPoolUsagePercent() {
  if (!statusData.value.dbPool) return 0
  return Math.round((statusData.value.dbPool.active / statusData.value.dbPool.max) * 100)
}

function getDbPoolUsageText() {
  if (!statusData.value.dbPool) return 'N/A'
  const percent = getDbPoolUsagePercent()
  return `${percent}% (${statusData.value.dbPool.active}/${statusData.value.dbPool.max})`
}

function getDbPoolStatus() {
  const percent = getDbPoolUsagePercent()
  if (percent >= 80) return 'bg-danger animate-pulse'
  if (percent >= 60) return 'bg-warning animate-pulse'
  return 'bg-success'
}

function getDbPoolStatusColor() {
  const percent = getDbPoolUsagePercent()
  if (percent >= 80) return 'text-danger'
  if (percent >= 60) return 'text-warning'
  return 'text-success'
}

function getDbPoolBarColor() {
  const percent = getDbPoolUsagePercent()
  if (percent >= 80) return 'bg-danger'
  if (percent >= 60) return 'bg-warning'
  return 'bg-success'
}

function formatTimestamp(timestamp) {
  if (!timestamp) return 'N/A'
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    fetchStatus()
    refreshInterval = setInterval(fetchStatus, 5000)
  } else {
    if (refreshInterval) {
      clearInterval(refreshInterval)
      refreshInterval = null
    }
  }
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .bg-dark-100,
.modal-leave-active .bg-dark-100 {
  transition: transform 0.3s ease;
}

.modal-enter-from .bg-dark-100,
.modal-leave-to .bg-dark-100 {
  transform: scale(0.95);
}
</style>
