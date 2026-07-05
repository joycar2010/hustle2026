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

              <!-- 自动策略进程 (continuous ladder arbitrage) -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between mb-3">
                  <div class="flex items-center space-x-3">
                    <div :class="['w-3 h-3 rounded-full', anyStrategyRunning ? 'bg-success animate-pulse' : 'bg-gray-500']"></div>
                    <h3 class="font-medium">自动策略进程</h3>
                  </div>
                  <span :class="['text-sm', anyStrategyRunning ? 'text-success' : 'text-text-tertiary']">{{ runningStrategyCount }} 个运行中</span>
                </div>

                <div class="space-y-3">
                  <!-- 策略功能组件 (全局组件) -->
                  <div class="grid grid-cols-2 gap-2">
                    <div class="bg-dark-300 rounded p-2 flex items-center justify-between">
                      <span class="text-xs text-text-tertiary">策略管理器</span>
                      <span class="flex items-center gap-1.5">
                        <span :class="['w-2 h-2 rounded-full', statusData.strategyManager ? 'bg-success' : 'bg-danger']"></span>
                        <span :class="['text-xs', statusData.strategyManager ? 'text-success' : 'text-danger']">{{ statusData.strategyManager ? '运行中' : '停止' }}</span>
                      </span>
                    </div>
                    <div class="bg-dark-300 rounded p-2 flex items-center justify-between">
                      <span class="text-xs text-text-tertiary">持仓监控</span>
                      <span class="flex items-center gap-1.5">
                        <span :class="['w-2 h-2 rounded-full', positionMonitorStatus.active ? 'bg-success' : 'bg-danger']"></span>
                        <span :class="['text-xs', positionMonitorStatus.active ? 'text-success' : 'text-danger']">{{ positionMonitorStatus.active ? '运行中' : '停止' }}</span>
                      </span>
                    </div>
                  </div>

                  <!-- 4 个连续执行进程: 反向/正向 × 开仓/平仓 -->
                  <div v-for="slot in STRATEGY_SLOTS" :key="slot.key" class="bg-dark-300 rounded p-2.5">
                    <div class="flex items-center justify-between">
                      <div class="flex items-center gap-2">
                        <span :class="['w-2 h-2 rounded-full', procDotClass(slot.key)]"></span>
                        <span class="text-sm font-medium">{{ slot.label }}</span>
                      </div>
                      <span :class="['text-xs px-2 py-0.5 rounded', procBadgeClass(slot.key)]">{{ procStatusText(slot.key) }}</span>
                    </div>
                    <div v-if="strategyProcesses[slot.key].running" class="mt-2 space-y-1.5 text-xs text-text-tertiary">
                      <div class="flex justify-between items-center">
                        <span>触发进度</span>
                        <span class="font-mono text-text-secondary">{{ strategyProcesses[slot.key].trigger.current }} / {{ strategyProcesses[slot.key].trigger.required || '-' }}</span>
                      </div>
                      <div v-if="strategyProcesses[slot.key].trigger.required" class="w-full bg-dark-100 rounded-full h-1.5">
                        <div class="h-1.5 rounded-full bg-success transition-all" :style="{ width: triggerPct(slot.key) + '%' }"></div>
                      </div>
                      <div class="flex justify-between">
                        <span>当前阶梯</span>
                        <span class="font-mono text-text-secondary">{{ strategyProcesses[slot.key].current_ladder != null ? ('第 ' + strategyProcesses[slot.key].current_ladder + ' 阶') : '-' }}</span>
                      </div>
                      <div class="flex justify-between">
                        <span>开始时间</span>
                        <span class="font-mono text-text-secondary">{{ formatTimestamp(strategyProcesses[slot.key].started_at) }}</span>
                      </div>
                    </div>
                    <div v-else class="mt-1 text-xs text-text-tertiary">{{ procStatusText(slot.key) === '失败' ? '上次执行失败' : '空闲 — 未在自动执行' }}</div>
                  </div>
                </div>
              </div>

              <!-- WebSocket Status (live: 直接读 marketStore 连接态) -->
              <div class="bg-dark-200 rounded-lg p-4">
                <div class="flex items-center justify-between">
                  <div class="flex items-center space-x-3">
                    <div :class="['w-3 h-3 rounded-full', wsConnected ? 'bg-success animate-pulse' : 'bg-danger']"></div>
                    <span class="font-medium">WebSocket连接</span>
                  </div>
                  <span :class="['text-sm', wsConnected ? 'text-success' : 'text-danger']">
                    {{ wsConnected ? '已连接' : '未连接' }}
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
                  <span :class="['text-sm', getDbPoolStatusColor()]">{{ getDbPoolUsageText() }}</span>
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
                      <div class="flex justify-between"><span>版本</span><span>{{ systemMonitor.redis.version }}</span></div>
                      <div class="flex justify-between"><span>内存使用</span><span>{{ systemMonitor.redis.used_memory_human }}</span></div>
                      <div class="flex justify-between"><span>连接数</span><span>{{ systemMonitor.redis.connected_clients }}</span></div>
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
                        <span :class="['text-sm', getFeishuStatusTextClass()]">{{ getFeishuStatusText() }}</span>
                      </div>
                    </div>
                    <div v-if="systemMonitor.feishu?.configured" class="text-xs text-text-tertiary">
                      Webhook: {{ systemMonitor.feishu.webhook_url }}
                    </div>
                    <div v-else-if="systemMonitor.feishu?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.feishu.error }}
                    </div>
                  </div>

                  <!-- SSL Certificate (go.hustle2026.xyz) -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">SSL证书 (go.hustle2026.xyz)</span>
                      <div class="flex items-center space-x-2">
                        <div :class="['w-2 h-2 rounded-full', getSSLStatusClass()]"></div>
                        <span :class="['text-sm', getSSLStatusTextClass()]">{{ getSSLStatusText() }}</span>
                      </div>
                    </div>
                    <div v-if="systemMonitor.ssl_certificate?.exists" class="space-y-1 text-xs text-text-tertiary">
                      <div class="flex justify-between"><span>剩余天数</span><span :class="getSSLDaysClass()">{{ systemMonitor.ssl_certificate.days_remaining }} 天</span></div>
                      <div class="flex justify-between"><span>过期时间</span><span>{{ formatDate(systemMonitor.ssl_certificate.expires_at) }}</span></div>
                      <div class="flex justify-between"><span>颁发者</span><span>{{ systemMonitor.ssl_certificate.issuer || '-' }}</span></div>
                      <div v-if="systemMonitor.ssl_certificate.domain_names?.length" class="flex justify-between">
                        <span>域名</span><span>{{ systemMonitor.ssl_certificate.domain_names.join(', ') }}</span>
                      </div>
                    </div>
                    <!-- Other domains summary -->
                    <div v-if="systemMonitor.ssl_all_certs?.length > 1" class="mt-2 pt-2 border-t border-dark-400">
                      <div class="text-xs text-text-tertiary mb-1">其他域名证书:</div>
                      <div v-for="cert in systemMonitor.ssl_all_certs.filter(c => !(c.domain_names || []).includes('go.hustle2026.xyz'))" :key="cert.cert_path" class="flex items-center justify-between text-xs text-text-tertiary">
                        <span>{{ (cert.domain_names || [])[0] || cert.cert_path }}</span>
                        <span :class="cert.status === 'healthy' ? 'text-success' : 'text-warning'">{{ cert.days_remaining }}天</span>
                      </div>
                    </div>
                    <div v-else-if="systemMonitor.ssl_certificate?.error" class="text-xs text-danger mt-1">
                      {{ systemMonitor.ssl_certificate.error }}
                    </div>
                  </div>

                  <!-- IPIPGO Static IP Proxy (参考 testadmin 总控面板 IP 代理状态) -->
                  <div class="bg-dark-300 rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-sm font-medium">IPIPGO 静态IP代理</span>
                      <span class="text-xs text-text-tertiary">{{ (systemMonitor.proxies || []).length }} 个绑定</span>
                    </div>
                    <div v-if="(systemMonitor.proxies || []).length" class="space-y-2">
                      <div v-for="(p, i) in systemMonitor.proxies" :key="i" class="bg-dark-200 rounded p-2 text-xs space-y-1">
                        <div class="flex items-center justify-between mb-0.5">
                          <span class="text-text-secondary font-medium truncate">{{ p.account_name }}</span>
                          <span :class="['px-1.5 py-0.5 rounded', proxyStatusClass(p)]">{{ proxyStatusText(p) }}</span>
                        </div>
                        <div class="flex justify-between"><span class="text-text-tertiary">IP地址</span><span class="font-mono text-text-secondary">{{ p.host }}:{{ p.port }}</span></div>
                        <div class="flex justify-between"><span class="text-text-tertiary">地区</span><span class="text-text-secondary">{{ p.region || '-' }}</span></div>
                        <div class="flex justify-between"><span class="text-text-tertiary">协议</span><span class="text-text-secondary uppercase">{{ p.proxy_type || 'socks5' }}</span></div>
                        <div v-if="p.allocated_at" class="flex justify-between"><span class="text-text-tertiary">分配日期</span><span class="font-mono text-text-secondary">{{ p.allocated_at }}</span></div>
                        <div v-if="p.expires_at" class="flex justify-between">
                          <span class="text-text-tertiary">到期日期</span>
                          <span class="font-mono" :class="proxyDaysClass(p)">{{ p.expires_at }} <span class="font-normal text-text-tertiary">({{ proxyDaysLeft(p) }}天)</span></span>
                        </div>
                      </div>
                    </div>
                    <div v-else class="text-center text-text-tertiary py-1">未配置代理 — 使用服务器直连</div>
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
                  <span class="text-sm">{{ formatTimestamp(lastUpdatedAt) }}</span>
                </div>
              </div>

            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between p-6 border-t border-border-secondary">
            <span class="text-sm text-text-tertiary">实时事件驱动 · 内容变化即刷新</span>
            <button
              @click="refreshAll"
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
import { ref, computed, watch, onUnmounted } from 'vue'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const props = defineProps({
  isOpen: { type: Boolean, required: true }
})

