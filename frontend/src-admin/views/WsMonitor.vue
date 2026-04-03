<template>
  <div class="container mx-auto px-4 py-6 space-y-6">

    <!-- 页头 -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h1 class="text-2xl font-bold">WebSocket 连接监控</h1>
        <p class="text-xs text-text-tertiary mt-0.5">实时监控 Go 后端 WebSocket 推送状态 · {{ wsUrl }}</p>
      </div>
      <div class="flex items-center gap-3 flex-wrap">
        <div :class="['w-3 h-3 rounded-full', connected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        <span :class="['text-sm font-bold', connected ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
          {{ connected ? '已连接' : '未连接' }}
        </span>
        <button v-if="!connected" @click="connect"
          class="px-3 py-1.5 bg-[#0ecb81] text-dark-300 font-semibold rounded-lg text-sm hover:bg-[#0db774] transition-colors">
          重新连接
        </button>
        <button v-else @click="disconnect"
          class="px-3 py-1.5 bg-[#f6465d] text-white font-semibold rounded-lg text-sm hover:bg-[#e03d52] transition-colors">
          断开连接
        </button>
        <button @click="clearStats"
          class="px-3 py-1.5 bg-dark-100 text-text-secondary rounded-lg text-sm hover:bg-dark-50 transition-colors border border-border-primary">
          清除统计
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary mb-1">消息总数</div>
        <div class="text-2xl font-mono font-bold text-text-primary">{{ stats.totalMessages }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary mb-1">连接时长</div>
        <div class="text-2xl font-mono font-bold text-text-primary">{{ formatUptime(stats.uptime) }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary mb-1">消息速率</div>
        <div class="text-2xl font-mono font-bold text-primary">{{ stats.messageRate }}/s</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary mb-1">服务端连接数</div>
        <div class="text-2xl font-mono font-bold text-[#f0b90b]">{{ serverStats.connections?.total ?? '--' }}</div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">

      <!-- 左列 -->
      <div class="space-y-4">

        <!-- 健康状态 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="flex items-center justify-between mb-3">
            <div class="text-sm font-bold">健康状态</div>
            <div :class="['px-2 py-0.5 rounded text-xs font-bold', healthStatusClass]">{{ healthStatusText }}</div>
          </div>
          <div v-if="healthStatus.issues.length" class="space-y-1.5">
            <div v-for="(issue, i) in healthStatus.issues" :key="i" class="flex items-start gap-2 text-xs">
              <span :class="issue.level === 'critical' ? 'text-[#f6465d]' : 'text-[#FF9500]'">⚠</span>
              <span class="text-text-secondary">{{ issue.message }}</span>
            </div>
          </div>
          <div v-else class="text-xs text-text-tertiary">所有指标正常</div>
        </div>

        <!-- 性能指标 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="text-sm font-bold mb-3">性能指标</div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <div class="text-xs text-text-tertiary">平均延迟</div>
              <div class="text-base font-mono font-bold">{{ perf.avgLatency.toFixed(0) }}ms</div>
            </div>
            <div>
              <div class="text-xs text-text-tertiary">最大延迟</div>
              <div class="text-base font-mono font-bold">{{ perf.maxLatency === 0 ? '-' : perf.maxLatency.toFixed(0) + 'ms' }}</div>
            </div>
            <div>
              <div class="text-xs text-text-tertiary">重连次数</div>
              <div class="text-base font-mono font-bold">{{ perf.reconnectCount }}</div>
            </div>
            <div>
              <div class="text-xs text-text-tertiary">丢失消息</div>
              <div class="text-base font-mono font-bold">{{ perf.lostMessages }}</div>
            </div>
          </div>
        </div>

        <!-- 推流服务状态（Streamers） -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="flex items-center justify-between mb-3">
            <div class="text-sm font-bold">推流服务状态</div>
            <button @click="fetchServerStats" class="text-xs text-primary hover:text-primary-hover transition-colors">刷新</button>
          </div>
          <div class="space-y-3">
            <div v-for="(cfg, name) in STREAMER_CONFIGS" :key="name"
              class="bg-dark-200 rounded-lg p-3">
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                  <div :class="['w-2 h-2 rounded-full', getStreamerDot(name)]"></div>
                  <span class="text-xs font-semibold">{{ cfg.label }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <span class="text-xs text-text-tertiary font-mono">
                    推送 {{ serverStats.streamers?.[name]?.broadcast_count ?? '--' }} 次
                  </span>
                  <span v-if="(serverStats.streamers?.[name]?.error_count ?? 0) > 0"
                    class="text-xs text-[#f6465d] font-mono">
                    错误 {{ serverStats.streamers[name].error_count }}
                  </span>
                </div>
              </div>
              <!-- 频率调整 -->
              <div class="flex items-center gap-2">
                <span class="text-xs text-text-tertiary whitespace-nowrap">推送间隔:</span>
                <select v-model="streamerIntervals[name]" @change="updateStreamerInterval(name)"
                  class="flex-1 px-2 py-1 bg-dark-300 border border-border-secondary rounded text-xs focus:outline-none focus:border-primary">
                  <option v-for="opt in cfg.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
                <span class="text-xs text-text-tertiary whitespace-nowrap font-mono">
                  当前: {{ ((serverStats.streamers?.[name]?.interval_ms ?? 0) / 1000).toFixed(1) }}s
                </span>
              </div>
            </div>
            <div v-if="!serverStats.streamers" class="text-xs text-text-tertiary text-center py-2">加载中...</div>
          </div>
        </div>

        <!-- 消息类型统计 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="text-sm font-bold mb-3">消息类型统计</div>
          <div class="space-y-2 max-h-52 overflow-y-auto">
            <div v-for="(count, type) in stats.messageTypes" :key="type"
              class="flex items-center justify-between text-sm">
              <div class="flex items-center gap-2">
                <div :class="['w-2 h-2 rounded-full', getTypeColor(type)]"></div>
                <span class="text-text-secondary">{{ formatMessageType(type) }}</span>
              </div>
              <span class="font-mono text-text-tertiary">{{ count }}</span>
            </div>
            <div v-if="!Object.keys(stats.messageTypes).length" class="text-xs text-text-tertiary">暂无消息记录</div>
          </div>
        </div>

        <!-- 最近消息 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="text-sm font-bold mb-3">最近消息（最新 10 条）</div>
          <div class="space-y-1 max-h-52 overflow-y-auto">
            <div v-for="msg in recentMessages" :key="msg.id"
              class="flex items-center justify-between text-xs bg-dark-200 rounded px-2 py-1.5">
              <div class="flex items-center gap-2">
                <span class="text-text-tertiary font-mono">{{ formatTime(msg.timestamp) }}</span>
                <span :class="['font-bold', getTypeTextColor(msg.type)]">{{ formatMessageType(msg.type) }}</span>
              </div>
              <span class="text-text-tertiary font-mono">{{ msg.size }} bytes</span>
            </div>
            <div v-if="!recentMessages.length" class="text-xs text-text-tertiary">等待消息...</div>
          </div>
        </div>
      </div>

      <!-- 右列 -->
      <div class="space-y-4">

        <!-- 图表 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="text-sm font-bold mb-3">消息速率趋势（最近 5 分钟）</div>
          <div class="h-52">
            <Line :data="rateChartData" :options="chartOptions('#0ecb81', '消息速率 (msg/s)')" />
          </div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="text-sm font-bold mb-3">延迟趋势（最近 5 分钟）</div>
          <div class="h-52">
            <Line :data="latencyChartData" :options="chartOptions('#f0b90b', '平均延迟 (ms)')" />
          </div>
        </div>

        <!-- 服务端连接信息（Go Hub） -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="flex items-center justify-between mb-3">
            <div class="text-sm font-bold">服务端信息（Go Hub）</div>
            <div class="flex items-center gap-2">
              <span class="text-xs text-text-tertiary">15s 自动刷新</span>
              <button @click="fetchServerStats" class="text-xs text-primary hover:text-primary-hover transition-colors">刷新</button>
            </div>
          </div>
          <div class="space-y-2 text-xs">
            <div class="flex justify-between">
              <span class="text-text-tertiary">当前连接数</span>
              <span class="font-mono font-bold text-primary">{{ serverStats.connections?.total ?? '--' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">在线用户数</span>
              <span class="font-mono text-text-secondary">{{ serverStats.connections?.by_user ?? '--' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">在线用户</span>
              <span class="font-mono text-text-secondary text-right max-w-[200px] truncate">
                {{ serverStats.connections?.users?.join(', ') || '--' }}
              </span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">服务</span>
              <span class="font-mono text-text-secondary">{{ serverStats.service ?? 'hustle-go' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">服务器时间</span>
              <span class="font-mono text-text-secondary">
                {{ serverStats.server_time ? formatTime(new Date(serverStats.server_time)) : '--' }}
              </span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">Python Streamer</span>
              <span class="font-mono" :class="serverStats.streamers ? 'text-[#0ecb81]' : 'text-text-tertiary'">
                {{ serverStats.streamers ? '运行中' : '--' }}
              </span>
            </div>
          </div>
        </div>

        <!-- Redis 桥接通道 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
          <div class="text-sm font-bold mb-3">Redis 推流桥接通道</div>
          <div class="space-y-1.5 text-xs">
            <div v-for="ch in REDIS_CHANNELS" :key="ch.channel"
              class="flex items-center justify-between bg-dark-200 rounded px-2 py-1.5">
              <div class="flex items-center gap-2">
                <div :class="['w-1.5 h-1.5 rounded-full', connected ? 'bg-[#0ecb81]' : 'bg-gray-600']"></div>
                <span class="text-text-tertiary font-mono">{{ ch.channel }}</span>
              </div>
              <span class="text-text-secondary">{{ ch.desc }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  PointElement, LineElement, Title, Tooltip, Legend, Filler
} from 'chart.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

// ── 常量配置 ─────────────────────────────────────────────────
const STREAMER_CONFIGS = {
  market_data: {
    label: '市场数据 (Market Data)',
    options: [
      { value: 0.5, label: '0.5s（高频）' },
      { value: 1,   label: '1s（默认）' },
      { value: 2,   label: '2s' },
      { value: 5,   label: '5s（低频）' },
    ]
  },
  account_balance: {
    label: '账户余额 (Account Balance)',
    options: [
      { value: 5,  label: '5s' },
      { value: 10, label: '10s' },
      { value: 30, label: '30s（默认）' },
      { value: 60, label: '60s（低频）' },
    ]
  },
  risk_metrics: {
    label: '风险指标 (Risk Metrics)',
    options: [
      { value: 10,  label: '10s' },
      { value: 30,  label: '30s（默认）' },
      { value: 60,  label: '60s' },
      { value: 120, label: '120s（低频）' },
    ]
  },
  mt5_connection: {
    label: 'MT5 连接状态',
    options: [
      { value: 10,  label: '10s' },
      { value: 30,  label: '30s（默认）' },
      { value: 60,  label: '60s' },
      { value: 120, label: '120s（低频）' },
    ]
  },
}

const REDIS_CHANNELS = [
  { channel: 'ws:broadcast',       desc: '通用广播（策略/持仓）' },
  { channel: 'ws:market_data',     desc: '市场行情数据' },
  { channel: 'ws:account_balance', desc: '账户余额更新' },
  { channel: 'ws:risk_metrics',    desc: '风险指标' },
  { channel: 'ws:order_update',    desc: '订单成交事件' },
  { channel: 'ws:position_update', desc: '持仓变化' },
]

// ── WebSocket URL ────────────────────────────────────────────
const wsUrl = computed(() => `${location.origin}/api/v1/ws`)
let ws = null

// ── 响应式状态 ───────────────────────────────────────────────
const connected      = ref(false)
const stats          = ref({ totalMessages: 0, uptime: 0, messageRate: 0, messageTypes: {}, lastMessageTime: null })
const perf           = ref({ avgLatency: 0, maxLatency: 0, lostMessages: 0, reconnectCount: 0 })
const healthStatus   = ref({ status: 'healthy', issues: [] })
const recentMessages = ref([])
const serverStats    = ref({})
const streamerIntervals = ref({
  market_data: 1, account_balance: 30, risk_metrics: 30, mt5_connection: 30
})

const rateHistory    = ref([])
const latencyHistory = ref([])
const MAX_POINTS = 300

let connectionStartTime = null
let msgCountLastSec = 0
let uptimeTimer = null, rateTimer = null, healthTimer = null, serverTimer = null

// ── 计算属性 ─────────────────────────────────────────────────
const healthStatusClass = computed(() => ({
  healthy:  'bg-[#0ecb81]/20 text-[#0ecb81]',
  warning:  'bg-[#FF9500]/20 text-[#FF9500]',
  critical: 'bg-[#f6465d]/20 text-[#f6465d]',
}[healthStatus.value.status] || 'bg-[#0ecb81]/20 text-[#0ecb81]'))

const healthStatusText = computed(() =>
  ({ healthy: '健康', warning: '警告', critical: '严重' }[healthStatus.value.status] || '未知'))

const rateChartData = computed(() => ({
  labels: rateHistory.value.map(d => dayjs(d.time).format('HH:mm:ss')),
  datasets: [{ label: '消息速率', data: rateHistory.value.map(d => d.rate),
    borderColor: '#0ecb81', backgroundColor: 'rgba(14,203,129,0.1)',
    fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
}))

const latencyChartData = computed(() => ({
  labels: latencyHistory.value.map(d => dayjs(d.time).format('HH:mm:ss')),
  datasets: [{ label: '平均延迟', data: latencyHistory.value.map(d => d.latency),
    borderColor: '#f0b90b', backgroundColor: 'rgba(240,185,11,0.1)',
    fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
}))

function chartOptions(color, label) {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { mode: 'index', intersect: false, backgroundColor: 'rgba(0,0,0,0.8)', borderColor: color, borderWidth: 1 }
    },
    scales: {
      x: { display: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888', maxTicksLimit: 8 } },
      y: { display: true, beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888' } }
    }
  }
}

// ── WebSocket 连接 ───────────────────────────────────────────
function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return
  const token = localStorage.getItem('admin_token')
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/api/v1/ws?token=${token}`
  ws = new WebSocket(url)

  ws.onopen = () => {
    connected.value = true
    connectionStartTime = Date.now()
    stats.value.uptime = 0
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      stats.value.totalMessages++
      msgCountLastSec++
      stats.value.lastMessageTime = Date.now()

      // 延迟计算：Go 发出的 timestamp 是 UnixMilli
      if (msg.timestamp) {
        const latency = Date.now() - msg.timestamp
        if (latency >= 0 && latency < 60000) {
          perf.value.avgLatency = stats.value.totalMessages === 1
            ? latency
            : (perf.value.avgLatency * (stats.value.totalMessages - 1) + latency) / stats.value.totalMessages
          perf.value.maxLatency = Math.max(perf.value.maxLatency, latency)
        }
      }

      const type = msg.type || 'unknown'
      stats.value.messageTypes[type] = (stats.value.messageTypes[type] || 0) + 1

      recentMessages.value = [
        { id: Date.now() + Math.random(), type, timestamp: Date.now(), size: event.data.length },
        ...recentMessages.value
      ].slice(0, 10)
    } catch {}
  }

  ws.onclose = () => {
    connected.value = false
    connectionStartTime = null
    perf.value.reconnectCount++
  }

  ws.onerror = () => { connected.value = false }
}

function disconnect() {
  if (ws) { ws.close(); ws = null }
  connected.value = false
}

// ── 服务端统计 ───────────────────────────────────────────────
// admin 站点: 所有 /api/ 走 Python，/api/v1/ws/stats 返回完整数据
// (connections + streamers + server_time)
async function fetchServerStats() {
  try {
    const r = await api.get('/api/v1/ws/stats')
    if (r.data) {
      serverStats.value = {
        ...serverStats.value,
        ...r.data,
        connections: {
          ...(serverStats.value.connections || {}),
          ...(r.data.connections || {}),
        }
      }
      // 同步本地 interval 选择框
      for (const name of Object.keys(STREAMER_CONFIGS)) {
        const ms = r.data.streamers?.[name]?.interval_ms
        if (ms) streamerIntervals.value[name] = ms / 1000
      }
    }
  } catch {}
}

// ── Streamer 频率控制 ─────────────────────────────────────────
async function updateStreamerInterval(name) {
  const interval = streamerIntervals.value[name]
  try {
    await api.post('/api/v1/ws/config', { streamer: name, interval })
    await fetchServerStats()
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '未知错误'
    alert(`调整失败: ${detail}`)
    // 回滚到当前服务端值
    const ms = serverStats.value.streamers?.[name]?.interval_ms
    if (ms) streamerIntervals.value[name] = ms / 1000
  }
}

// ── 定时器 ───────────────────────────────────────────────────
function startTimers() {
  uptimeTimer = setInterval(() => {
    if (connectionStartTime) stats.value.uptime = Date.now() - connectionStartTime
  }, 1000)

  rateTimer = setInterval(() => {
    const now = Date.now()
    stats.value.messageRate = msgCountLastSec
    rateHistory.value.push({ time: now, rate: msgCountLastSec })
    latencyHistory.value.push({ time: now, latency: perf.value.avgLatency })
    const cutoff = now - 5 * 60 * 1000
    rateHistory.value    = rateHistory.value.filter(d => d.time > cutoff).slice(-MAX_POINTS)
    latencyHistory.value = latencyHistory.value.filter(d => d.time > cutoff).slice(-MAX_POINTS)
    msgCountLastSec = 0
  }, 1000)

  healthTimer = setInterval(checkHealth, 5000)
  serverTimer = setInterval(fetchServerStats, 15000)
}

function checkHealth() {
  const issues = []
  if (!connected.value)
    issues.push({ level: 'critical', message: 'WebSocket 未连接' })
  if (perf.value.avgLatency > 1000)
    issues.push({ level: 'warning', message: `平均延迟过高: ${perf.value.avgLatency.toFixed(0)}ms` })
  if (stats.value.messageRate === 0 && connected.value && stats.value.uptime > 10000)
    issues.push({ level: 'warning', message: '未收到消息（可能无数据推送或 streamer 异常）' })
  if (perf.value.reconnectCount > 5)
    issues.push({ level: 'warning', message: `频繁重连 (${perf.value.reconnectCount} 次)` })
  for (const [name, cfg] of Object.entries(STREAMER_CONFIGS)) {
    const errCount = serverStats.value.streamers?.[name]?.error_count ?? 0
    if (errCount > 100)
      issues.push({ level: 'warning', message: `${cfg.label} 推流错误 ${errCount} 次` })
  }
  healthStatus.value = {
    issues,
    status: issues.some(i => i.level === 'critical') ? 'critical'
          : issues.length ? 'warning' : 'healthy'
  }
}

function clearStats() {
  stats.value = { totalMessages: 0, uptime: stats.value.uptime, messageRate: 0, messageTypes: {}, lastMessageTime: null }
  perf.value  = { avgLatency: 0, maxLatency: 0, lostMessages: 0, reconnectCount: 0 }
  recentMessages.value = []
  rateHistory.value    = []
  latencyHistory.value = []
  msgCountLastSec = 0
}

// ── 格式化 ───────────────────────────────────────────────────
function formatUptime(ms) {
  if (!ms) return '0s'
  const s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60)
  return h > 0 ? `${h}h ${m % 60}m` : m > 0 ? `${m}m ${s % 60}s` : `${s}s`
}

function formatTime(ts) { return dayjs(ts).format('HH:mm:ss') }

function formatMessageType(type) {
  return ({
    market_data: '市场数据', account_balance: '账户余额', risk_metrics: '风险指标',
    order_update: '订单更新', position_update: '持仓更新', connection: 'WS连接建立',
    strategy_status: '策略状态', strategy_trigger_progress: '策略触发进度',
    strategy_position_change: '策略持仓变化', strategy_execution_started: '策略执行开始',
    strategy_execution_completed: '策略执行完成', strategy_execution_error: '策略执行错误',
    strategy_order_executed: '策略订单执行', mt5_connection_status: 'MT5连接状态',
    system_notification: '系统通知', risk_alert: '风险警报',
    spread: '价差数据', tick: '行情Tick', position_snapshot: '持仓快照',
    unknown: '未知',
  })[type] || type
}

function getTypeColor(type) {
  return ({
    market_data: 'bg-[#0ecb81]', account_balance: 'bg-[#5AC8FA]', risk_metrics: 'bg-[#FF9500]',
    order_update: 'bg-[#f0b90b]', position_update: 'bg-[#AF52DE]', connection: 'bg-[#64D2FF]',
    strategy_status: 'bg-[#00C98B]', strategy_trigger_progress: 'bg-[#34C759]',
    strategy_position_change: 'bg-[#30D158]', strategy_execution_started: 'bg-[#32ADE6]',
    strategy_execution_completed: 'bg-[#0ecb81]', strategy_execution_error: 'bg-[#f6465d]',
    strategy_order_executed: 'bg-[#FFD60A]', mt5_connection_status: 'bg-[#BF5AF2]',
    system_notification: 'bg-[#64D2FF]', risk_alert: 'bg-[#f6465d]',
    spread: 'bg-[#0ecb81]', tick: 'bg-[#32ADE6]', position_snapshot: 'bg-[#AF52DE]',
  })[type] || 'bg-gray-500'
}

function getTypeTextColor(type) {
  return ({
    market_data: 'text-[#0ecb81]', account_balance: 'text-[#5AC8FA]', risk_metrics: 'text-[#FF9500]',
    order_update: 'text-[#f0b90b]', position_update: 'text-[#AF52DE]', connection: 'text-[#64D2FF]',
    strategy_status: 'text-[#00C98B]', strategy_trigger_progress: 'text-[#34C759]',
    strategy_position_change: 'text-[#30D158]', strategy_execution_started: 'text-[#32ADE6]',
    strategy_execution_completed: 'text-[#0ecb81]', strategy_execution_error: 'text-[#f6465d]',
    strategy_order_executed: 'text-[#FFD60A]', mt5_connection_status: 'text-[#BF5AF2]',
    system_notification: 'text-[#64D2FF]', risk_alert: 'text-[#f6465d]',
    spread: 'text-[#0ecb81]', tick: 'text-[#32ADE6]', position_snapshot: 'text-[#AF52DE]',
  })[type] || 'text-gray-500'
}

function getStreamerDot(name) {
  const s = serverStats.value.streamers?.[name]
  if (!s) return 'bg-gray-600'
  if (!s.running) return 'bg-[#f6465d]'
  if ((s.error_count ?? 0) > 100) return 'bg-[#FF9500]'
  return 'bg-[#0ecb81] animate-pulse'
}

// ── 生命周期 ─────────────────────────────────────────────────
onMounted(() => {
  connect()
  startTimers()
  fetchServerStats()
})

onUnmounted(() => {
  disconnect()
  clearInterval(uptimeTimer)
  clearInterval(rateTimer)
  clearInterval(healthTimer)
  clearInterval(serverTimer)
})
</script>
