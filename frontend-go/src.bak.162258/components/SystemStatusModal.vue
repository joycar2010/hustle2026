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
          <div class="p-6 space-y-4">
            <!-- Loading State -->
            <div v-if="loading" class="flex items-center justify-center py-12">
              <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
            </div>

            <div v-else class="space-y-4">

              <!-- WebSocket Status -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between">
                  <div class="flex items-center space-x-3">
                    <div :class="['w-3 h-3 rounded-full', monitors.websocket ? (statusData.websocket ? 'bg-success animate-pulse' : 'bg-danger') : 'bg-gray-600']"></div>
                    <span class="font-medium">WebSocket连接</span>
                  </div>
                  <div class="flex items-center space-x-3">
                    <span v-if="monitors.websocket" :class="['text-sm', statusData.websocket ? 'text-success' : 'text-danger']">
                      {{ statusData.websocket ? '已连接' : '未连接' }}
                    </span>
                    <span v-else class="text-sm text-gray-500">监控已关闭</span>
                    <button @click="toggleMonitor('websocket')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.websocket ? 'bg-primary' : 'bg-gray-600']" :title="monitors.websocket ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.websocket ? 'translate-x-5' : 'translate-x-1']" /></button>
                  </div>
                </div>
              </div>

              <!-- Database Pool Status -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between mb-3">
                  <div class="flex items-center space-x-3">
                    <div :class="['w-3 h-3 rounded-full', monitors.dbPool ? getDbPoolStatus() : 'bg-gray-600']"></div>
                    <span class="font-medium">数据库连接池</span>
                  </div>
                  <div class="flex items-center space-x-3">
                    <span v-if="monitors.dbPool" :class="['text-sm', getDbPoolStatusColor()]">{{ getDbPoolUsageText() }}</span>
                    <span v-else class="text-sm text-gray-500">监控已关闭</span>
                    <button @click="toggleMonitor('dbPool')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.dbPool ? 'bg-primary' : 'bg-gray-600']" :title="monitors.dbPool ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.dbPool ? 'translate-x-5' : 'translate-x-1']" /></button>
                  </div>
                </div>
                <div v-if="monitors.dbPool && statusData.dbPool" class="space-y-2">
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
                <div class="flex items-center justify-between mb-3">
                  <h3 class="font-medium">后端服务</h3>
                  <button @click="toggleMonitor('backend')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.backend ? 'bg-primary' : 'bg-gray-600']" :title="monitors.backend ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.backend ? 'translate-x-5' : 'translate-x-1']" /></button>
                </div>
                <div v-if="monitors.backend" class="space-y-2">
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
                <div v-else class="text-sm text-gray-500">监控已关闭</div>
              </div>

              <!-- Exchange Connections -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between mb-3">
                  <h3 class="font-medium">交易所连接</h3>
                  <button @click="toggleMonitor('exchanges')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.exchanges ? 'bg-primary' : 'bg-gray-600']" :title="monitors.exchanges ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.exchanges ? 'translate-x-5' : 'translate-x-1']" /></button>
                </div>
                <div v-if="monitors.exchanges" class="space-y-2">
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
                <div v-else class="text-sm text-gray-500">监控已关闭</div>
              </div>

              <!-- Infrastructure Services -->
              <div class="bg-dark-200 rounded-lg p-4">
                <h3 class="font-medium mb-3">基础设施服务</h3>
                <div class="space-y-3">

                  <!-- Redis -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">Redis</span>
                      <div class="flex items-center space-x-3">
                        <div v-if="monitors.redis" class="flex items-center space-x-2">
                          <div :class="['w-2 h-2 rounded-full', systemMonitor.redis?.connected ? 'bg-success' : 'bg-danger']"></div>
                          <span :class="['text-sm', systemMonitor.redis?.connected ? 'text-success' : 'text-danger']">
                            {{ systemMonitor.redis?.connected ? '已连接' : '未连接' }}
                          </span>
                        </div>
                        <span v-else class="text-sm text-gray-500">监控已关闭</span>
                        <button @click="toggleMonitor('redis')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.redis ? 'bg-primary' : 'bg-gray-600']" :title="monitors.redis ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.redis ? 'translate-x-5' : 'translate-x-1']" /></button>
                      </div>
                    </div>
                    <div v-if="monitors.redis && systemMonitor.redis?.connected" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between"><span>版本</span><span>{{ systemMonitor.redis.version }}</span></div>
                      <div class="flex justify-between"><span>内存使用</span><span>{{ systemMonitor.redis.used_memory_human }}</span></div>
                      <div class="flex justify-between"><span>连接数</span><span>{{ systemMonitor.redis.connected_clients }}</span></div>
                    </div>
                    <div v-else-if="monitors.redis && systemMonitor.redis?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.redis.error }}
                    </div>
                  </div>

                  <!-- Feishu -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">飞书通知</span>
                      <div class="flex items-center space-x-3">
                        <div v-if="monitors.feishu" class="flex items-center space-x-2">
                          <div :class="['w-2 h-2 rounded-full', getFeishuStatusClass()]"></div>
                          <span :class="['text-sm', getFeishuStatusTextClass()]">{{ getFeishuStatusText() }}</span>
                        </div>
                        <span v-else class="text-sm text-gray-500">监控已关闭</span>
                        <button @click="toggleMonitor('feishu')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.feishu ? 'bg-primary' : 'bg-gray-600']" :title="monitors.feishu ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.feishu ? 'translate-x-5' : 'translate-x-1']" /></button>
                      </div>
                    </div>
                    <div v-if="monitors.feishu && systemMonitor.feishu?.configured" class="text-xs text-text-tertiary">
                      Webhook: {{ systemMonitor.feishu.webhook_url }}
                    </div>
                    <div v-else-if="monitors.feishu && systemMonitor.feishu?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.feishu.error }}
                    </div>
                  </div>

                  <!-- SSL Certificate (go.hustle2026.xyz) -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">SSL证书 (go.hustle2026.xyz)</span>
                      <div class="flex items-center space-x-3">
                        <div v-if="monitors.ssl" class="flex items-center space-x-2">
                          <div :class="['w-2 h-2 rounded-full', getSSLStatusClass()]"></div>
                          <span :class="['text-sm', getSSLStatusTextClass()]">{{ getSSLStatusText() }}</span>
                        </div>
                        <span v-else class="text-sm text-gray-500">监控已关闭</span>
                        <button @click="toggleMonitor('ssl')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.ssl ? 'bg-primary' : 'bg-gray-600']" :title="monitors.ssl ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.ssl ? 'translate-x-5' : 'translate-x-1']" /></button>
                      </div>
                    </div>
                    <div v-if="monitors.ssl && systemMonitor.ssl_certificate?.exists" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between"><span>剩余天数</span><span :class="getSSLDaysClass()">{{ systemMonitor.ssl_certificate.days_remaining }} 天</span></div>
                      <div class="flex justify-between"><span>过期时间</span><span>{{ formatDate(systemMonitor.ssl_certificate.expires_at) }}</span></div>
                      <div class="flex justify-between"><span>颁发者</span><span>{{ systemMonitor.ssl_certificate.issuer || '-' }}</span></div>
                      <div v-if="systemMonitor.ssl_certificate.domain_names?.length" class="flex justify-between">
                        <span>域名</span><span>{{ systemMonitor.ssl_certificate.domain_names.join(', ') }}</span>
                      </div>
                    </div>
                    <!-- Other domains summary -->
                    <div v-if="monitors.ssl && systemMonitor.ssl_all_certs?.length > 1" class="mt-2 pt-2 border-t border-dark-400">
                      <div class="text-xs text-text-tertiary mb-1">其他域名证书:</div>
                      <div v-for="cert in systemMonitor.ssl_all_certs.filter(c => !(c.domain_names || []).includes('go.hustle2026.xyz'))" :key="cert.cert_path" class="flex items-center justify-between text-xs text-text-tertiary">
                        <span>{{ (cert.domain_names || [])[0] || cert.cert_path }}</span>
                        <span :class="cert.status === 'healthy' ? 'text-success' : 'text-warning'">{{ cert.days_remaining }}天</span>
                      </div>
                    </div>
                    <div v-else-if="monitors.ssl && systemMonitor.ssl_certificate?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.ssl_certificate.error }}
                    </div>
                  </div>

                  <!-- IPIPGO Static IP Proxy -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">IPIPGO 静态IP</span>
                      <div class="flex items-center space-x-3">
                        <div v-if="monitors.proxy" class="flex items-center space-x-2">
                          <div :class="['w-2 h-2 rounded-full', getProxyStatusClass()]"></div>
                          <span :class="['text-sm', getProxyStatusTextClass()]">{{ getProxyStatusText() }}</span>
                        </div>
                        <span v-else class="text-sm text-gray-500">监控已关闭</span>
                        <button @click="toggleMonitor('proxy')" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', monitors.proxy ? 'bg-primary' : 'bg-gray-600']" :title="monitors.proxy ? '点击关闭监控' : '点击开启监控'"><span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', monitors.proxy ? 'translate-x-5' : 'translate-x-1']" /></button>
                      </div>
                    </div>
                    <div v-if="monitors.proxy && systemMonitor.ipipgo" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between"><span>IP地址</span><span class="font-mono">{{ systemMonitor.ipipgo.host }}:{{ systemMonitor.ipipgo.port }}</span></div>
                      <div class="flex justify-between"><span>地区</span><span>{{ systemMonitor.ipipgo.region || '-' }}</span></div>
                      <div class="flex justify-between"><span>协议</span><span>{{ systemMonitor.ipipgo.proxy_type || '-' }}</span></div>
                      <div class="flex justify-between"><span>状态</span><span :class="systemMonitor.ipipgo.ip_status === 'active' ? 'text-success' : 'text-danger'">{{ systemMonitor.ipipgo.ip_status === 'active' ? '活跃' : systemMonitor.ipipgo.ip_status || '未知' }}</span></div>
                      <div class="flex justify-between"><span>分配日期</span><span>{{ systemMonitor.ipipgo.allocated_at || '-' }}</span></div>
                      <div class="flex justify-between">
                        <span>到期日期</span>
                        <span :class="getIpipgoExpiryClass()">{{ systemMonitor.ipipgo.expires_at || '-' }}</span>
                      </div>
                      <div class="flex justify-between"><span>绑定账户</span><span>{{ systemMonitor.ipipgo.account_count }}个</span></div>
                    </div>
                    <div v-else-if="monitors.proxy" class="text-xs text-text-tertiary mt-1">未配置 IPIPGO 代理</div>
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
import { ref, reactive, watch, onUnmounted } from 'vue'
import api from '@/services/api'