const emit = defineEmits(['close'])

const marketStore = useMarketStore()
// WebSocket 连接态实时读取（无需轮询）
const wsConnected = computed(() => marketStore.connected)

const loading = ref(false)
const lastUpdatedAt = ref('')
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
  proxies: null,
})

// ───────────────────────── 自动策略进程 ─────────────────────────
const STRATEGY_SLOTS = [
  { key: 'reverse_opening', label: '反向开仓' },
  { key: 'reverse_closing', label: '反向平仓' },
  { key: 'forward_opening', label: '正向开仓' },
  { key: 'forward_closing', label: '正向平仓' },
]
const STRATEGY_KEYS = STRATEGY_SLOTS.map(s => s.key)

function emptyProc() {
  return { running: false, status: 'idle', task_id: null, started_at: null, trigger: { current: 0, required: 0 }, current_ladder: null, last_event_at: null }
}
function makeEmptyProcesses() {
  return { reverse_opening: emptyProc(), reverse_closing: emptyProc(), forward_opening: emptyProc(), forward_closing: emptyProc() }
}

const strategyProcesses = ref(makeEmptyProcesses())
const positionMonitorStatus = ref({ monitoring: false, active: false })

const anyStrategyRunning = computed(() => Object.values(strategyProcesses.value).some(p => p.running))
const runningStrategyCount = computed(() => Object.values(strategyProcesses.value).filter(p => p.running).length)

