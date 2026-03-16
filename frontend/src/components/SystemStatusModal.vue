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

              <!-- Infrastructure Services -->
              <div class="bg-dark-200 rounded-lg p-4">
                <h3 class="font-medium mb-3">基础设施服务</h3>
                <div class="space-y-3">
                  <!-- Redis -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">Redis</span>
                      <div class="flex items-center space-x-2">
                        <div :class="['w-2 h-2 rounded-full', systemMonitor.redis?.connected ? 'bg-success' : 'bg-danger']"></div>
                        <span :class="['text-sm', systemMonitor.redis?.connected ? 'text-success' : 'text-danger']">
                          {{ systemMonitor.redis?.connected ? '已连接' : '未连接' }}
                        </span>
                      </div>
                    </div>
                    <div v-if="systemMonitor.redis?.connected" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between">
                        <span>版本</span>
                        <span>{{ systemMonitor.redis.version }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>内存使用</span>
                        <span>{{ systemMonitor.redis.used_memory_human }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>连接数</span>
                        <span>{{ systemMonitor.redis.connected_clients }}</span>
                      </div>
                    </div>
                    <div v-else-if="systemMonitor.redis?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.redis.error }}
                    </div>
                  </div>

                  <!-- Feishu -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">飞书通知</span>
                      <div class="flex items-center space-x-2">
                        <div :class="['w-2 h-2 rounded-full', getFeishuStatusClass()]"></div>
                        <span :class="['text-sm', getFeishuStatusTextClass()]">
                          {{ getFeishuStatusText() }}
                        </span>
                      </div>
                    </div>
                    <div v-if="systemMonitor.feishu?.configured" class="text-xs text-text-tertiary">
                      Webhook: {{ systemMonitor.feishu.webhook_url }}
                    </div>
                    <div v-else-if="systemMonitor.feishu?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.feishu.error }}
                    </div>
                  </div>

                  <!-- SSL Certificate -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">SSL证书</span>
                      <div class="flex items-center space-x-2">
                        <div :class="['w-2 h-2 rounded-full', getSSLStatusClass()]"></div>
                        <span :class="['text-sm', getSSLStatusTextClass()]">
                          {{ getSSLStatusText() }}
                        </span>
                      </div>
                    </div>
                    <div v-if="systemMonitor.ssl_certificate?.exists" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between">
                        <span>剩余天数</span>
                        <span :class="getSSLDaysClass()">{{ systemMonitor.ssl_certificate.days_remaining }} 天</span>
                      </div>
                      <div class="flex justify-between">
                        <span>过期时间</span>
                        <span>{{ formatDate(systemMonitor.ssl_certificate.expires_at) }}</span>
                      </div>
                      <div v-if="systemMonitor.ssl_certificate.domain_names?.length" class="flex justify-between">
                        <span>域名</span>
                        <span>{{ systemMonitor.ssl_certificate.domain_names[0] }}</span>
                      </div>
                    </div>
                    <div v-else-if="systemMonitor.ssl_certificate?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.ssl_certificate.error }}
                    </div>
                  </div>

                  <!-- Proxy Health -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">IP代理池</span>
                      <div class="flex items-center space-x-2">
                        <div :class="['w-2 h-2 rounded-full', getProxyStatusClass()]"></div>
                        <span :class="['text-sm', getProxyStatusTextClass()]">
                          {{ getProxyStatusText() }}
                        </span>
                      </div>
                    </div>
                    <div v-if="systemMonitor.proxies" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between">
                        <span>总代理数</span>
                        <span>{{ systemMonitor.proxies.total }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>活跃代理</span>
                        <span class="text-success">{{ systemMonitor.proxies.active }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>失败代理</span>
                        <span :class="systemMonitor.proxies.failed > 0 ? 'text-danger' : ''">{{ systemMonitor.proxies.failed }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>已过期</span>
                        <span :class="systemMonitor.proxies.expired > 0 ? 'text-warning' : ''">{{ systemMonitor.proxies.expired }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>平均健康度</span>
                        <span :class="getProxyHealthClass()">{{ systemMonitor.proxies.avgHealth }}/100</span>
                      </div>
                      <!-- Progress Bar -->
                      <div class="mt-2">
                        <div class="w-full bg-dark-400 rounded-full h-2">
                          <div
                            :class="['h-2 rounded-full transition-all', getProxyHealthBarColor()]"
                            :style="{ width: systemMonitor.proxies.avgHealth + '%' }"
                          ></div>
                        </div>
                      </div>
                    </div>
                    <div v-else class="text-xs text-text-tertiary mt-1">
                      暂无代理数据
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
            <span class="text-sm text-text-tertiary">自动刷新: 30秒</span>
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

const systemMonitor = ref({
  redis: null,
  feishu: null,
  ssl_certificate: null,
  proxies: null
})

let refreshInterval = null

async function fetchStatus() {
  try {
    loading.value = true
    const response = await api.get('/api/v1/system/status')
    statusData.value = response.data

    // Fetch system monitor data
    const monitorResponse = await api.get('/api/v1/monitor/status')
    systemMonitor.value = monitorResponse.data

    // Fetch proxy health data
    try {
      const proxyResponse = await api.get('/api/v1/proxies')
      const proxies = proxyResponse.data
      const total = proxies.length
      const active = proxies.filter(p => p.status === 'active').length
      const failed = proxies.filter(p => p.status === 'failed').length
      const expired = proxies.filter(p => p.status === 'expired').length
      const avgHealth = total > 0 ? Math.round(proxies.reduce((sum, p) => sum + (p.health_score || 0), 0) / total) : 100

      systemMonitor.value.proxies = {
        total,
        active,
        failed,
        expired,
        avgHealth,
        list: proxies.slice(0, 5) // 只显示前5个
      }
    } catch (error) {
      console.error('Failed to fetch proxy data:', error)
      systemMonitor.value.proxies = null
    }
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

function formatDate(dateStr) {
  if (!dateStr) return 'N/A'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// Feishu status helpers
function getFeishuStatusClass() {
  if (!systemMonitor.value.feishu) return 'bg-gray-500'
  if (systemMonitor.value.feishu.status === 'healthy') return 'bg-success'
  if (systemMonitor.value.feishu.status === 'not_configured') return 'bg-warning'
  return 'bg-danger'
}

function getFeishuStatusTextClass() {
  if (!systemMonitor.value.feishu) return 'text-gray-500'
  if (systemMonitor.value.feishu.status === 'healthy') return 'text-success'
  if (systemMonitor.value.feishu.status === 'not_configured') return 'text-warning'
  return 'text-danger'
}

function getFeishuStatusText() {
  if (!systemMonitor.value.feishu) return '未知'
  if (systemMonitor.value.feishu.status === 'healthy') return '正常'
  if (systemMonitor.value.feishu.status === 'not_configured') return '未配置'
  return '异常'
}

// SSL status helpers
function getSSLStatusClass() {
  if (!systemMonitor.value.ssl_certificate) return 'bg-gray-500'
  const status = systemMonitor.value.ssl_certificate.status
  if (status === 'healthy') return 'bg-success'
  if (status === 'warning') return 'bg-warning'
  if (status === 'critical' || status === 'expired') return 'bg-danger'
  return 'bg-gray-500'
}

function getSSLStatusTextClass() {
  if (!systemMonitor.value.ssl_certificate) return 'text-gray-500'
  const status = systemMonitor.value.ssl_certificate.status
  if (status === 'healthy') return 'text-success'
  if (status === 'warning') return 'text-warning'
  if (status === 'critical' || status === 'expired') return 'text-danger'
  return 'text-gray-500'
}

function getSSLStatusText() {
  if (!systemMonitor.value.ssl_certificate) return '未知'
  if (!systemMonitor.value.ssl_certificate.exists) return '未找到'
  const status = systemMonitor.value.ssl_certificate.status
  if (status === 'healthy') return '正常'
  if (status === 'warning') return '即将过期'
  if (status === 'critical') return '紧急'
  if (status === 'expired') return '已过期'
  return '错误'
}

function getSSLDaysClass() {
  if (!systemMonitor.value.ssl_certificate) return ''
  const days = systemMonitor.value.ssl_certificate.days_remaining
  if (days <= 7) return 'text-danger font-bold'
  if (days <= 30) return 'text-warning font-bold'
  return 'text-success'
}

function getProxyStatusClass() {
  if (!systemMonitor.value.proxies) return 'bg-gray-500'
  const { avgHealth, failed } = systemMonitor.value.proxies
  if (avgHealth >= 80 && failed === 0) return 'bg-success'
  if (avgHealth >= 50) return 'bg-warning'
  return 'bg-danger'
}

function getProxyStatusTextClass() {
  if (!systemMonitor.value.proxies) return 'text-gray-500'
  const { avgHealth, failed } = systemMonitor.value.proxies
  if (avgHealth >= 80 && failed === 0) return 'text-success'
  if (avgHealth >= 50) return 'text-warning'
  return 'text-danger'
}

function getProxyStatusText() {
  if (!systemMonitor.value.proxies) return '未配置'
  const { total, active, failed, avgHealth } = systemMonitor.value.proxies
  if (total === 0) return '无代理'
  if (avgHealth >= 80 && failed === 0) return '健康'
  if (avgHealth >= 50) return '警告'
  return '异常'
}

function getProxyHealthClass() {
  if (!systemMonitor.value.proxies) return ''
  const health = systemMonitor.value.proxies.avgHealth
  if (health >= 80) return 'text-success font-bold'
  if (health >= 50) return 'text-warning font-bold'
  return 'text-danger font-bold'
}

function getProxyHealthBarColor() {
  if (!systemMonitor.value.proxies) return 'bg-gray-500'
  const health = systemMonitor.value.proxies.avgHealth
  if (health >= 80) return 'bg-success'
  if (health >= 50) return 'bg-warning'
  return 'bg-danger'
}

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    fetchStatus()
    refreshInterval = setInterval(fetchStatus, 30000)
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
