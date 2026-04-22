<template>
  <div class="space-y-4">
    <!-- Target picker + window selector (merged compact row) -->
    <div class="bg-dark-100 rounded-xl px-3 py-2 border border-border-primary flex items-center gap-2 text-xs flex-wrap">
      <span class="text-text-tertiary">作用域:</span>
      <button @click="selectedTarget = null"
        class="px-2 py-0.5 rounded"
        :class="selectedTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary hover:bg-dark-300'">全部</button>
      <button v-for="t in targets" :key="t.id" @click="selectedTarget = t.id"
        class="px-2 py-0.5 rounded"
        :class="selectedTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary hover:bg-dark-300'">
        <span class="font-semibold">{{ t.username }}</span>/<span class="font-mono">{{ t.pair_code }}</span>
      </button>
      <span v-if="targets.length === 0" class="text-text-tertiary">尚无目标</span>
      <span class="mx-2 text-text-tertiary">|</span>
      <span class="text-text-tertiary">窗口:</span>
      <button v-for="w in WINDOWS" :key="w.key" @click="windowKey = w.key"
        class="px-2 py-0.5 rounded"
        :class="windowKey === w.key ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">{{ w.label }}</button>
      <button @click="showCharts = !showCharts" class="ml-auto px-2 py-0.5 rounded bg-dark-200 text-text-secondary hover:bg-dark-300">
        {{ showCharts ? '隐藏图表' : '显示图表' }}
      </button>
    </div>

    <!-- Single unified KPI strip (10 metrics, collapsed padding) -->
    <div class="grid grid-cols-2 md:grid-cols-5 lg:grid-cols-10 gap-2">
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">运行模式</div>
        <div class="font-bold text-base leading-tight" :class="modeColor">{{ modeLabel }}</div>
        <div class="text-[9px] text-text-tertiary">kill: {{ status?.kill_switch ? '开' : '关' }}</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">总权益</div>
        <div class="font-mono font-bold text-base leading-tight">{{ fmt(status?.total_equity) }}</div>
        <div class="text-[9px] text-text-tertiary truncate">A{{ fmt(status?.a_equity) }}·B{{ fmt(status?.b_equity) }}</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">总持仓比</div>
        <div class="font-mono font-bold text-base leading-tight" :class="ratioColor(status?.position_ratio, 0.5)">{{ pct(status?.position_ratio) }}</div>
        <div class="text-[9px] text-text-tertiary">上限50%</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">日内累计</div>
        <div class="font-mono font-bold text-base leading-tight" :class="ratioColor(status?.daily_volume_ratio, 5)">{{ pct(status?.daily_volume_ratio) }}</div>
        <div class="text-[9px] text-text-tertiary">上限500%</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">30m点差</div>
        <div class="font-mono font-bold text-base leading-tight" :class="spreadColor(status?.spread_30m_avg)">{{ status?.spread_30m_avg?.toFixed(2) ?? '--' }}</div>
        <div class="text-[9px] text-text-tertiary truncate">{{ spreadModeLabel }}</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">决策数</div>
        <div class="font-mono font-bold text-base leading-tight">{{ stats?.total ?? '--' }}</div>
        <div class="text-[9px] text-text-tertiary">{{ windowKey }}</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">执行率</div>
        <div class="font-mono font-bold text-base leading-tight text-success">{{ pct(stats?.executed_rate) }}</div>
        <div class="text-[9px] text-text-tertiary">exec/total</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">拒绝率</div>
        <div class="font-mono font-bold text-base leading-tight text-danger">{{ pct(stats?.rejected_rate) }}</div>
        <div class="text-[9px] text-text-tertiary">rej/total</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">Token</div>
        <div class="font-mono font-bold text-base leading-tight">{{ fmtInt(stats?.tokens_total) }}</div>
        <div class="text-[9px] text-text-tertiary truncate">in{{ fmtInt(stats?.tokens_in) }}·out{{ fmtInt(stats?.tokens_out) }}</div>
      </div>
      <div class="bg-dark-100 rounded-lg px-2.5 py-1.5 border border-border-primary">
        <div class="text-[10px] text-text-tertiary">p50/p95ms</div>
        <div class="font-mono font-bold text-base leading-tight">{{ stats?.latency?.p50_ms?.toFixed(0) ?? '--' }}/{{ stats?.latency?.p95_ms?.toFixed(0) ?? '--' }}</div>
        <div class="text-[9px] text-text-tertiary">p99 {{ stats?.latency?.p99_ms?.toFixed(0) ?? '--' }}</div>
      </div>
    </div>

    <!-- Mid: leg balance + rate buckets (compact) -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-2">
      <div class="bg-dark-100 rounded-xl p-3 border border-border-primary lg:col-span-2">
        <div class="flex justify-between items-center mb-2">
          <h3 class="font-semibold text-sm">双腿配平 <span v-if="balance?.target_label" class="text-[10px] text-text-tertiary font-normal">· {{ balance.target_label }}</span></h3>
          <span class="text-[10px] text-text-tertiary">5s</span>
        </div>
        <div v-if="!balance" class="text-text-tertiary text-xs py-4 text-center">加载中…</div>
        <div v-else class="flex items-center gap-4 text-xs flex-wrap">
          <div><span class="text-text-tertiary">A</span> <span class="font-mono text-[10px] opacity-70">{{ balance?.a_symbol || "XAUUSDT" }}</span> <span class="font-mono ml-1">{{ balance.a_size }} 张</span></div>
          <div><span class="text-text-tertiary">B</span> <span class="font-mono text-[10px] opacity-70">{{ balance?.b_symbol || "XAUUSD+" }}</span> <span class="font-mono ml-1">{{ balance.b_size }} × {{ balance.conversion_factor }}</span></div>
          <div><span class="text-text-tertiary">偏差</span> <span class="font-mono font-bold ml-1" :class="Math.abs(balance.delta) > 1 ? 'text-danger' : 'text-success'">{{ balance.delta?.toFixed(2) }} oz</span></div>
          <div v-if="Math.abs(balance.delta) > 1" class="text-danger">⚠ 单腿，仅允许 rebalance</div>
        </div>
      </div>
      <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
        <h3 class="font-semibold text-sm mb-2">频次水位 <span class="text-[9px] text-text-tertiary font-normal">{{ rate ? ('已含 ' + pct(rate.safety_margin) + ' 安全余量') : '' }}</span></h3>
        <div v-if="!rate" class="text-text-tertiary text-xs py-2 text-center">加载中…</div>
        <div v-else class="space-y-1">
          <div v-for="b in rate.buckets" :key="b.window" class="text-[11px]">
            <div class="flex justify-between">
              <span class="text-text-tertiary">{{ b.window }}</span>
              <span class="font-mono">{{ b.used }}/{{ b.effective_cap }}</span>
            </div>
            <div class="h-1 bg-dark-200 rounded overflow-hidden">
              <div class="h-full" :class="bucketColor(b)" :style="{width: Math.min(100, b.used / b.effective_cap * 100) + '%'}"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Phase 2 viz: 2x2 grid, togglable -->
    <div v-if="showCharts" class="grid grid-cols-1 md:grid-cols-2 gap-2">
      <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
        <h3 class="font-semibold text-sm mb-2">决策热力图 <span class="text-[10px] text-text-tertiary font-normal">按小时 × 判决</span></h3>
        <div v-if="!heatmap" class="text-text-tertiary text-xs py-6 text-center">加载中…</div>
        <div v-else class="h-40"><Bar :data="heatmapChart" :options="heatmapOpts" /></div>
      </div>
      <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
        <h3 class="font-semibold text-sm mb-2">判决分布</h3>
        <div v-if="!stats" class="text-text-tertiary text-xs py-6 text-center">加载中…</div>
        <div v-else class="h-40"><Doughnut :data="verdictPie" :options="pieOpts" /></div>
      </div>
      <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
        <h3 class="font-semibold text-sm mb-2">触发类型 TOP 10</h3>
        <div v-if="!stats" class="text-text-tertiary text-xs py-6 text-center">加载中…</div>
        <div v-else class="h-40"><Bar :data="triggerBar" :options="horizBarOpts" /></div>
      </div>
      <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
        <h3 class="font-semibold text-sm mb-2">Token 成本 CNY <span class="text-[10px] text-text-tertiary font-normal">近 7 天</span></h3>
        <div v-if="!costSeries" class="text-text-tertiary text-xs py-6 text-center">加载中…</div>
        <div v-else class="h-40"><Line :data="costChart" :options="lineOpts" /></div>
      </div>
    </div>

    <!-- Decision stream (height-capped with inner scroll) -->
    <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
      <div class="flex justify-between items-center mb-2">
        <h3 class="font-semibold text-sm">最近决策（实时）</h3>
        <router-link to="/decisions" class="text-xs text-primary hover:underline">查看全部 →</router-link>
      </div>
      <div class="max-h-72 overflow-y-auto">
      <div v-if="decisions.length === 0" class="text-text-tertiary text-sm py-6 text-center">暂无决策</div>
      <table v-else class="w-full text-xs">
        <thead class="text-text-tertiary">
          <tr class="text-left">
            <th class="py-1">时间</th>
            <th>目标</th>
            <th>触发</th>
            <th>动作</th>
            <th>数量</th>
            <th>判决</th>
            <th>tokens / ms</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in decisions.slice(0, 10)" :key="d.id" class="border-t border-border-primary hover:bg-dark-200">
            <td class="py-1.5 font-mono text-text-tertiary">{{ fmtTime(d.created_at) }}</td>
            <td class="text-[11px]">
              <span v-if="d.username" class="font-semibold text-text-secondary">{{ d.username }}</span>
              <span v-if="d.pair_code" class="font-mono text-primary">/{{ d.pair_code }}</span>
              <span v-if="!d.username && !d.pair_code" class="text-text-tertiary">—</span>
            </td>
            <td class="text-text-secondary">{{ d.trigger }}</td>
            <td><span class="font-mono" :class="actionColor(d.action)">{{ d.action }}</span></td>
            <td class="font-mono">{{ d.qty }}</td>
            <td>
              <span class="px-1.5 py-0.5 rounded text-[10px]" :class="verdictBadge(d.verdict)">{{ d.verdict }}</span>
            </td>
            <td class="font-mono text-text-tertiary">{{ (d.tokens_in||0)+(d.tokens_out||0) }} / {{ d.latency_ms }}</td>
            <td class="text-text-secondary truncate max-w-[240px]" :title="d.reject_reason || d.reason">
              {{ d.reject_reason || d.reason }}
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'
import { useWsStream } from '@/stores/wsStream.js'
import { Bar, Line, Doughnut } from 'vue-chartjs'
import {
  Chart, BarElement, LineElement, PointElement, ArcElement,
  CategoryScale, LinearScale, Tooltip, Legend, Filler, Title,
} from 'chart.js'
Chart.register(BarElement, LineElement, PointElement, ArcElement,
  CategoryScale, LinearScale, Tooltip, Legend, Filler, Title)

