<template>
  <div class="pb-20 md:pb-6">
    <!-- Header -->
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <div class="flex items-center gap-3">
        <img src="/logo.png" alt="HustleXAU" class="w-8 h-8 object-contain" />
        <span class="font-semibold">HustleXAU · 我的收益</span>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-text-secondary">{{ auth.user?.username }}</span>
        <select v-if="viewOptions.length > 1" v-model="activeView" @change="onViewChange"
          class="text-sm bg-dark-200 border border-border-primary rounded px-2 py-1">
          <option v-for="o in viewOptions" :key="o.val" :value="o.val">{{ o.label }}</option>
        </select>
        <div class="w-2 h-2 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-red-500'"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
        <button @click="doLogout" class="text-sm text-text-tertiary hover:text-danger transition-colors">退出</button>
      </div>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-semibold text-sm flex-shrink-0">我的收益</span>
        <span class="text-xs text-text-secondary truncate">{{ auth.user?.username || '--' }}</span>
        <select v-if="viewOptions.length > 1" v-model="activeView" @change="onViewChange"
          class="text-xs bg-dark-200 border border-border-primary rounded px-1.5 py-0.5 flex-shrink-0 max-w-[40vw]">
          <option v-for="o in viewOptions" :key="o.val" :value="o.val">{{ o.label }}</option>
        </select>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-red-500'"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
      </div>
    </div>

    <div v-if="maintenanceActive" class="px-4 py-16 md:px-6 md:py-24 max-w-3xl mx-auto text-center"><div class="text-6xl mb-4">🛠</div><div class="text-xl font-semibold mb-2">系统维护中</div><div class="text-sm text-text-tertiary">{{ maintenanceReason || '统计数据暂不可用' }}</div><div v-if="maintenanceResume" class="text-sm text-text-tertiary mt-1">预计 {{ new Date(maintenanceResume).toLocaleString('zh-CN', { hour12: false }) }} 恢复</div></div><div v-show="!maintenanceActive" class="px-4 py-4 md:px-6 md:py-6 max-w-3xl mx-auto space-y-5">

      <!-- 核心四宫格: 今日 / 本周 / 本月 / 累计 -->
      <div class="grid grid-cols-2 gap-3">
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4 min-w-0">
          <div class="text-xs text-text-tertiary mb-1">今日收益</div>
          <div class="font-bold font-mono leading-tight whitespace-nowrap" :class="[pnlColor(todayPnl), fitFont(todayPnl)]">{{ fmtPnl(todayPnl) }}</div>
          <div class="text-[10px] text-text-tertiary mt-1">USDT</div>
        </div>
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4 min-w-0">
          <div class="text-xs text-text-tertiary mb-1">本周收益</div>
          <div class="font-bold font-mono leading-tight whitespace-nowrap" :class="[pnlColor(thisWeekPnl), fitFont(thisWeekPnl)]">{{ fmtPnl(thisWeekPnl) }}</div>
          <div class="text-[10px] text-text-tertiary mt-1">本周一至今</div>
        </div>
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4 min-w-0">
          <div class="text-xs text-text-tertiary mb-1">本月收益</div>
          <div class="font-bold font-mono leading-tight whitespace-nowrap" :class="[pnlColor(thisMonthPnl), fitFont(thisMonthPnl)]">{{ fmtPnl(thisMonthPnl) }}</div>
          <div class="text-[10px] text-text-tertiary mt-1">本月1日至今</div>
        </div>
        <div class="bg-dark-100 rounded-2xl border border-border-primary p-4 min-w-0">
          <div class="text-xs text-text-tertiary mb-1">累计收益</div>
          <div class="font-bold font-mono leading-tight whitespace-nowrap" :class="[pnlColor(cumulativePnl), fitFont(cumulativePnl)]">{{ cumLoading ? '...' : fmtPnl(cumulativePnl) }}</div>
          <div class="text-[10px] text-text-tertiary mt-1">开户至今<span v-if="cumInception" class="ml-1 text-text-tertiary/80">({{ cumInception }} 起)</span></div>
        </div>
      </div>

      <!-- 收益趋势(日/周/月切换, 不发新请求) -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-bold">收益趋势</span>
          <div class="flex gap-1">
            <button v-for="g in grans" :key="g.val" @click="activeGran = g.val"
              :class="['px-3 py-1 rounded text-xs border transition-colors',
                activeGran===g.val ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-200 text-text-secondary border-border-primary']">
              {{ g.label }}
            </button>
          </div>
        </div>
        <div class="h-56 md:h-64">
          <Bar v-if="chartData.labels.length" :data="chartData" :options="chartOpts" :key="chartKey" />
          <div v-else class="h-full flex items-center justify-center text-text-tertiary text-sm">{{ loading ? '加载中...' : '暂无数据' }}</div>
        </div>
        <!-- 取数范围切换(只影响趋势图与累计的窗口) -->
        <div class="flex items-center justify-end gap-1 mt-3">
          <span class="text-[10px] text-text-tertiary mr-1">范围</span>
          <button v-for="r in ranges" :key="r.val" @click="setRange(r.val)"
            :class="['px-2 py-0.5 rounded text-[11px] border transition-colors',
              activeRange===r.val ? 'bg-primary/10 text-primary border-primary' : 'bg-dark-200 text-text-secondary border-border-primary']">
            {{ r.label }}
          </button>
        </div>
      </div>

      <!-- 账户资金(一行弱化) -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary px-4 py-3">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-bold text-text-secondary">账户资金</span>
          <span class="text-[10px]" :class="wsConnected ? 'text-[#0ecb81]' : 'text-text-tertiary'">{{ wsConnected ? '⚡ 实时' : '📡 轮询' }}</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2 text-sm">
          <div class="flex items-center justify-between gap-1 min-w-0">
            <span class="text-text-tertiary text-xs flex-shrink-0">总资产</span>
            <span class="font-mono font-semibold whitespace-nowrap text-right text-xs">{{ fmtNum(fundTotals.total_assets) }} U</span>
          </div>
          <div class="flex items-center justify-between gap-1 min-w-0">
            <span class="text-text-tertiary text-xs flex-shrink-0">净资产</span>
            <span class="font-mono font-semibold whitespace-nowrap text-right text-xs">{{ fmtNum(fundTotals.net_assets) }} U</span>
          </div>
          <div class="flex items-center justify-between gap-1 min-w-0">
            <span class="text-text-tertiary text-xs flex-shrink-0">浮动盈亏</span>
            <span class="font-mono font-semibold whitespace-nowrap text-right text-xs" :class="pnlColor(fundTotals.unrealized_pnl)">{{ fmtPnl(fundTotals.unrealized_pnl) }} U</span>
          </div>
        </div>
      </div>

      <p class="text-[10px] text-text-tertiary text-center leading-relaxed">
        收益 = 主账号已实现盈亏 + 对冲账号已实现盈亏 + 资金费 − 手续费(已剔除平台间划转/出入金)。
      </p>
    </div>
  </div>
