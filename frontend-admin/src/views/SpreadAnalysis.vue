<template>
  <div class="container mx-auto px-4 py-6 space-y-5">

    <!-- Header + WS Status -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h1 class="text-2xl font-bold">点差分析</h1>
        <p class="text-xs text-text-tertiary mt-0.5">多品种实时点差监控 · WebSocket 500ms 推送</p>
      </div>
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5">
          <div class="w-2 h-2 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-red-500'"></div>
          <span class="text-xs" :class="wsConnected ? 'text-green-400' : 'text-red-400'">{{ wsConnected ? 'WS 实时' : 'HTTP 回退' }}</span>
        </div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
      </div>
    </div>

    <!-- ===== 多品种实时点差排行 ===== -->
    <div class="flex gap-2 overflow-x-auto pb-1">
      <div v-for="pair in sortedLivePairs" :key="pair.pair_code"
        @click="selectPair(pair.pair_code)"
        :class="['flex-shrink-0 bg-dark-100 rounded-xl border p-3 cursor-pointer transition-all min-w-[140px]',
          activePair === pair.pair_code ? 'border-primary bg-primary/5' : 'border-border-primary hover:border-border-focus']">
        <div class="flex items-center justify-between mb-1">
          <span class="font-bold text-sm">{{ pair.pair_code }}</span>
          <div class="w-2 h-2 rounded-full" :class="pair.hasData ? 'bg-green-500 animate-pulse' : 'bg-gray-600'"></div>
        </div>
        <div class="grid grid-cols-2 gap-x-3 text-xs">
          <div>
            <span class="text-text-tertiary">正套</span>
            <div class="font-mono font-bold" :class="spreadColor(pair.forwardEntry)">{{ fmtSpread(pair.forwardEntry) }}</div>
          </div>
          <div>
            <span class="text-text-tertiary">反套</span>
            <div class="font-mono font-bold" :class="spreadColor(pair.reverseEntry)">{{ fmtSpread(pair.reverseEntry) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 活跃品种操作栏 ===== -->
    <div class="flex items-center gap-3 flex-wrap">
      <!-- 时间快选 -->
      <div class="flex gap-1">
        <button v-for="r in timeRanges" :key="r.val" @click="setRange(r.val)"
          :class="['px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors',
            activeRange === r.val ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-100 text-text-secondary border-border-primary hover:border-border-focus']">
          {{ r.label }}
        </button>
      </div>
      <!-- 自定义时间 -->
      <input type="datetime-local" v-model="startTime" class="px-2 py-1.5 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary" />
      <span class="text-text-tertiary text-xs">至</span>
      <input type="datetime-local" v-model="endTime" class="px-2 py-1.5 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary" />
      <select v-model="limit" class="px-2 py-1.5 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary">
        <option v-for="n in [100,300,500,1000]" :key="n" :value="n">{{ n }} 条</option>
      </select>
      <button @click="fetchHistory" :disabled="histLoading" class="px-4 py-1.5 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-lg text-sm transition-colors">
        {{ histLoading ? '查询中' : '查询历史' }}
      </button>
      <!-- 阈值 -->
      <span class="text-xs text-text-tertiary ml-2">机会阈值:</span>
      <input type="number" v-model.number="oppThreshold" step="0.1" min="0" class="w-20 px-2 py-1 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary text-center" />
      <span class="text-xs text-text-tertiary">USDT</span>
    </div>

    <!-- ===== 量化统计指标 ===== -->
    <div class="grid grid-cols-2 md:grid-cols-6 gap-3">
      <div v-for="c in statCards" :key="c.label" class="bg-dark-100 rounded-xl border border-border-primary p-3">
        <div class="text-[10px] text-text-tertiary mb-0.5">{{ c.label }}</div>
        <div class="text-base font-bold font-mono" :class="c.color">{{ c.value }}</div>
        <div v-if="c.sub" class="text-[10px] text-text-tertiary">{{ c.sub }}</div>
      </div>
    </div>

    <!-- ===== 实时点差图表 ===== -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-bold">{{ activePair }} 点差趋势</div>
        <div class="flex items-center gap-4 text-xs">
          <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#0ecb81] inline-block"></span>正套开仓</span>
          <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#f0b90b] inline-block"></span>反套开仓</span>
          <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#f6465d] inline-block border-dashed"></span>阈值 {{ oppThreshold }}</span>
          <span class="text-text-tertiary">{{ wsChartData.length }} 点</span>
        </div>
      </div>
      <div class="h-64">
        <Line :data="chartData" :options="chartOptions" v-if="chartData.labels.length" :key="chartKey" />
        <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">等待数据...</div>
      </div>
    </div>

    <!-- ===== 方向筛选 ===== -->
    <div class="flex items-center gap-3">
      <span class="text-xs text-text-tertiary">方向筛选:</span>
      <button v-for="d in directions" :key="d.val" @click="activeDir = d.val"
        :class="['px-3 py-1 rounded-lg text-xs font-medium border transition-colors',
          activeDir === d.val ? 'bg-primary/20 text-primary border-primary' : 'bg-dark-100 text-text-secondary border-border-primary']">
        {{ d.label }}
      </button>
    </div>

    <!-- ===== 数据表格 ===== -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary overflow-hidden">
      <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
        <span class="font-semibold text-sm">{{ activePair }} 点差记录</span>
        <div class="flex items-center gap-3 text-xs text-text-tertiary">
          <span>{{ dataSource }}</span>
          <span>{{ filteredRecords.length }} 条</span>
          <span>第 {{ currentPage }}/{{ totalPages }} 页</span>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead><tr class="border-b border-border-secondary text-text-tertiary">
            <th class="text-left px-4 py-2.5">时间</th>
            <th class="text-right px-3 py-2.5">CEX Bid</th>
            <th class="text-right px-3 py-2.5">MT5 Ask</th>
            <th class="text-right px-3 py-2.5">正套点差</th>
            <th class="text-right px-3 py-2.5">反套点差</th>
            <th class="text-center px-3 py-2.5">方向</th>
            <th class="text-right px-3 py-2.5">利润率</th>
            <th class="text-center px-4 py-2.5">状态</th>
          </tr></thead>
          <tbody>
            <tr v-if="histLoading"><td colspan="8" class="text-center py-10 text-text-tertiary">加载中...</td></tr>
            <tr v-else-if="!pagedRecords.length"><td colspan="8" class="text-center py-10 text-text-tertiary">暂无数据</td></tr>
            <tr v-for="row in pagedRecords" :key="row.id" class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
              <td class="px-4 py-2 font-mono text-text-tertiary whitespace-nowrap">{{ row.time }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ row.cexBid }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ row.mt5Ask }}</td>
              <td class="px-3 py-2 text-right font-mono font-semibold" :class="spreadColor(parseFloat(row.fwdSpread))">{{ row.fwdSpread }}</td>
              <td class="px-3 py-2 text-right font-mono font-semibold" :class="spreadColor(parseFloat(row.revSpread))">{{ row.revSpread }}</td>
              <td class="px-3 py-2 text-center">
                <span :class="row.dir === 'forward' ? 'text-[#0ecb81] bg-[#0ecb81]/10' : 'text-[#f0b90b] bg-[#f0b90b]/10'" class="px-1.5 py-0.5 rounded text-xs">
                  {{ row.dir === 'forward' ? '正套' : '反套' }}
                </span>
              </td>
              <td class="px-3 py-2 text-right font-mono" :class="parseFloat(row.pct) > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary'">{{ row.pct }}%</td>
              <td class="px-4 py-2 text-center">
                <span v-if="row.isOpp" class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/20 text-[#0ecb81]">机会</span>
                <span v-else class="px-1.5 py-0.5 rounded text-xs bg-dark-200 text-text-tertiary">正常</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- Pagination -->
      <div v-if="totalPages > 1" class="px-4 py-3 border-t border-border-secondary flex items-center justify-between">
        <span class="text-xs text-text-tertiary">{{ (currentPage-1)*pageSize+1 }}–{{ Math.min(currentPage*pageSize, filteredRecords.length) }} / {{ filteredRecords.length }}</span>
        <div class="flex gap-1">
          <button @click="currentPage=1" :disabled="currentPage===1" class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40">«</button>
          <button @click="currentPage--" :disabled="currentPage===1" class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40">‹</button>
          <span class="px-3 py-1 text-xs bg-dark-50 rounded font-mono">{{ currentPage }}/{{ totalPages }}</span>
          <button @click="currentPage++" :disabled="currentPage>=totalPages" class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40">›</button>
          <button @click="currentPage=totalPages" :disabled="currentPage>=totalPages" class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40">»</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler } from 'chart.js'
import { useWebSocket } from '@/composables/useWebSocket.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

// ── WebSocket ──
const { connected: wsConnected, lastMessage, connect: wsConnect, disconnect: wsDisconnect, send: wsSend } = useWebSocket()

// ── State ──
const pairs = ref([])
const activePair = ref('XAU')
const liveData = ref({})        // { pair_code: { forwardEntry, reverseEntry, binanceBid, bybitAsk, ts } }
const wsChartData = ref([])     // rolling window for chart (max 300 points)
const historyData = ref([])     // from HTTP history API
const histLoading = ref(false)
const activeRange = ref('1h')
const activeDir = ref('all')
const limit = ref(300)
const oppThreshold = ref(2.0)
const startTime = ref(dayjs().subtract(1, 'hour').format('YYYY-MM-DDTHH:mm'))
const endTime = ref(dayjs().format('YYYY-MM-DDTHH:mm'))
const currentPage = ref(1)
const pageSize = 50
const lastUpdate = ref('--')
const chartKey = ref(0)
let fallbackTimer = null

const timeRanges = [
  { label: '15分钟', val: '15m' }, { label: '1小时', val: '1h' },
  { label: '6小时', val: '6h' }, { label: '1天', val: '1d' }, { label: '7天', val: '7d' },
]
const directions = [
  { label: '全部', val: 'all' }, { label: '正套', val: 'forward' }, { label: '反套', val: 'reverse' },
]

// ── WS message handler ──
watch(lastMessage, (msg) => {
  if (!msg || msg.type !== 'spread' || !msg.data) return
  const d = msg.data
  const pc = d.pair_code || msg.pair_code
  if (!pc) return

  // Update live data for all pairs
  liveData.value[pc] = {
    forwardEntry: d.forward_entry_spread ?? d.forward_spread ?? 0,
    reverseEntry: d.reverse_entry_spread ?? d.reverse_spread ?? 0,
    binanceBid: d.binance_bid ?? 0,
    binanceAsk: d.binance_ask ?? 0,
    bybitBid: d.bybit_bid ?? 0,
    bybitAsk: d.bybit_ask ?? 0,
    ts: msg.timestamp || Date.now(),
    hasData: true,
  }

  // Append to chart if this is the active pair
  if (pc === activePair.value) {
    const now = dayjs().format('HH:mm:ss')
    wsChartData.value.push({
      time: now,
      fwd: d.forward_entry_spread ?? d.forward_spread ?? 0,
      rev: d.reverse_entry_spread ?? d.reverse_spread ?? 0,
    })
    // Keep max 300 points
    if (wsChartData.value.length > 300) wsChartData.value.shift()
    lastUpdate.value = now
  }
})

// When WS connects, subscribe to all pairs
watch(wsConnected, (val) => {
  if (val) {
    clearInterval(fallbackTimer); fallbackTimer = null
    const pairCodes = pairs.value.map(p => p.pair_code)
    if (pairCodes.length) wsSend({ type: 'subscribe', pairs: pairCodes })
  } else if (!fallbackTimer) {
    fallbackTimer = setInterval(pollSpread, 5000)
  }
})

// ── Computed ──
const sortedLivePairs = computed(() => {
  return pairs.value.map(p => {
    const live = liveData.value[p.pair_code] || {}
    return { pair_code: p.pair_code, forwardEntry: live.forwardEntry ?? null, reverseEntry: live.reverseEntry ?? null, hasData: !!live.hasData }
  }).sort((a, b) => {
    // Pairs with data first, then by max absolute spread desc
    if (a.hasData && !b.hasData) return -1
    if (!a.hasData && b.hasData) return 1
    const maxA = Math.max(Math.abs(a.forwardEntry || 0), Math.abs(a.reverseEntry || 0))
    const maxB = Math.max(Math.abs(b.forwardEntry || 0), Math.abs(b.reverseEntry || 0))
    return maxB - maxA
  })
})

const dataSource = computed(() => wsChartData.value.length > 0 && !historyData.value.length ? 'WS实时' : '历史查询')

// Merge WS live + history data for table
const allRecords = computed(() => {
  // If history loaded, show history; otherwise show WS rolling data
  const source = historyData.value.length ? historyData.value : wsChartData.value.map((d, i) => ({
    id: 'ws-' + i, time: d.time, cexBid: (liveData.value[activePair.value]?.binanceBid || 0).toFixed(2),
    mt5Ask: (liveData.value[activePair.value]?.bybitAsk || 0).toFixed(2),
    fwdSpread: d.fwd.toFixed(4), revSpread: d.rev.toFixed(4),
    dir: Math.abs(d.fwd) >= Math.abs(d.rev) ? 'forward' : 'reverse',
    pct: ((Math.max(Math.abs(d.fwd), Math.abs(d.rev)) / Math.max(liveData.value[activePair.value]?.binanceBid || 1, 1)) * 100).toFixed(4),
    isOpp: Math.max(Math.abs(d.fwd), Math.abs(d.rev)) >= oppThreshold.value,
  })).reverse()
  return source
})

const filteredRecords = computed(() => {
  if (activeDir.value === 'all') return allRecords.value
  return allRecords.value.filter(r => r.dir === activeDir.value)
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredRecords.value.length / pageSize)))
const pagedRecords = computed(() => {
  const p = Math.min(currentPage.value, totalPages.value)
  return filteredRecords.value.slice((p - 1) * pageSize, p * pageSize)
})

