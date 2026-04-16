<template>
  <div class="container mx-auto px-4 py-6 space-y-5">

    <!-- 页头 -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h1 class="text-2xl font-bold">点差记录分析</h1>
        <p class="text-xs text-text-tertiary mt-0.5">实时点差数据 · XAUUSDT / Binance-MT5 · Go 后端</p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <!-- 时间段快选 -->
        <div class="flex gap-1">
          <button v-for="r in timeRanges" :key="r.val"
            @click="setRange(r.val)"
            :class="['px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border',
              activeRange === r.val
                ? 'bg-primary text-dark-300 border-primary'
                : 'bg-dark-100 text-text-secondary border-border-primary hover:border-border-focus']">
            {{ r.label }}
          </button>
        </div>
        <!-- 自定义时间 -->
        <input type="datetime-local" v-model="startTime"
          class="px-2 py-1.5 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary" />
        <span class="text-text-tertiary text-xs">至</span>
        <input type="datetime-local" v-model="endTime"
          class="px-2 py-1.5 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary" />
        <!-- 记录数 -->
        <select v-model="limit"
          class="px-2 py-1.5 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary">
          <option v-for="n in [100,300,500,1000]" :key="n" :value="n">{{ n }} 条</option>
        </select>
        <button @click="fetchData" :disabled="loading"
          class="px-4 py-1.5 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-lg text-sm transition-colors flex items-center gap-1.5">
          <svg v-if="loading" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
          {{ loading ? '查询中' : '查询' }}
        </button>
        <!-- 自动刷新 -->
        <label class="flex items-center gap-1.5 cursor-pointer text-xs text-text-secondary">
          <div @click="toggleAutoRefresh"
            :class="['relative w-9 h-5 rounded-full transition-colors cursor-pointer', autoRefresh ? 'bg-primary' : 'bg-gray-600']">
            <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', autoRefresh ? 'translate-x-4' : 'translate-x-0.5']"/>
          </div>
          自动刷新
        </label>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
      <div v-for="c in statCards" :key="c.label" class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
        <div class="text-xs text-text-tertiary mb-1">{{ c.label }}</div>
        <div class="text-lg font-bold font-mono" :class="c.color">{{ c.value }}</div>
      </div>
    </div>

    <!-- 方向筛选 + 阈值 -->
    <div class="flex items-center gap-3 flex-wrap">
      <span class="text-xs text-text-tertiary">方向筛选：</span>
      <button v-for="d in directions" :key="d.val"
        @click="activeDir = d.val"
        :class="['px-3 py-1 rounded-lg text-xs font-medium transition-colors border',
          activeDir === d.val ? 'bg-primary/20 text-primary border-primary' : 'bg-dark-100 text-text-secondary border-border-primary hover:border-border-focus']">
        {{ d.label }}
      </button>
      <span class="text-xs text-text-tertiary ml-4">机会阈值：</span>
      <input type="number" v-model.number="oppThreshold" step="0.1" min="0"
        class="w-20 px-2 py-1 bg-dark-100 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary text-center" />
      <span class="text-xs text-text-tertiary">USDT</span>
    </div>

    <!-- 图表 -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-bold">点差趋势（正套 / 反套）</div>
        <div class="flex items-center gap-3 text-xs">
          <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#0ecb81] inline-block"></span>正套点差</span>
          <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#f0b90b] inline-block"></span>反套点差</span>
          <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#f6465d] border-dashed inline-block"></span>阈值 {{ oppThreshold }}</span>
        </div>
      </div>
      <div class="h-56">
        <Line :data="chartData" :options="chartOptions" v-if="chartData.labels.length" />
        <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">暂无数据</div>
      </div>
    </div>

    <!-- 数据表格 -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary overflow-hidden">
      <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
        <span class="font-semibold text-sm">点差记录明细</span>
        <div class="flex items-center gap-3 text-xs text-text-tertiary">
          <span>共 {{ filteredRecords.length }} 条</span>
          <span>当前第 {{ currentPage }}/{{ totalPages }} 页</span>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b border-border-secondary text-text-tertiary">
              <th class="text-left px-4 py-2.5">时间</th>
              <th class="text-right px-3 py-2.5">Binance Bid</th>
              <th class="text-right px-3 py-2.5">MT5 Ask</th>
              <th class="text-right px-3 py-2.5">正套点差</th>
              <th class="text-right px-3 py-2.5">反套点差</th>
              <th class="text-center px-3 py-2.5">方向</th>
              <th class="text-right px-3 py-2.5">利润率</th>
              <th class="text-center px-4 py-2.5">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="8" class="text-center py-10 text-text-tertiary">加载中...</td>
            </tr>
            <tr v-else-if="!pagedRecords.length">
              <td colspan="8" class="text-center py-10 text-text-tertiary">暂无数据</td>
            </tr>
            <tr v-for="row in pagedRecords" :key="row.id"
              class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
              <td class="px-4 py-2 font-mono text-text-tertiary whitespace-nowrap">{{ row.time }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ row.binanceBid }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ row.mt5Ask }}</td>
              <td class="px-3 py-2 text-right font-mono font-semibold"
                :class="row.forwardSpread >= oppThreshold ? 'text-[#0ecb81]' : row.forwardSpread <= -oppThreshold ? 'text-[#f6465d]' : 'text-text-secondary'">
                {{ row.forwardSpread }}
              </td>
              <td class="px-3 py-2 text-right font-mono font-semibold"
                :class="row.reverseSpread >= oppThreshold ? 'text-[#f0b90b]' : row.reverseSpread <= -oppThreshold ? 'text-[#f6465d]' : 'text-text-secondary'">
                {{ row.reverseSpread }}
              </td>
              <td class="px-3 py-2 text-center">
                <span :class="row.direction === 'forward'
                  ? 'text-[#0ecb81] bg-[#0ecb81]/10 px-1.5 py-0.5 rounded text-xs'
                  : 'text-[#f0b90b] bg-[#f0b90b]/10 px-1.5 py-0.5 rounded text-xs'">
                  {{ row.direction === 'forward' ? '正套' : '反套' }}
                </span>
              </td>
              <td class="px-3 py-2 text-right font-mono"
                :class="row.profitPct > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary'">
                {{ row.profitPct }}%
              </td>
              <td class="px-4 py-2 text-center">
                <span v-if="row.isOpp" class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/20 text-[#0ecb81]">机会</span>
                <span v-else class="px-1.5 py-0.5 rounded text-xs bg-dark-200 text-text-tertiary">正常</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- 分页 -->
      <div v-if="totalPages > 1" class="px-4 py-3 border-t border-border-secondary flex items-center justify-between">
        <span class="text-xs text-text-tertiary">
          显示 {{ (currentPage-1)*pageSize+1 }}–{{ Math.min(currentPage*pageSize, filteredRecords.length) }}，共 {{ filteredRecords.length }} 条
        </span>
        <div class="flex gap-1">
          <button @click="currentPage=1" :disabled="currentPage===1"
            class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40 hover:bg-dark-50 transition-colors">«</button>
          <button @click="currentPage--" :disabled="currentPage===1"
            class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40 hover:bg-dark-50 transition-colors">‹</button>
          <span class="px-3 py-1 text-xs bg-dark-50 rounded font-mono">{{ currentPage }}/{{ totalPages }}</span>
          <button @click="currentPage++" :disabled="currentPage===totalPages"
            class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40 hover:bg-dark-50 transition-colors">›</button>
          <button @click="currentPage=totalPages" :disabled="currentPage===totalPages"
            class="px-2 py-1 text-xs bg-dark-200 rounded disabled:opacity-40 hover:bg-dark-50 transition-colors">»</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement,
  LineElement, Tooltip, Legend, Filler
} from 'chart.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