</template>

<script setup>
import { useMaintenance } from '@/composables/useMaintenance.js'
const { maintenanceActive, maintenanceReason, maintenanceResume } = useMaintenance()
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Bar } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip } from 'chart.js'
import { useAuthStore } from '@/stores/auth.js'
import { useWebSocket } from '@/composables/useWebSocket.js'
import { fetchDailyPnl, aggregateWeekly, aggregateMonthly, fmtPnl, fmtNum, pnlColor, setWsInstance, clearPnlCache } from '@/utils/pnlUtils.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
dayjs.extend(utc)
dayjs.extend(timezone)

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

const router = useRouter()
const auth = useAuthStore()
const { connected: wsConnected, lastMessage, connect: wsConnect, disconnect: wsDisconnect, requestData } = useWebSocket()

const loading = ref(true)
const lastUpdate = ref('--')
const dailyList = ref([])
const fundTotals = ref({ total_assets: 0, available: 0, net_assets: 0, unrealized_pnl: 0 })
const activeRange = ref('30d')
const activeGran = ref('day')   // day | week | month
const chartKey = ref(0)
let fallbackTimer = null

// 收益视图(20260620): merged=合并全部关联用户; <user_id>=只看某个用户
const activeView = ref('merged')
const viewOptions = ref([])  // [{label,val}], 仅当有关联用户时长度>1
async function loadViewOptions() {
  try {
    const r = await api.get('/api/v1/pnl/link-options')
    const linked = r.data?.linked || []
    if (linked.length === 0) { viewOptions.value = []; return }  // 无关联→不显示下拉
    const self = r.data?.self
    viewOptions.value = [
      { label: '合并全部数据', val: 'merged' },
      ...(self ? [{ label: self.username + '(本人)', val: self.user_id }] : []),
      ...linked.map(u => ({ label: u.username, val: u.user_id })),
    ]
  } catch (e) { viewOptions.value = [] }
}
async function onViewChange() {
  await Promise.all([setRange(activeRange.value), fetchCumulative()])
}

const ranges = [
  { label: '30天', val: '30d' }, { label: '90天', val: '90d' },
  { label: '半年', val: '180d' }, { label: '全部', val: '365d' },
]
const grans = [
  { label: '日', val: 'day' }, { label: '周', val: 'week' }, { label: '月', val: 'month' },
]
const rangeLabel = computed(() => (ranges.find(r => r.val === activeRange.value) || {}).label || '')

