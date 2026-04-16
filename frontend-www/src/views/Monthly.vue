<template>
  <div class="pb-20 md:pb-6">
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <span class="font-semibold">HustleXAU · 月收益</span>
      <button @click="$router.push('/')" class="text-sm text-text-tertiary hover:text-text-primary">返回总览</button>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3"><span class="font-semibold text-sm">月收益分析</span></div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-5xl mx-auto space-y-4">

      <!-- KPI -->
      <div class="grid grid-cols-2 md:grid-cols-5 gap-2">
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">本年累计</div>
          <div class="text-lg font-bold font-mono" :class="pnlColor(summary.cumulative_pnl)">{{ fmtPnl(summary.cumulative_pnl) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">年化收益率</div>
          <div class="text-lg font-bold font-mono text-primary">{{ annualReturn }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">最大回撤</div>
          <div class="text-lg font-bold font-mono text-[#f6465d]">{{ summary.max_drawdown_pct != null ? summary.max_drawdown_pct.toFixed(2) + '%' : '--' }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">盈利月数</div>
          <div class="text-lg font-bold font-mono text-[#0ecb81]">{{ profitMonths }} / {{ monthlyData.length }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">夏普比率</div>
          <div class="text-lg font-bold font-mono text-primary">{{ summary.sharpe_ratio ?? '--' }}</div>
        </div>
      </div>

      <!-- Waterfall chart -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <span class="text-sm font-bold mb-2 block">月收益瀑布图</span>
        <div class="h-56 md:h-64">
          <Bar v-if="waterfallChart.labels.length" :data="waterfallChart" :options="waterfallOpts" :key="ck" />
          <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">{{ loading ? '加载中...' : '暂无数据' }}</div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Calendar heatmap -->
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
          <span class="text-sm font-bold mb-3 block">全年日收益热力图</span>
          <div class="overflow-x-auto">
            <div class="grid gap-[2px]" style="grid-template-columns: repeat(53, 10px); grid-template-rows: repeat(7, 10px);">
              <div v-for="(d, i) in calendarDays" :key="i"
                :title="d.date + ': ' + (d.pnl != null ? fmtPnl(d.pnl) : '无数据')"
                class="w-[10px] h-[10px] rounded-[2px]"
                :class="calHeatColor(d.pnl)">
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2 mt-2 text-[9px] text-text-tertiary">
            <span>亏损</span>
            <span class="w-2.5 h-2.5 rounded-sm bg-[#f6465d]"></span>
            <span class="w-2.5 h-2.5 rounded-sm bg-[#f6465d]/30"></span>
            <span class="w-2.5 h-2.5 rounded-sm bg-dark-300"></span>
            <span class="w-2.5 h-2.5 rounded-sm bg-[#0ecb81]/30"></span>
            <span class="w-2.5 h-2.5 rounded-sm bg-[#0ecb81]"></span>
            <span>盈利</span>
          </div>
        </div>

        <!-- Rolling annualized return -->
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
          <span class="text-sm font-bold mb-2 block">滚动年化收益率</span>
          <div class="h-44">
            <Line v-if="rollingChart.labels.length" :data="rollingChart" :options="lineOpts" :key="ck+1" />
            <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">需要更多数据</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Bar, Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip, Filler } from 'chart.js'
import { fetchDailyPnl, aggregateMonthly, fmtPnl, pnlColor } from '@/utils/pnlUtils.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip, Filler)

const loading = ref(true)
const dailyList = ref([])
const monthlyData = ref([])
const summary = ref({})
const ck = ref(0)

const profitMonths = computed(() => monthlyData.value.filter(m => m.net_pnl > 0).length)

const annualReturn = computed(() => {
  const days = dailyList.value.length
  if (days < 2 || !summary.value.cumulative_pnl) return '--'
  const totalPnl = summary.value.cumulative_pnl
  // Simple annualization: (cumPnl / days) * 365
  const dailyAvg = totalPnl / days
  return (dailyAvg * 365).toFixed(2) + ' U/yr'
})

// Waterfall chart (floating bars)
const waterfallChart = computed(() => {
  const m = monthlyData.value
  if (!m.length) return { labels: [], datasets: [] }
  const labels = [...m.map(x => x.month.substring(5)), '合计']
  let cum = 0
  const bases = [], tops = [], colors = []
  for (const x of m) {
    const pnl = +x.net_pnl.toFixed(2)
    if (pnl >= 0) { bases.push(cum); tops.push(pnl); colors.push('rgba(14,203,129,0.8)') }
    else { bases.push(cum + pnl); tops.push(-pnl); colors.push('rgba(246,70,93,0.8)') }
    cum += pnl
  }
  // Total bar
  bases.push(0); tops.push(cum); colors.push(cum >= 0 ? 'rgba(59,130,246,0.8)' : 'rgba(246,70,93,0.8)')
  return {
    labels,
    datasets: [
      { label: '基底', data: bases, backgroundColor: 'transparent', borderWidth: 0, barPercentage: 0.6 },
      { label: '月收益', data: tops, backgroundColor: colors, borderRadius: 3, barPercentage: 0.6 },
    ]
  }
})

const waterfallOpts = {
  responsive: true, maintainAspectRatio: false, animation: false,
  plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(0,0,0,0.85)', callbacks: { label: (ctx) => ctx.datasetIndex === 1 ? ctx.raw.toFixed(2) + ' USDT' : '' } } },
  scales: {
    x: { stacked: true, grid: { display: false }, ticks: { color: '#666', font: { size: 10 } } },
    y: { stacked: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } }
  }
}

// Calendar heatmap data (53 weeks x 7 days)
const calendarDays = computed(() => {
  const pnlMap = {}
  for (const d of dailyList.value) pnlMap[d.date] = d.net_pnl
  const days = []
  const yearStart = dayjs().startOf('year')
  const startDay = yearStart.startOf('week') // align to Sunday
  for (let i = 0; i < 53 * 7; i++) {
    const date = startDay.add(i, 'day')
    if (date.isAfter(dayjs())) { days.push({ date: '', pnl: null }); continue }
    const dk = date.format('YYYY-MM-DD')
    days.push({ date: dk, pnl: pnlMap[dk] ?? null })
  }
  return days
})

function calHeatColor(v) {
  if (v == null) return 'bg-dark-300'
  if (v > 10) return 'bg-[#0ecb81]'
  if (v > 0) return 'bg-[#0ecb81]/30'
  if (v > -5) return 'bg-[#f6465d]/30'
  return 'bg-[#f6465d]'
}

// Rolling 30-day annualized return
const rollingChart = computed(() => {
  const list = dailyList.value
  if (list.length < 30) return { labels: [], datasets: [] }
  const window = 30
  const labels = [], vals = []
  for (let i = window; i < list.length; i++) {
    const slice = list.slice(i - window, i)
    const totalPnl = slice.reduce((s, d) => s + d.net_pnl, 0)
    const annualized = (totalPnl / window) * 365
    labels.push(list[i].date.substring(5))
    vals.push(+annualized.toFixed(2))
  }
  return {
    labels,
    datasets: [{ label: '滚动30天年化', data: vals, borderColor: '#f0b90b', backgroundColor: 'rgba(240,185,11,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 }]
  }
})

const lineOpts = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(0,0,0,0.85)' } }, scales: { x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', maxTicksLimit: 8, font: { size: 9 } } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } } } }

onMounted(async () => {
  loading.value = true
  try {
    const start = dayjs().startOf('year').format('YYYY-MM-DD')
    const end = dayjs().format('YYYY-MM-DD')
    const data = await fetchDailyPnl(start, end)
    dailyList.value = data.daily_pnl || []
    summary.value = data.summary || {}
    monthlyData.value = aggregateMonthly(dailyList.value)
    ck.value++
  } catch {} finally { loading.value = false }
})
</script>