// ── 状态 ──────────────────────────────────────────────────────
const loading    = ref(false)
const rawData    = ref([])
const activeRange = ref('1h')
const activeDir  = ref('all')
const limit      = ref(300)
const oppThreshold = ref(2.0)
const autoRefresh = ref(false)
const startTime  = ref(dayjs().subtract(1, 'hour').format('YYYY-MM-DDTHH:mm'))
const endTime    = ref(dayjs().format('YYYY-MM-DDTHH:mm'))
const currentPage = ref(1)
const pageSize   = 50
let autoTimer    = null

const timeRanges = [
  { label: '15分钟', val: '15m' },
  { label: '1小时',  val: '1h' },
  { label: '6小时',  val: '6h' },
  { label: '1天',    val: '1d' },
  { label: '7天',    val: '7d' },
]
const directions = [
  { label: '全部', val: 'all' },
  { label: '正套', val: 'forward' },
  { label: '反套', val: 'reverse' },
]

// ── 数据转换 ──────────────────────────────────────────────────
const records = computed(() => rawData.value.map((item, i) => {
  const binanceBid = item.binance_quote?.bid ?? item.binance_quote?.bid_price ?? item.binance_bid ?? 0
  const mt5Ask     = item.bybit_quote?.ask  ?? item.bybit_quote?.ask_price  ?? item.mt5_ask    ?? 0
  const fwdSpread  = item.forward_spread  ?? (binanceBid - mt5Ask)
  const revSpread  = item.reverse_spread  ?? (mt5Ask - binanceBid)
  const absMax     = Math.abs(fwdSpread) > Math.abs(revSpread) ? fwdSpread : revSpread
  const direction  = Math.abs(fwdSpread) >= Math.abs(revSpread) ? 'forward' : 'reverse'
  const profitPct  = binanceBid > 0 ? ((Math.abs(absMax) / binanceBid) * 100).toFixed(4) : '0.0000'
  return {
    id: i,
    time:         dayjs(item.timestamp ?? item.created_at).format('MM-DD HH:mm:ss'),
    binanceBid:   binanceBid.toFixed(2),
    mt5Ask:       mt5Ask.toFixed(2),
    forwardSpread: fwdSpread.toFixed(4),
    reverseSpread: revSpread.toFixed(4),
    direction,
    profitPct,
    isOpp:        Math.max(Math.abs(fwdSpread), Math.abs(revSpread)) >= oppThreshold.value,
    _fwd: fwdSpread,
    _rev: revSpread,
    _ts:  item.timestamp ?? item.created_at,
  }
}))