function procStatusText(key) {
  const s = strategyProcesses.value[key]?.status
  if (s === 'running') return '运行中'
  if (s === 'completed') return '已完成'
  if (s === 'failed') return '失败'
  if (s === 'cancelled') return '已停止'
  return '空闲'
}
function procDotClass(key) {
  const p = strategyProcesses.value[key]
  if (p?.running) return 'bg-success animate-pulse'
  if (p?.status === 'failed') return 'bg-danger'
  return 'bg-gray-500'
}
function procBadgeClass(key) {
  const p = strategyProcesses.value[key]
  if (p?.running) return 'bg-success/20 text-success'
  if (p?.status === 'failed') return 'bg-danger/20 text-danger'
  if (p?.status === 'completed') return 'bg-success/10 text-success'
  return 'bg-dark-100 text-text-tertiary'
}
function triggerPct(key) {
  const t = strategyProcesses.value[key]?.trigger
  if (!t || !t.required) return 0
  return Math.min(100, Math.round((t.current / t.required) * 100))
}

async function fetchStrategyProcesses() {
  try {
    const { data } = await api.get('/api/v1/strategies/execution/tasks')
    const tasks = data?.tasks || []
    const next = makeEmptyProcesses()
    for (const t of tasks) {
      const st = t.strategy_type
      if (next[st]) {
        next[st].running = (t.status === 'running')
        next[st].status = t.status || 'idle'
        next[st].task_id = t.task_id || null
        next[st].started_at = t.started_at || null
      }
    }
    // 保留同一任务的实时 trigger / current_ladder（来自 WS），避免快照覆盖
    for (const k of STRATEGY_KEYS) {
      const prev = strategyProcesses.value[k]
      if (prev && next[k].task_id && next[k].task_id === prev.task_id) {
        next[k].trigger = prev.trigger
        next[k].current_ladder = prev.current_ladder
      }
    }
    strategyProcesses.value = next
  } catch { /* ignore */ }

  try {
    const { data } = await api.get('/api/v1/automation/position-monitor/status')
    positionMonitorStatus.value = { monitoring: !!data?.monitoring, active: !!data?.active }
  } catch { /* ignore */ }
}

