<template>
  <div class="pb-20 md:pb-6">
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <span class="font-semibold">HustleXAU · 周收益</span>
      <button @click="$router.push('/')" class="text-sm text-text-tertiary hover:text-text-primary">返回总览</button>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3"><span class="font-semibold text-sm">周收益分析</span></div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-5xl mx-auto space-y-4">

      <!-- KPI -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">本周收益</div>
          <div class="text-lg font-bold font-mono" :class="pnlColor(thisWeekPnl)">{{ fmtPnl(thisWeekPnl) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">本月累计</div>
          <div class="text-lg font-bold font-mono" :class="pnlColor(thisMonthPnl)">{{ fmtPnl(thisMonthPnl) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">本年累计</div>
          <div class="text-lg font-bold font-mono" :class="pnlColor(summary.cumulative_pnl)">{{ fmtPnl(summary.cumulative_pnl) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary">最大回撤</div>
          <div class="text-lg font-bold font-mono text-[#f6465d]">{{ summary.max_drawdown_pct != null ? summary.max_drawdown_pct.toFixed(2) + '%' : '--' }}</div>
        </div>
      </div>

      <!-- Main: Weekly bar + cumulative line -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <span class="text-sm font-bold mb-2 block">周收益柱状图（叠加累计收益折线）</span>
        <div class="h-56 md:h-64">
          <Bar v-if="comboChart.labels.length" :data="comboChart" :options="comboOpts" :key="ck" />
          <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">{{ loading ? '加载中...' : '暂无数据' }}</div>
        </div>
      </div>

      <!-- Heatmap -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <span class="text-sm font-bold mb-3 block">周收益热力图</span>
        <div class="flex flex-wrap gap-1.5">
          <div v-for="w in weeklyData" :key="w.week" :title="w.week + ': ' + fmtPnl(w.net_pnl)"
            class="w-8 h-8 rounded flex items-center justify-center text-[9px] font-mono cursor-default"
            :class="heatColor(w.net_pnl)">
            {{ w.net_pnl >= 0 ? '+' : '' }}{{ w.net_pnl.toFixed(0) }}
          </div>
        </div>
        <div class="flex items-center gap-3 mt-3 text-[10px] text-text-tertiary">
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-[#0ecb81]"></span> >1%</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-[#0ecb81]/40"></span> 0~1%</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-[#f6465d]/40"></span> -0.5~0%</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-[#f6465d]"></span> &lt;-0.5%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Bar } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip } from 'chart.js'
import { fetchDailyPnl, aggregateWeekly, fmtPnl, pnlColor } from '@/utils/pnlUtils.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip)

const loading = ref(true)
const dailyList = ref([])
const weeklyData = ref([])
const summary = ref({})
const ck = ref(0)

const thisWeekPnl = computed(() => {
  const ws = dayjs().startOf('week').format('YYYY-MM-DD')
  return dailyList.value.filter(d => d.date >= ws).reduce((s, d) => s + d.net_pnl, 0)
})
const thisMonthPnl = computed(() => {
  const ms = dayjs().startOf('month').format('YYYY-MM-DD')
  return dailyList.value.filter(d => d.date >= ms).reduce((s, d) => s + d.net_pnl, 0)
})

const comboChart = computed(() => {
  const w = weeklyData.value
  if (!w.length) return { labels: [], datasets: [] }
  let cum = 0
  const cumArr = w.map(x => { cum += x.net_pnl; return +cum.toFixed(2) })
  return {
    labels: w.map(x => x.week.substring(5)),
    datasets: [
      { type: 'bar', label: '周收益', data: w.map(x => +x.net_pnl.toFixed(2)), backgroundColor: w.map(x => x.net_pnl >= 0 ? 'rgba(14,203,129,0.7)' : 'rgba(246,70,93,0.7)'), borderRadius: 3, order: 2 },
      { type: 'line', label: '累计收益', data: cumArr, borderColor: '#f0b90b', backgroundColor: 'transparent', tension: 0.3, pointRadius: 2, pointBackgroundColor: '#f0b90b', borderWidth: 2, order: 1 },
    ]
  }
})

const comboOpts = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: 'rgba(0,0,0,0.85)' } }, scales: { x: { grid: { display: false }, ticks: { color: '#666', font: { size: 9 } } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } } } }

function heatColor(v) {
  if (v > 0) return v > 10 ? 'bg-[#0ecb81] text-dark-300' : 'bg-[#0ecb81]/40 text-[#0ecb81]'
  if (v < -5) return 'bg-[#f6465d] text-white'
  if (v < 0) return 'bg-[#f6465d]/40 text-[#f6465d]'
  return 'bg-dark-200 text-text-tertiary'
}

onMounted(async () => {
  loading.value = true
  try {
    const start = dayjs().subtract(365, 'day').format('YYYY-MM-DD')
    const end = dayjs().format('YYYY-MM-DD')
    const data = await fetchDailyPnl(start, end)
    dailyList.value = data.daily_pnl || []
    summary.value = data.summary || {}
    weeklyData.value = aggregateWeekly(dailyList.value)
    ck.value++
  } catch {} finally { loading.value = false }
})
</script>