const WINDOWS = [
  { key: '1h', label: '1h' },
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
]

const status = ref(null)
const balance = ref(null)
const rate = ref(null)
const decisions = ref([])
const targets = ref([])
const selectedTarget = ref(null)
const windowKey = ref('24h')
const stats = ref(null)
const heatmap = ref(null)
const costSeries = ref(null)
const showCharts = ref(true)

const modeLabel = computed(() => ({ shadow: 'Shadow', semi: '半自动', auto: '全自动', off: '已停机' })[status.value?.mode] || '--')
const modeColor = computed(() => ({ shadow: 'text-yellow-400', semi: 'text-blue-400', auto: 'text-success', off: 'text-text-tertiary' })[status.value?.mode] || 'text-text-primary')
const spreadModeLabel = computed(() => {
  const s = Math.abs(status.value?.spread_30m_avg || 0)
  if (s > 5) return '极端模式 (>5)'
  if (s > 1.5) return '中等模式 (1.5-5)'
  return '普通模式 (±1.5)'
})

function fmt(n) { return n != null ? Number(n).toFixed(2) : '--' }
function fmtInt(n) {
  if (n == null) return '--'
  const v = Number(n)
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'k'
  return v.toString()
}
function pct(n) { return n != null ? (Number(n) * 100).toFixed(1) + '%' : '--' }
function fmtTime(t) { return dayjs(t).format('HH:mm:ss') }
function ratioColor(r, cap) {
  if (r == null) return 'text-text-primary'
  const ratio = r / cap
  if (ratio > 0.8) return 'text-danger'
  if (ratio > 0.5) return 'text-warning'
  return 'text-text-primary'
}
function spreadColor(s) {
  if (s == null) return 'text-text-primary'
  const a = Math.abs(s)
  if (a > 5) return 'text-danger'
  if (a > 1.5) return 'text-warning'
  return 'text-text-primary'
}
function actionColor(a) {
  if (a === 'noop') return 'text-text-tertiary'
  if (a?.startsWith('open')) return 'text-primary'
  if (a?.startsWith('close')) return 'text-blue-400'
  if (a === 'rebalance') return 'text-yellow-400'
  return 'text-text-primary'
}
function verdictBadge(v) {
  return ({
    executed: 'bg-success/20 text-success',
    shadow: 'bg-yellow-900/30 text-yellow-400',
    pending: 'bg-blue-900/30 text-blue-400',
    rejected: 'bg-danger/20 text-danger',
    skipped: 'bg-dark-200 text-text-tertiary',
  })[v] || 'bg-dark-200 text-text-tertiary'
}
function bucketColor(b) {
  const r = b.used / b.effective_cap
  if (r > 0.8) return 'bg-danger'
  if (r > 0.5) return 'bg-warning'
  return 'bg-success'
}