// ── Quant Stats ──
const statCards = computed(() => {
  const rs = allRecords.value
  if (!rs.length) return defaultStats()
  const fwds = rs.map(r => Math.abs(parseFloat(r.fwdSpread || 0)))
  const revs = rs.map(r => Math.abs(parseFloat(r.revSpread || 0)))
  const all = fwds.concat(revs).sort((a, b) => a - b)
  const opps = rs.filter(r => r.isOpp).length

  // P50, P90
  const p50 = percentile(all, 50)
  const p90 = percentile(all, 90)

  // Volatility (std dev)
  const mean = all.reduce((s, v) => s + v, 0) / all.length
  const variance = all.reduce((s, v) => s + (v - mean) ** 2, 0) / all.length
  const stddev = Math.sqrt(variance)

  // Opportunity frequency (per hour) — estimate from data range
  let freqStr = '--'
  if (rs.length >= 2) {
    const first = rs[rs.length - 1]
    const last = rs[0]
    // rough time span from first/last record
    const hours = Math.max(rs.length * 0.5 / 3600, 0.01) // WS: ~2 per sec, History: varies
    if (historyData.value.length) {
      // Use actual time span from history
      const rangeMap = { '15m': 0.25, '1h': 1, '6h': 6, '1d': 24, '7d': 168 }
      const h = rangeMap[activeRange.value] || 1
      freqStr = (opps / h).toFixed(1)
    } else {
      const mins = wsChartData.value.length * 0.5 / 60 // ~500ms per tick
      freqStr = mins > 0 ? (opps / (mins / 60)).toFixed(1) : '--'
    }
  }

  return [
    { label: '记录数', value: rs.length, color: 'text-text-primary' },
    { label: '机会次数', value: opps, color: 'text-[#0ecb81]', sub: freqStr + ' 次/h' },
    { label: 'P50 点差', value: p50.toFixed(4), color: 'text-text-secondary' },
    { label: 'P90 点差', value: p90.toFixed(4), color: 'text-primary' },
    { label: '波动率 (σ)', value: stddev.toFixed(4), color: 'text-[#f0b90b]' },
    { label: '最大点差', value: Math.max(...all).toFixed(4), color: 'text-[#0ecb81]' },
  ]
})