// ── 四个核心数字: 今日/本周/本月由 dailyList 现算; 累计独立从 /pnl/cumulative 取 ──
const todayPnl = computed(() => {
  const today = dayjs().tz('Asia/Shanghai').format('YYYY-MM-DD')
  const d = dailyList.value.find(x => x.date === today)
  return d ? d.net_pnl : 0
})
const thisWeekPnl = computed(() => {
  const d = dayjs().tz('Asia/Shanghai')
  const ws = d.subtract((d.day() + 6) % 7, 'day').format('YYYY-MM-DD')  // 本周一
  return dailyList.value.filter(x => x.date >= ws).reduce((s, x) => s + x.net_pnl, 0)
})
const thisMonthPnl = computed(() => {
  const ms = dayjs().tz('Asia/Shanghai').format('YYYY-MM') + '-01'
  return dailyList.value.filter(x => x.date >= ms).reduce((s, x) => s + x.net_pnl, 0)
})
// 累计收益: 改为固定"开户至今"(后端 /pnl/cumulative, inception起算), 独立于上方范围,
// 不再随30天滚动窗/日期跳变。cumulativePnl 不再从 dailyList 求和。
const cumulativePnl = ref(0)
const cumInception = ref('')
const cumLoading = ref(false)
async function fetchCumulative() {
  cumLoading.value = true
  try {
    const r = await api.get('/api/v1/pnl/cumulative', { params: { platform: 'all', view: activeView.value } })
    cumulativePnl.value = Number(r.data?.cumulative_pnl || 0)
    cumInception.value = r.data?.inception_date || ''
  } catch (e) { console.error('cumulative fetch error:', e) }
  finally { cumLoading.value = false }
}

// 数字自适应字号(完整显示不截断): 按格式化后字符串长度选 Tailwind 字号档, 字号下探更小,
// 保证半屏卡片宽度内最长金额也能整行放下(无 overflow-hidden, 永不出现 "..." 截断)。
// 参考: 半屏卡片(grid-cols-2, p-4)内容宽约 130-150px。
function fitFont(v) {
  const len = String(fmtPnl(v)).length
  if (len <= 7) return 'text-2xl'      // +137.16
  if (len <= 9) return 'text-xl'       // +1,622.36
  if (len <= 11) return 'text-base'    // +9,209.10 / +12,345.67
  if (len <= 13) return 'text-sm'      // +123,456.78
  return 'text-xs'                      // 更长极端值, 仍完整显示
}

// ── 趋势图: 日/周/月 三种粒度, 纯前端切换, 不发请求 ──
const chartData = computed(() => {
  const list = dailyList.value
  if (!list.length) return { labels: [], datasets: [] }
  let rows
  if (activeGran.value === 'week') {
    rows = aggregateWeekly(list).map(w => ({ label: w.week.substring(5), v: w.net_pnl }))
  } else if (activeGran.value === 'month') {
    rows = aggregateMonthly(list).map(m => ({ label: m.month, v: m.net_pnl }))
  } else {
    rows = list.map(d => ({ label: d.date.substring(5), v: d.net_pnl }))
  }
  return {
    labels: rows.map(r => r.label),
    datasets: [{
      label: '收益',
      data: rows.map(r => parseFloat(r.v.toFixed(2))),
      backgroundColor: rows.map(r => r.v >= 0 ? 'rgba(14,203,129,0.75)' : 'rgba(246,70,93,0.75)'),
      borderRadius: 3,
      maxBarThickness: 28,
    }]
  }
})

const chartOpts = {
  responsive: true, maintainAspectRatio: false, animation: false,
  plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(0,0,0,0.85)' } },
  scales: {
    x: { grid: { display: false }, ticks: { color: '#666', maxTicksLimit: 8, font: { size: 10 } } },
    y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } } }
  }
}

watch(activeGran, () => { chartKey.value++ })

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
  const start = dayjs().tz('Asia/Shanghai').subtract(days, 'day').format('YYYY-MM-DD')
  const end = dayjs().tz('Asia/Shanghai').format('YYYY-MM-DD')
  loading.value = true
  try {
    const data = await fetchDailyPnl(start, end, activeView.value)
    dailyList.value = data.daily_pnl || []
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

// 切户/重新登录后自动刷新: pnlUtils 的缓存键只按日期范围(不含user_id), 换用户后60s内会
// 命中上个用户的缓存→显示旧数据。故进入页面先 clearPnlCache 清缓存, 并 watch 当前用户变化
// (username 变即重新拉数), 保证切户后数据立即随当前账号刷新, 无需手动刷新。
watch(() => auth.user?.username, (nu, ou) => {
  if (nu && nu !== ou) {
    clearPnlCache()
    activeView.value = 'merged'
    loadViewOptions()
    setRange(activeRange.value)
    fetchFund()
    fetchCumulative()
  }
})

onMounted(async () => {
  clearPnlCache()           // 进入页即清, 杜绝跨用户缓存串号
  await auth.fetchUser()    // 先确认当前用户, 再拉该用户数据
  wsConnect()
  setWsInstance({ connected: wsConnected, requestData })
  loadViewOptions()        // 加载收益视图下拉(有关联用户才显示)
  await Promise.all([setRange('30d'), fetchFund()])
  fetchCumulative()         // 累计独立拉取(开户至今, 不阻塞首屏四宫格其余三个数)
})
onUnmounted(() => { wsDisconnect(); clearInterval(fallbackTimer) })
</script>
