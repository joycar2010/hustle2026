<template>
  <div class="pb-20 md:pb-6">
    <!-- Header -->
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 bg-gradient-to-br from-primary to-primary-hover rounded-lg flex items-center justify-center"><span class="text-dark-300 font-bold">H</span></div>
        <span class="font-semibold">HustleXAU · 收益总览</span>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-text-secondary">{{ auth.user?.username }}</span>
        <div class="w-2 h-2 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-red-500'"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
        <button @click="doLogout" class="text-sm text-text-tertiary hover:text-danger transition-colors">退出</button>
      </div>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3 flex items-center justify-between">
      <span class="font-semibold text-sm">收益总览</span>
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-red-500'"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
      </div>
    </div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-5xl mx-auto space-y-5">

      <!-- KPI Dashboard -->
      <div class="grid grid-cols-3 md:grid-cols-6 gap-3">
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary mb-0.5">累计收益</div>
          <div class="text-lg font-bold font-mono" :class="pnlColor(summary.cumulative_pnl)">{{ fmtPnl(summary.cumulative_pnl) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary mb-0.5">今日收益</div>
          <div class="text-lg font-bold font-mono" :class="pnlColor(todayPnl)">{{ fmtPnl(todayPnl) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary mb-0.5">最大回撤</div>
          <div class="text-lg font-bold font-mono text-[#f6465d]">{{ summary.max_drawdown_pct != null ? summary.max_drawdown_pct.toFixed(2) + '%' : '--' }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary mb-0.5">胜率</div>
          <div class="text-lg font-bold font-mono text-text-primary">{{ summary.win_rate != null ? (summary.win_rate * 100).toFixed(1) + '%' : '--' }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary mb-0.5">盈亏比</div>
          <div class="text-lg font-bold font-mono text-text-primary">{{ summary.profit_factor ?? '--' }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
          <div class="text-[10px] text-text-tertiary mb-0.5">夏普比率</div>
          <div class="text-lg font-bold font-mono text-primary">{{ summary.sharpe_ratio ?? '--' }}</div>
        </div>
      </div>

      <!-- Cumulative PnL Curve -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-bold">累计收益曲线</span>
          <div class="flex gap-1">
            <button v-for="r in ranges" :key="r.val" @click="setRange(r.val)"
              :class="['px-2.5 py-1 rounded text-xs border transition-colors',
                activeRange===r.val ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-200 text-text-secondary border-border-primary']">
              {{ r.label }}
            </button>
          </div>
        </div>
        <div class="h-52 md:h-64">
          <Line v-if="chartData.labels.length" :data="chartData" :options="chartOpts" :key="chartKey" />
          <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">{{ loading ? '加载中...' : '暂无数据' }}</div>
        </div>
      </div>

      <!-- Fund Summary (merged, not per-account) -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-bold">账户资金概览</span>
          <span class="text-xs text-text-tertiary">{{ wsConnected ? 'WS实时' : '定时刷新' }}</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div class="bg-dark-200 rounded-xl p-3">
            <div class="text-xs text-text-tertiary mb-1">总资产</div>
            <div class="font-mono font-bold text-text-primary">{{ fmtNum(fundTotals.total_assets) }} U</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3">
            <div class="text-xs text-text-tertiary mb-1">可用资产</div>
            <div class="font-mono font-bold text-text-secondary">{{ fmtNum(fundTotals.available) }} U</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3">
            <div class="text-xs text-text-tertiary mb-1">净资产</div>
            <div class="font-mono font-bold text-text-secondary">{{ fmtNum(fundTotals.net_assets) }} U</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3">
            <div class="text-xs text-text-tertiary mb-1">浮动盈亏</div>
            <div class="font-mono font-bold" :class="pnlColor(fundTotals.unrealized_pnl)">{{ fmtPnl(fundTotals.unrealized_pnl) }} U</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler } from 'chart.js'
import { useAuthStore } from '@/stores/auth.js'
import { useWebSocket } from '@/composables/useWebSocket.js'
import { fetchDailyPnl, fmtPnl, fmtNum, pnlColor } from '@/utils/pnlUtils.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)

const router = useRouter()
const auth = useAuthStore()
const { connected: wsConnected, lastMessage, connect: wsConnect, disconnect: wsDisconnect } = useWebSocket()

const loading = ref(true)
const lastUpdate = ref('--')
const dailyList = ref([])
const summary = ref({})
const fundTotals = ref({ total_assets: 0, available: 0, net_assets: 0, unrealized_pnl: 0 })
const activeRange = ref('90d')
const chartKey = ref(0)
let fallbackTimer = null

const ranges = [
  { label: '30天', val: '30d' }, { label: '90天', val: '90d' },
  { label: '半年', val: '180d' }, { label: '全部', val: '365d' },
]

const todayPnl = computed(() => {
  const today = dayjs().format('YYYY-MM-DD')
  const d = dailyList.value.find(x => x.date === today)
  return d ? d.net_pnl : 0
})

// Chart
const chartData = computed(() => {
  const list = dailyList.value
  if (!list.length) return { labels: [], datasets: [] }
  let cum = 0
  const cumArr = []
  const ddArr = []
  let peak = 0
  for (const d of list) {
    cum += d.net_pnl
    cumArr.push(parseFloat(cum.toFixed(2)))
    peak = Math.max(peak, cum)
    ddArr.push(parseFloat((cum - peak).toFixed(2)))
  }
  return {
    labels: list.map(d => d.date.substring(5)), // MM-DD
    datasets: [
      { label: '累计收益', data: cumArr, borderColor: '#0ecb81', backgroundColor: 'rgba(14,203,129,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: '回撤', data: ddArr, borderColor: '#f6465d', backgroundColor: 'rgba(246,70,93,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1, borderDash: [4, 4] },
    ]
  }
})

const chartOpts = {
  responsive: true, maintainAspectRatio: false, animation: false,
  plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: 'rgba(0,0,0,0.85)' } },
  scales: {
    x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', maxTicksLimit: 8, font: { size: 10 } } },
    y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } }
  }
}

// WS for fund totals
watch(lastMessage, (msg) => {
  if (!msg) return
  if (msg.type === 'account_balance' && msg.data) {
    const s = msg.data.summary || {}
    fundTotals.value = {
      total_assets: s.total_assets || 0,
      available: s.available_balance || 0,
      net_assets: s.net_assets || 0,
      unrealized_pnl: s.unrealized_pnl || 0,
    }
    lastUpdate.value = dayjs().format('HH:mm:ss')
  }
})

watch(wsConnected, (val) => {
  if (val) { clearInterval(fallbackTimer); fallbackTimer = null }
  else if (!fallbackTimer) { fallbackTimer = setInterval(fetchFund, 30000) }
})

async function setRange(val) {
  activeRange.value = val
  const days = parseInt(val)
  const start = dayjs().subtract(days, 'day').format('YYYY-MM-DD')
  const end = dayjs().format('YYYY-MM-DD')
  loading.value = true
  try {
    const data = await fetchDailyPnl(start, end)
    dailyList.value = data.daily_pnl || []
    summary.value = data.summary || {}
    chartKey.value++
  } catch (e) { console.error('PnL fetch error:', e) }
  finally { loading.value = false }
}

async function fetchFund() {
  try {
    const r = await api.get('/api/v1/accounts/dashboard/aggregated')
    const s = r.data?.summary || {}
    fundTotals.value = { total_assets: s.total_assets || 0, available: s.available_balance || 0, net_assets: s.net_assets || 0, unrealized_pnl: s.unrealized_pnl || 0 }
    lastUpdate.value = dayjs().format('HH:mm:ss')
  } catch {}
}

function doLogout() { wsDisconnect(); clearInterval(fallbackTimer); auth.logout(); router.push('/login') }

onMounted(async () => {
  await auth.fetchUser()
  await Promise.all([setRange('90d'), fetchFund()])
  wsConnect()
})
onUnmounted(() => { wsDisconnect(); clearInterval(fallbackTimer) })
</script>