const props = defineProps({
  isOpen: { type: Boolean, required: true }
})

const emit = defineEmits(['close'])

const STORAGE_KEY = 'system_monitor_switches'

const defaultMonitors = {
  websocket: true,
  dbPool: true,
  backend: true,
  exchanges: true,
  redis: true,
  feishu: true,
  ssl: true,
  proxy: true,
}

function loadMonitors() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? { ...defaultMonitors, ...JSON.parse(saved) } : { ...defaultMonitors }
  } catch {
    return { ...defaultMonitors }
  }
}

const monitors = reactive(loadMonitors())

function toggleMonitor(key) {
  monitors[key] = !monitors[key]
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...monitors }))
}

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
  ssl_all_certs: null,
  ipipgo: null
})

let refreshInterval = null

async function fetchStatus() {
  try {
    loading.value = true

    const needsSystemStatus = monitors.websocket || monitors.dbPool || monitors.backend || monitors.exchanges
    const needsMonitorStatus = monitors.redis || monitors.feishu || monitors.ssl

    if (needsSystemStatus) {
      const response = await api.get('/api/v1/system/status')
      statusData.value = response.data
    }

    if (needsMonitorStatus) {
      const monitorResponse = await api.get('/api/v1/monitor/status')
      const monitorData = { ...monitorResponse.data }

      // Normalize ssl_certificate: Go returns an array of certs.
      // Pick go.hustle2026.xyz cert specifically; keep full array for "other domains" display.
      if (Array.isArray(monitorData.ssl_certificate) && monitorData.ssl_certificate.length > 0) {
        monitorData.ssl_all_certs = monitorData.ssl_certificate
        // Prefer go.hustle2026.xyz; fall back to most-urgent cert
        const goCert = monitorData.ssl_certificate.find(c =>
          (c.domain_names || []).includes('go.hustle2026.xyz')
        )
        monitorData.ssl_certificate = goCert || monitorData.ssl_certificate.reduce((best, cert) =>
          (cert.days_remaining ?? 999) < (best.days_remaining ?? 999) ? cert : best
        )
      }

      systemMonitor.value = { ...systemMonitor.value, ...monitorData }
    }

    if (monitors.proxy) {
      // Load IPIPGO static IP info from account proxy_config (not the empty proxy_pool table)
      try {
        const aggResponse = await api.get('/api/v1/accounts/dashboard/aggregated')
        const accounts = aggResponse.data?.accounts || []
        // Find the first account with a proxy_config that has a host
        const proxyAccounts = accounts.filter(a => a.proxy_config?.host)
        if (proxyAccounts.length > 0) {
          const pc = proxyAccounts[0].proxy_config
          systemMonitor.value.ipipgo = {
            host: pc.host,
            port: pc.port,
            region: pc.region,
            proxy_type: pc.proxy_type,
            ip_status: pc.ip_status,
            allocated_at: pc.allocated_at,
            expires_at: pc.expires_at,
            account_count: proxyAccounts.length,
          }
        } else {
          systemMonitor.value.ipipgo = null
        }
      } catch {
        systemMonitor.value.ipipgo = null
      }
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
  return new Date(timestamp).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  })
}