function defaultStats() {
  return [
    { label: '记录数', value: '0', color: 'text-text-primary' },
    { label: '机会次数', value: '0', color: 'text-[#0ecb81]' },
    { label: 'P50 点差', value: '--', color: 'text-text-secondary' },
    { label: 'P90 点差', value: '--', color: 'text-primary' },
    { label: '波动率 (σ)', value: '--', color: 'text-[#f0b90b]' },
    { label: '最大点差', value: '--', color: 'text-[#0ecb81]' },
  ]
}

function percentile(sorted, p) {
  if (!sorted.length) return 0
  const i = (p / 100) * (sorted.length - 1)
  const lo = Math.floor(i), hi = Math.ceil(i)
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo)
}

// ── Chart ──
const chartData = computed(() => {
  const source = wsChartData.value.length ? wsChartData.value : []
  return {
    labels: source.map(d => d.time),
    datasets: [
      { label: '正套开仓', data: source.map(d => d.fwd), borderColor: '#0ecb81', backgroundColor: 'rgba(14,203,129,0.06)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
      { label: '反套开仓', data: source.map(d => d.rev), borderColor: '#f0b90b', backgroundColor: 'rgba(240,185,11,0.06)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    ]
  }
})

const chartOptions = {
  responsive: true, maintainAspectRatio: false, animation: false,
  plugins: {
    legend: { display: false },
    tooltip: { mode: 'index', intersect: false, backgroundColor: 'rgba(0,0,0,0.85)' },
    annotation: undefined,
  },
  scales: {
    x: { display: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', maxTicksLimit: 10, font: { size: 10 } } },
    y: { display: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } }
  }
}

// ── Data fetch ──
async function loadPairs() {
  try {
    const r = await api.get('/api/v1/hedging/pairs')
    pairs.value = (Array.isArray(r.data) ? r.data : []).filter(p => p.is_active)
    if (pairs.value.length && !pairs.value.find(p => p.pair_code === activePair.value)) {
      activePair.value = pairs.value[0].pair_code
    }
  } catch { pairs.value = [{ pair_code: 'XAU', is_active: true }] }
}

function selectPair(pc) {
  activePair.value = pc
  wsChartData.value = []
  historyData.value = []
  currentPage.value = 1
  chartKey.value++
}

function setRange(val) {
  activeRange.value = val
  currentPage.value = 1
  const map = { '15m': 15, '1h': 60, '6h': 360, '1d': 1440, '7d': 10080 }
  startTime.value = dayjs().subtract(map[val], 'minute').format('YYYY-MM-DDTHH:mm')
  endTime.value = dayjs().format('YYYY-MM-DDTHH:mm')
  fetchHistory()
}

async function fetchHistory() {
  histLoading.value = true
  currentPage.value = 1
  const pairConfig = pairs.value.find(p => p.pair_code === activePair.value)
  const binSymbol = pairConfig?.symbol_a?.symbol || pairConfig?.cex_symbol || 'XAUUSDT'
  try {
    const r = await api.get('/api/v1/market/spread/history', {
      params: { limit: limit.value, binance_symbol: binSymbol, bybit_symbol: binSymbol, start_time: startTime.value + ':00', end_time: endTime.value + ':00' }
    })
    const raw = Array.isArray(r.data) ? r.data : r.data?.data ?? r.data?.records ?? []
    historyData.value = raw.map((item, i) => {
      const cexBid = item.binance_quote?.bid ?? item.binance_bid ?? 0
      const mt5Ask = item.bybit_quote?.ask ?? item.bybit_ask ?? 0
      const fwd = item.forward_spread ?? (cexBid - mt5Ask)
      const rev = item.reverse_spread ?? (mt5Ask - cexBid)
      const dir = Math.abs(fwd) >= Math.abs(rev) ? 'forward' : 'reverse'
      return {
        id: i, time: dayjs(item.timestamp ?? item.created_at).format('MM-DD HH:mm:ss'),
        cexBid: cexBid.toFixed(2), mt5Ask: mt5Ask.toFixed(2),
        fwdSpread: fwd.toFixed(4), revSpread: rev.toFixed(4), dir,
        pct: cexBid > 0 ? ((Math.max(Math.abs(fwd), Math.abs(rev)) / cexBid) * 100).toFixed(4) : '0',
        isOpp: Math.max(Math.abs(fwd), Math.abs(rev)) >= oppThreshold.value,
      }
    })
    // Also populate chart from history
    wsChartData.value = raw.map(item => ({
      time: dayjs(item.timestamp ?? item.created_at).format('HH:mm:ss'),
      fwd: item.forward_spread ?? 0, rev: item.reverse_spread ?? 0,
    }))
    chartKey.value++
  } catch { historyData.value = [] }
  finally { histLoading.value = false }
}

async function pollSpread() {
  try {
    const r = await api.get('/api/v1/market/spread', { params: { pair_code: activePair.value } })
    const d = r.data
    if (d) {
      liveData.value[activePair.value] = {
        forwardEntry: d.forward_entry_spread ?? 0, reverseEntry: d.reverse_entry_spread ?? 0,
        binanceBid: d.binance_quote?.bid_price ?? 0, bybitAsk: d.bybit_quote?.ask_price ?? 0,
        ts: d.timestamp, hasData: true,
      }
    }
  } catch {}
}

// ── Helpers ──
function fmtSpread(v) { return v != null ? v.toFixed(2) : '--' }
function spreadColor(v) {
  if (v == null) return 'text-text-tertiary'
  if (Math.abs(v) >= oppThreshold.value) return v >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'
  return 'text-text-secondary'
}

// ── Lifecycle ──
onMounted(async () => {
  await loadPairs()
  wsConnect()
  // Subscribe after short delay to ensure WS is connected
  setTimeout(() => {
    if (wsConnected.value) {
      wsSend({ type: 'subscribe', pairs: pairs.value.map(p => p.pair_code) })
    }
  }, 1000)
})

onUnmounted(() => {
  wsDisconnect()
  clearInterval(fallbackTimer)
})
</script>