const filteredRecords = computed(() => {
  if (activeDir.value === 'all') return records.value
  return records.value.filter(r => r.direction === activeDir.value)
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredRecords.value.length / pageSize)))

const pagedRecords = computed(() => {
  const p = Math.min(currentPage.value, totalPages.value)
  return filteredRecords.value.slice((p - 1) * pageSize, p * pageSize)
})

// ── 统计 ──────────────────────────────────────────────────────
const statCards = computed(() => {
  const rs = filteredRecords.value
  if (!rs.length) return [
    { label: '记录总数', value: '0',    color: 'text-text-primary' },
    { label: '机会次数', value: '0',    color: 'text-[#0ecb81]'   },
    { label: '最大正套', value: '--',   color: 'text-[#0ecb81]'   },
    { label: '最大反套', value: '--',   color: 'text-[#f0b90b]'   },
    { label: '平均点差', value: '--',   color: 'text-primary'      },
  ]
  const fwds = rs.map(r => parseFloat(r.forwardSpread))
  const revs = rs.map(r => parseFloat(r.reverseSpread))
  const avg  = (fwds.concat(revs).reduce((a, b) => a + Math.abs(b), 0) / (fwds.length + revs.length))
  return [
    { label: '记录总数', value: rs.length,                       color: 'text-text-primary' },
    { label: '机会次数', value: rs.filter(r => r.isOpp).length,  color: 'text-[#0ecb81]'   },
    { label: '最大正套', value: Math.max(...fwds).toFixed(4),    color: 'text-[#0ecb81]'   },
    { label: '最大反套', value: Math.max(...revs).toFixed(4),    color: 'text-[#f0b90b]'   },
    { label: '平均点差', value: avg.toFixed(4),                  color: 'text-primary'      },
  ]
})

// ── 图表 ──────────────────────────────────────────────────────
const chartData = computed(() => {
  const sample = filteredRecords.value.slice(0, 300)
  const labels = sample.map(r => r.time.slice(6))   // HH:mm:ss
  return {
    labels,
    datasets: [
      { label: '正套点差', data: sample.map(r => parseFloat(r.forwardSpread)),
        borderColor: '#0ecb81', backgroundColor: 'rgba(14,203,129,0.06)',
        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
      { label: '反套点差', data: sample.map(r => parseFloat(r.reverseSpread)),
        borderColor: '#f0b90b', backgroundColor: 'rgba(240,185,11,0.06)',
        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    ]
  }
})

const chartOptions = {
  responsive: true, maintainAspectRatio: false, animation: false,
  plugins: {
    legend: { display: false },
    tooltip: { mode: 'index', intersect: false,
      backgroundColor: 'rgba(0,0,0,0.85)', borderWidth: 1 },
  },
  scales: {
    x: { display: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', maxTicksLimit: 10, font: { size: 10 } } },
    y: { display: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } }
  }
}

// ── 数据获取 ──────────────────────────────────────────────────
function setRange(val) {
  activeRange.value = val
  currentPage.value = 1
  const map = { '15m': 15, '1h': 60, '6h': 360, '1d': 1440, '7d': 10080 }
  startTime.value = dayjs().subtract(map[val], 'minute').format('YYYY-MM-DDTHH:mm')
  endTime.value   = dayjs().format('YYYY-MM-DDTHH:mm')
  fetchData()
}

async function fetchData() {
  loading.value = true
  currentPage.value = 1
  try {
    // 主接口
    const r = await api.get('/api/v1/market/spread/history', {
      params: {
        limit: limit.value,
        binance_symbol: 'XAUUSDT',
        bybit_symbol:   'XAUUSDT',
        start_time: startTime.value + ':00',
        end_time:   endTime.value   + ':00',
      }
    })
    rawData.value = Array.isArray(r.data) ? r.data : r.data?.data ?? r.data?.records ?? []
  } catch {
    // 备用接口
    try {
      const r2 = await api.get('/api/v1/spreads/records', {
        params: { limit: limit.value, start_time: startTime.value + ':00', end_time: endTime.value + ':00' }
      })
      rawData.value = Array.isArray(r2.data) ? r2.data : r2.data?.records ?? []
    } catch { rawData.value = [] }
  } finally { loading.value = false }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    autoTimer = setInterval(() => { setRange(activeRange.value) }, 10000)
  } else {
    clearInterval(autoTimer)
  }
}

onMounted(() => { setRange('1h') })
onUnmounted(() => { clearInterval(autoTimer) })
</script>