function formatDate(dateStr) {
  if (!dateStr) return 'N/A'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  })
}

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

function getSSLStatusClass() {
  if (!systemMonitor.value.ssl_certificate) return 'bg-gray-500'
  const s = systemMonitor.value.ssl_certificate.status
  if (s === 'healthy') return 'bg-success'
  if (s === 'warning') return 'bg-warning'
  if (s === 'critical' || s === 'expired') return 'bg-danger'
  return 'bg-gray-500'
}

function getSSLStatusTextClass() {
  if (!systemMonitor.value.ssl_certificate) return 'text-gray-500'
  const s = systemMonitor.value.ssl_certificate.status
  if (s === 'healthy') return 'text-success'
  if (s === 'warning') return 'text-warning'
  if (s === 'critical' || s === 'expired') return 'text-danger'
  return 'text-gray-500'
}

function getSSLStatusText() {
  if (!systemMonitor.value.ssl_certificate) return '未知'
  if (!systemMonitor.value.ssl_certificate.exists) return '未找到'
  const s = systemMonitor.value.ssl_certificate.status
  if (s === 'healthy') return '正常'
  if (s === 'warning') return '即将过期'
  if (s === 'critical') return '紧急'
  if (s === 'expired') return '已过期'
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
  if (!systemMonitor.value.ipipgo) return 'bg-gray-500'
  return systemMonitor.value.ipipgo.ip_status === 'active' ? 'bg-success' : 'bg-danger'
}

function getProxyStatusTextClass() {
  if (!systemMonitor.value.ipipgo) return 'text-gray-500'
  return systemMonitor.value.ipipgo.ip_status === 'active' ? 'text-success' : 'text-danger'
}

function getProxyStatusText() {
  if (!systemMonitor.value.ipipgo) return '未配置'
  return systemMonitor.value.ipipgo.ip_status === 'active' ? '活跃' : '异常'
}

function getIpipgoExpiryClass() {
  if (!systemMonitor.value.ipipgo?.expires_at) return ''
  const daysLeft = Math.ceil((new Date(systemMonitor.value.ipipgo.expires_at) - new Date()) / 86400000)
  if (daysLeft <= 7) return 'text-danger font-bold'
  if (daysLeft <= 14) return 'text-warning font-bold'
  return 'text-success'
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
  if (refreshInterval) clearInterval(refreshInterval)
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