function slotKeyFromStrategyId(sid) {
  if (!sid) return ''
  for (const k of STRATEGY_KEYS) {
    if (sid.includes(k)) return k
  }
  return ''
}

// 事件驱动：策略相关 WS 消息直接更新对应进程，仅在内容变化时重渲染
function applyStrategyMessage(type, d) {
  if (!d) return
  const key = slotKeyFromStrategyId(d.strategy_id)
  if (!key) return
  const p = { ...strategyProcesses.value[key] }
  switch (type) {
    case 'strategy_execution_started':
      p.running = true; p.status = 'running'
      p.task_id = d.task_id || p.task_id
      p.started_at = p.started_at || new Date().toISOString()
      break
    case 'strategy_execution_completed':
      p.status = 'completed'; p.running = false
      break
    case 'strategy_execution_error':
      p.status = 'failed'; p.running = false
      break
    case 'strategy_stop_confirmed':
      p.status = 'cancelled'; p.running = false
      p.trigger = { current: 0, required: 0 }; p.current_ladder = null
      break
    case 'strategy_trigger_progress':
      if (!p.running) { p.running = true; p.status = 'running' }
      p.trigger = { current: d.current_count ?? 0, required: d.required_count ?? p.trigger.required ?? 0 }
      break
    case 'strategy_trigger_reset':
      p.trigger = { current: 0, required: p.trigger.required }
      break
    case 'strategy_order_executed':
      if (d.ladder_index != null) p.current_ladder = d.ladder_index + 1
      break
    default:
      return
  }
  p.last_event_at = new Date().toISOString()
  strategyProcesses.value = { ...strategyProcesses.value, [key]: p }
}

// 基础设施类 WS 推送（redis / mt5 连接），到达即更新对应健康位
function applyMainMessage(message) {
  if (!message || !message.type) return
  const t = message.type
  const d = message.data
  if (t === 'redis_status') {
    const connected = (d?.connected ?? d?.healthy) === true
    systemMonitor.value = {
      ...systemMonitor.value,
      redis: { ...(systemMonitor.value.redis || {}), connected, error: d?.last_error ?? d?.error ?? (systemMonitor.value.redis?.error || null) }
    }
    lastUpdatedAt.value = new Date().toISOString()
  } else if (t === 'mt5_connection_status') {
    statusData.value = { ...statusData.value, mt5: !!d?.healthy }
    lastUpdatedAt.value = new Date().toISOString()
  }
}