// ── Chart data ───────────────────────────────────────────────────────
const heatmapChart = computed(() => {
  if (!heatmap.value) return { labels: [], datasets: [] }
  const labels = heatmap.value.buckets.map(b => dayjs(b.hour).format('DD HH:00'))
  return {
    labels,
    datasets: [
      { label: 'shadow', data: heatmap.value.buckets.map(b => b.shadow), backgroundColor: '#facc15cc', stack: 's' },
      { label: 'executed', data: heatmap.value.buckets.map(b => b.executed), backgroundColor: '#22c55ecc', stack: 's' },
      { label: 'rejected', data: heatmap.value.buckets.map(b => b.rejected), backgroundColor: '#ef4444cc', stack: 's' },
      { label: 'pending',  data: heatmap.value.buckets.map(b => b.pending),  backgroundColor: '#3b82f6cc', stack: 's' },
    ],
  }
})
const heatmapOpts = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { labels: { color: '#a1a1aa', font: { size: 9 }, boxWidth: 8 } } },
  scales: {
    x: { stacked: true, ticks: { color: '#71717a', font: { size: 8 }, maxRotation: 60, autoSkip: true, autoSkipPadding: 16 }, grid: { display: false } },
    y: { stacked: true, ticks: { color: '#71717a', font: { size: 9 } }, grid: { color: '#27272a' } },
  },
}

