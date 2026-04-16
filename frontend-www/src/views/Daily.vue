<template>
  <div class="pb-20 md:pb-6">
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <span class="font-semibold">HustleXAU · 日收益</span>
      <button @click="$router.push('/')" class="text-sm text-text-tertiary hover:text-text-primary">返回总览</button>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3"><span class="font-semibold text-sm">日收益分析</span></div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-5xl mx-auto space-y-4">

      <!-- Range selector -->
      <div class="flex items-center gap-2 flex-wrap">
        <button v-for="r in ranges" :key="r.val" @click="setRange(r.val)"
          :class="['px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors',
            activeRange===r.val ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-100 text-text-secondary border-border-primary']">
          {{ r.label }}
        </button>
      </div>

      <!-- KPI -->
      <div class="grid grid-cols-3 md:grid-cols-6 gap-2">
        <div v-for="k in kpis" :key="k.label" class="bg-dark-100 rounded-xl border border-border-primary p-2.5">
          <div class="text-[10px] text-text-tertiary">{{ k.label }}</div>
          <div class="text-sm font-bold font-mono" :class="k.color">{{ k.value }}</div>
        </div>
      </div>

      <!-- Main: Cumulative curve with drawdown shadow -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm font-bold">累计收益曲线（带回撤阴影）</span>
          <div class="flex items-center gap-3 text-xs">
            <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#0ecb81] inline-block"></span>累计收益</span>
            <span class="flex items-center gap-1"><span class="w-3 h-0.5 bg-[#f6465d] inline-block opacity-50"></span>回撤</span>
          </div>
        </div>
        <div class="h-56 md:h-64">
          <Line v-if="cumChart.labels.length" :data="cumChart" :options="lineOpts" :key="ck" />
          <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">{{ loading ? '加载中...' : '暂无数据' }}</div>
        </div>
      </div>

      <!-- Sub charts row -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Daily bar chart -->
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
          <span class="text-sm font-bold mb-2 block">每日收益</span>
          <div class="h-44">
            <Bar v-if="barChart.labels.length" :data="barChart" :options="barOpts" :key="ck+1" />
            <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">暂无数据</div>
          </div>
        </div>
        <!-- Distribution histogram -->
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
          <span class="text-sm font-bold mb-2 block">日收益分布</span>
          <div class="h-44">
            <Bar v-if="distChart.labels.length" :data="distChart" :options="distOpts" :key="ck+2" />
            <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">暂无数据</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Line, Bar } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Filler } from 'chart.js'
import { fetchDailyPnl, fmtPnl, pnlColor } from '@/utils/pnlUtils.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Filler)

const loading = ref(true)
const dailyList = ref([])
const summary = ref({})
const activeRange = ref('30d')
const ck = ref(0)

const ranges = [
  { label: '7天', val: '7d' }, { label: '30天', val: '30d' },
  { label: '90天', val: '90d' }, { label: '180天', val: '180d' },
]

const kpis = computed(() => {
  const s = summary.value
  return [
    { label: '累计收益', value: fmtPnl(s.cumulative_pnl), color: pnlColor(s.cumulative_pnl) },
    { label: '今日收益', value: fmtPnl(todayPnl.value), color: pnlColor(todayPnl.value) },
    { label: '最大回撤', value: s.max_drawdown_pct != null ? s.max_drawdown_pct.toFixed(2) + '%' : '--', color: 'text-[#f6465d]' },
    { label: '胜率', value: s.win_rate != null ? (s.win_rate * 100).toFixed(1) + '%' : '--', color: '' },
    { label: '盈亏比', value: s.profit_factor ?? '--', color: '' },
    { label: '夏普比率', value: s.sharpe_ratio ?? '--', color: 'text-primary' },
  ]
})

const todayPnl = computed(() => {
  const d = dailyList.value.find(x => x.date === dayjs().format('YYYY-MM-DD'))
  return d ? d.net_pnl : 0
})

// Cumulative + drawdown chart
const cumChart = computed(() => {
  const list = dailyList.value
  if (!list.length) return { labels: [], datasets: [] }
  let cum = 0, peak = 0
  const cumArr = [], ddArr = []
  for (const d of list) { cum += d.net_pnl; cumArr.push(+cum.toFixed(2)); peak = Math.max(peak, cum); ddArr.push(+(cum - peak).toFixed(2)) }
  return {
    labels: list.map(d => d.date.substring(5)),
    datasets: [
      { label: '累计收益', data: cumArr, borderColor: '#0ecb81', backgroundColor: 'rgba(14,203,129,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: '回撤', data: ddArr, borderColor: '#f6465d', backgroundColor: 'rgba(246,70,93,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1, borderDash: [4, 4] },
    ]
  }
})

// Daily bar chart
const barChart = computed(() => {
  const list = dailyList.value
  if (!list.length) return { labels: [], datasets: [] }
  return {
    labels: list.map(d => d.date.substring(5)),
    datasets: [{
      label: '日收益', data: list.map(d => +d.net_pnl.toFixed(2)),
      backgroundColor: list.map(d => d.net_pnl >= 0 ? 'rgba(14,203,129,0.7)' : 'rgba(246,70,93,0.7)'),
      borderRadius: 2,
    }]
  }
})

// Distribution histogram
const distChart = computed(() => {
  const pnls = dailyList.value.map(d => d.net_pnl).filter(v => v !== 0)
  if (!pnls.length) return { labels: [], datasets: [] }
  const min = Math.min(...pnls), max = Math.max(...pnls)
  const binCount = Math.min(20, Math.max(5, Math.ceil(Math.sqrt(pnls.length))))
  const binSize = (max - min) / binCount || 1
  const bins = Array(binCount).fill(0)
  const labels = []
  for (let i = 0; i < binCount; i++) {
    const lo = min + i * binSize
    labels.push(lo.toFixed(1))
  }
  for (const p of pnls) {
    const idx = Math.min(Math.floor((p - min) / binSize), binCount - 1)
    bins[idx]++
  }
  return {
    labels,
    datasets: [{
      label: '频次', data: bins,
      backgroundColor: labels.map(l => parseFloat(l) >= 0 ? 'rgba(14,203,129,0.6)' : 'rgba(246,70,93,0.6)'),
      borderRadius: 2,
    }]
  }
})

const lineOpts = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: 'rgba(0,0,0,0.85)' } }, scales: { x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', maxTicksLimit: 8, font: { size: 10 } } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } } } }
const barOpts = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(0,0,0,0.85)' } }, scales: { x: { grid: { display: false }, ticks: { color: '#666', maxTicksLimit: 10, font: { size: 9 } } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } } } }
const distOpts = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(0,0,0,0.85)' } }, scales: { x: { grid: { display: false }, ticks: { color: '#666', font: { size: 9 } }, title: { display: true, text: 'USDT', color: '#666', font: { size: 10 } } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } }, title: { display: true, text: '天数', color: '#666', font: { size: 10 } } } } }

async function setRange(val) {
  activeRange.value = val
  loading.value = true
  try {
    const data = await fetchDailyPnl(dayjs().subtract(parseInt(val), 'day').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD'))
    dailyList.value = data.daily_pnl || []; summary.value = data.summary || {}; ck.value++
  } catch {} finally { loading.value = false }
}

onMounted(() => setRange('30d'))
</script>