async function fetchStatus() {
  try {
    loading.value = true

    const response = await api.get('/api/v1/system/status')
    statusData.value = { ...statusData.value, ...response.data }

    const monitorResponse = await api.get('/api/v1/monitor/status')
    const monitorData = { ...monitorResponse.data }

    // Normalize ssl_certificate: Go returns an array of certs.
    // Pick go.hustle2026.xyz cert specifically; keep full array for "other domains" display.
    if (Array.isArray(monitorData.ssl_certificate) && monitorData.ssl_certificate.length > 0) {
      monitorData.ssl_all_certs = monitorData.ssl_certificate
      const goCert = monitorData.ssl_certificate.find(c =>
        (c.domain_names || []).includes('go.hustle2026.xyz')
      )
      monitorData.ssl_certificate = goCert || monitorData.ssl_certificate.reduce((best, cert) =>
        (cert.days_remaining ?? 999) < (best.days_remaining ?? 999) ? cert : best
      )
    }

    systemMonitor.value = { ...systemMonitor.value, ...monitorData }

    // 列出所有账户的 IPIPGO 静态IP代理（参考 testadmin 总控面板 IP 代理状态）
    try {
      const aggResponse = await api.get('/api/v1/accounts/dashboard/aggregated?view=merged')
      const accounts = aggResponse.data?.accounts || []
      const proxyAccounts = accounts.filter(a => a.proxy_config?.host)
      systemMonitor.value.proxies = proxyAccounts.map(a => ({
        account_name: a.account_name || a.account_id,
        platform_id: a.platform_id,
        host: a.proxy_config.host,
        port: a.proxy_config.port,
        region: a.proxy_config.region,
        proxy_type: a.proxy_config.proxy_type,
        ip_status: a.proxy_config.ip_status,
        allocated_at: a.proxy_config.allocated_at,
        expires_at: a.proxy_config.expires_at,
      }))
    } catch {
      systemMonitor.value.proxies = []
    }

    lastUpdatedAt.value = new Date().toISOString()
  } catch (error) {
    console.error('Failed to fetch system status:', error)
  } finally {
    loading.value = false
  }
}

// 手动「立即刷新」：一次性拉取全部（事件驱动模式下的唯一主动刷新入口）
async function refreshAll() {
  await Promise.all([fetchStatus(), fetchStrategyProcesses()])
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

// 代理状态（per-account，对齐 testadmin 总控面板 IP 代理状态）
function proxyStatusOf(p) {
  return p.ip_status || (p.expires_at && new Date(p.expires_at) < new Date() ? 'expired' : 'active')
}
function proxyStatusClass(p) {
  return { active: 'bg-success/20 text-success', expired: 'bg-danger/20 text-danger', pending: 'bg-warning/20 text-warning', cancelled: 'bg-dark-100 text-text-tertiary' }[proxyStatusOf(p)] || 'bg-success/20 text-success'
}
function proxyStatusText(p) {
  return { active: '正常', expired: '已过期', pending: '待生效', cancelled: '已取消' }[proxyStatusOf(p)] || '正常'
}
function proxyDaysLeft(p) {
  if (!p.expires_at) return '--'
  return Math.ceil((new Date(p.expires_at) - new Date()) / 86400000)
}
function proxyDaysClass(p) {
  const d = proxyDaysLeft(p)
  if (d === '--') return 'text-text-secondary'
  if (d <= 7) return 'text-danger font-bold'
  if (d <= 30) return 'text-warning'
  return 'text-success'
}

// ───────── 事件驱动订阅：打开时拉一次基线，之后只随 WS 内容变化刷新 ─────────
let stopMainWatch = null
let stopStrategyWatch = null

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    fetchStatus()
    fetchStrategyProcesses()
    stopMainWatch = watch(() => marketStore.lastMessage, (m) => applyMainMessage(m))
    stopStrategyWatch = watch(() => marketStore.strategyMessage, (m) => {
      if (m && typeof m.type === 'string' && m.type.startsWith('strategy_')) applyStrategyMessage(m.type, m.data)
    })
  } else {
    if (stopMainWatch) { stopMainWatch(); stopMainWatch = null }
    if (stopStrategyWatch) { stopStrategyWatch(); stopStrategyWatch = null }
  }
})

onUnmounted(() => {
  if (stopMainWatch) stopMainWatch()
  if (stopStrategyWatch) stopStrategyWatch()
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