const verdictPie = computed(() => {
  const bv = stats.value?.by_verdict || {}
  const labels = Object.keys(bv)
  const colors = labels.map(l => ({
    executed: '#22c55e', shadow: '#facc15',
    pending: '#3b82f6', rejected: '#ef4444',
  }[l] || '#71717a'))
  return {
    labels,
    datasets: [{ data: labels.map(l => bv[l]), backgroundColor: colors, borderWidth: 0 }],
  }
})
const pieOpts = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { position: 'bottom', labels: { color: '#a1a1aa', font: { size: 10 } } } },
}

const triggerBar = computed(() => {
  const rows = (stats.value?.by_trigger || []).slice(0, 10)
  return {
    labels: rows.map(r => r.trigger),
    datasets: [{ label: '次数', data: rows.map(r => r.count), backgroundColor: '#06b6d4cc' }],
  }
})
const horizBarOpts = {
  indexAxis: 'y', responsive: true, maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { ticks: { color: '#71717a', font: { size: 10 } }, grid: { color: '#27272a' } },
    y: { ticks: { color: '#71717a', font: { size: 10 } }, grid: { display: false } },
  },
}

const costChart = computed(() => {
  if (!costSeries.value) return { labels: [], datasets: [] }
  const ss = costSeries.value.series || []
  return {
    labels: ss.map(r => dayjs(r.time).format('MM-DD HH:00')),
    datasets: [
      { label: 'CNY', data: ss.map(r => r.cost_cny), borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.15)', fill: true, tension: 0.25, pointRadius: 0 },
    ],
  }
})
const lineOpts = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { ticks: { color: '#71717a', font: { size: 9 }, maxRotation: 60, autoSkip: true, autoSkipPadding: 12 }, grid: { color: '#27272a' } },
    y: { ticks: { color: '#71717a', font: { size: 10 } }, grid: { color: '#27272a' } },
  },
}

// ── Data loading ─────────────────────────────────────────────────────
async function refreshCore() {
  try {
    const tid = selectedTarget.value
    const qs = tid != null ? '?target_id=' + tid : ''
    const [s, b, r, d, ts] = await Promise.all([
      api.get('/api/v1/agent/status' + qs).catch(() => null),
      api.get('/api/v1/agent/leg-balance' + qs).catch(() => null),
      api.get('/api/v1/agent/rate-buckets' + qs).catch(() => null),
      api.get('/api/v1/agent/decisions?limit=10' + (tid != null ? '&target_id=' + tid : '')).catch(() => null),
      targets.value.length === 0 ? api.get('/api/v1/agent/scope/targets').catch(() => null) : Promise.resolve(null),
    ])
    if (ts) targets.value = ts.data?.items?.filter(t => t.enabled) || []
    if (s) status.value = s.data
    if (b) balance.value = b.data
    if (r) rate.value = r.data
    if (d) decisions.value = d.data?.items || []
  } catch (e) { console.error(e) }
}

async function refreshAnalytics() {
  try {
    const tid = selectedTarget.value
    const w = windowKey.value
    const tq = tid != null ? '&target_id=' + tid : ''
    const [st, hm, cs] = await Promise.all([
      api.get('/api/v1/agent/decisions/stats?window=' + w + tq).catch(() => null),
      api.get('/api/v1/agent/decisions/heatmap?window=' + w + tq).catch(() => null),
      // cost series uses its own longer window regardless of KPI window
      api.get('/api/v1/agent/decisions/cost-series?window=7d&bucket=hour' + tq).catch(() => null),
    ])
    if (st) stats.value = st.data
    if (hm) heatmap.value = hm.data
    if (cs) costSeries.value = cs.data
  } catch (e) { console.error(e) }
}

// Keep existing polling (status / leg-balance / rate-buckets still need
// HTTP freshness), but live-update the preview list via WS so a new
// decision shows up instantly instead of on the next 5s tick.
const ws = useWsStream()
let coreTimer, analyticsTimer, wsStopDecisions, wsStopProposals
watch(selectedTarget, () => { refreshCore(); refreshAnalytics() })
watch(windowKey, () => refreshAnalytics())
onMounted(() => {
  refreshCore(); refreshAnalytics()
  coreTimer = setInterval(refreshCore, 5000)
  analyticsTimer = setInterval(refreshAnalytics, 30000)
  ws.connect()
  ws.subscribe('agent.decisions')
  ws.subscribe('agent.proposals')
  wsStopDecisions = watch(() => ws.channels['agent.decisions'], (payload) => {
    if (!payload || payload.event !== 'decision_new') return
    // Drop events that wouldn't match the currently-selected target
    if (selectedTarget.value != null && payload.target_id !== selectedTarget.value) return
    if (decisions.value.find(x => x.id === payload.id)) return
    decisions.value = [payload, ...decisions.value].slice(0, 20)
  })
  wsStopProposals = watch(() => ws.channels['agent.proposals'], (payload) => {
    // Proposal lifecycle events — just nudge analytics + core refresh to
    // reflect the possible config hot-reload.
    if (!payload) return
    refreshCore()
  })
})
onUnmounted(() => {
  clearInterval(coreTimer); clearInterval(analyticsTimer)
  try { ws.unsubscribe('agent.decisions') } catch {}
  try { ws.unsubscribe('agent.proposals') } catch {}
  if (wsStopDecisions) wsStopDecisions()
  if (wsStopProposals) wsStopProposals()
})
</script>
