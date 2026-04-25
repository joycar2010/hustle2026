<template>
  <div class="space-y-4">
    <!-- ═══ Layer 1: Target Matrix Cards ═══ -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold text-sm flex items-center gap-2">
          智能体矩阵
          <span class="text-[10px] text-text-tertiary font-normal">{{ store.comparison.length }} 个目标</span>
          <span v-if="store.alerts.unacked_count" class="ml-1 px-1.5 py-0.5 rounded-full bg-danger text-white text-[10px] font-bold">{{ store.alerts.unacked_count }}</span>
        </h3>
        <div class="flex items-center gap-2 text-xs">
          <span class="text-text-tertiary">窗口:</span>
          <button v-for="w in WINDOWS" :key="w.key" @click="windowKey = w.key"
            class="px-2 py-0.5 rounded"
            :class="windowKey === w.key ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">{{ w.label }}</button>
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
        <div v-for="t in store.comparison" :key="t.target_id"
          @click="store.select(t.target_id)"
          class="rounded-lg p-3 border-2 cursor-pointer transition hover:shadow-lg relative"
          :class="cardClass(t)">
          <!-- Alert badge with reason tooltip -->
          <div v-if="t.alert_level !== 'normal'" class="absolute -top-1.5 -right-1.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold text-white animate-pulse"
            :class="t.alert_level === 'critical' ? 'bg-danger' : 'bg-warning'"
            :title="(t.alert_reasons || []).join(', ')">
            {{ t.alert_reasons?.length || '!' }}
          </div>
          <!-- Header -->
          <div class="flex items-center justify-between mb-2">
            <div>
              <span class="font-semibold text-sm">{{ t.username }}</span>
              <span class="font-mono text-primary text-xs ml-1">{{ t.pair_code }}</span>
            </div>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold"
              :class="healthBadge(t.health_score)">{{ t.health_score }}</span>
          </div>
          <!-- 8 indicators (added daily_pnl + max_drawdown) -->
          <div class="grid grid-cols-4 gap-x-2 gap-y-1 text-[10px]">
            <div>
              <span class="text-text-tertiary">模式</span>
              <div class="font-mono font-bold" :class="modeColor">{{ modeLabel }}</div>
            </div>
            <div>
              <span class="text-text-tertiary">频率/h</span>
              <div class="font-mono font-bold">{{ t.freq_per_hour }}</div>
            </div>
            <div>
              <span class="text-text-tertiary">偏差%</span>
              <div class="font-mono font-bold" :class="deviationColor(t.match_deviation_pct)">{{ t.match_deviation_pct }}%</div>
            </div>
            <div>
              <span class="text-text-tertiary">24h PnL</span>
              <div class="font-mono font-bold" :class="t.daily_pnl_est >= 0 ? 'text-success' : 'text-danger'">
                {{ t.daily_pnl_est >= 0 ? '+' : '' }}{{ fmtK(t.daily_pnl_est) }}
              </div>
            </div>
            <div>
              <span class="text-text-tertiary">回撤</span>
              <div class="font-mono font-bold" :class="t.max_drawdown_24h > 5 ? 'text-danger' : t.max_drawdown_24h > 2 ? 'text-warning' : 'text-text-primary'">{{ t.max_drawdown_24h || 0 }}%</div>
            </div>
            <div>
              <span class="text-text-tertiary">净资产</span>
              <div class="font-mono font-bold">{{ fmtK(t.net_assets_total) }}</div>
            </div>
            <div>
              <span class="text-text-tertiary">保证金</span>
              <div class="font-mono font-bold" :class="t.margin_usage_pct > 70 ? 'text-danger' : 'text-text-primary'">{{ t.margin_usage_pct || 0 }}%</div>
            </div>
            <div>
              <span class="text-text-tertiary">最近</span>
              <div class="font-mono text-text-secondary">{{ t.last_decision_at ? dayjs(t.last_decision_at).fromNow() : '--' }}</div>
            </div>
          </div>
          <!-- Verdict bar -->
          <div class="mt-2 h-1.5 bg-dark-300 rounded-full overflow-hidden flex">
            <div class="bg-success h-full" :style="{width: verdictPct(t, 'executed') + '%'}"></div>
            <div class="bg-yellow-500 h-full" :style="{width: verdictPct(t, 'shadow') + '%'}"></div>
            <div class="bg-danger h-full" :style="{width: verdictPct(t, 'rejected') + '%'}"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ Layer 2: Target Detail Panel (60/40) ═══ -->
    <div v-if="store.selectedTargetId && sel" class="grid grid-cols-1 lg:grid-cols-5 gap-4">
      <!-- Left 60%: Charts -->
      <div class="lg:col-span-3 space-y-4">
        <!-- Equity Curve -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center justify-between mb-2">
            <h4 class="font-semibold text-sm">净资产曲线</h4>
            <div class="text-[10px] text-text-tertiary">
              最大回撤 <span class="text-danger font-mono font-bold">{{ equityData.max_drawdown_pct?.toFixed(2) || 0 }}%</span>
              · 峰值 <span class="font-mono">{{ fmtK(equityData.peak_net || 0) }}</span>
            </div>
          </div>
          <div class="h-48"><Line v-if="equityChart.labels.length" :data="equityChart" :options="areaOpts" /></div>
        </div>
        <!-- Balance Series (A/B legs) -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center justify-between mb-2">
            <h4 class="font-semibold text-sm">A/B 腿平衡</h4>
            <div class="text-[10px] text-text-tertiary">偏差 <span class="font-mono font-bold" :class="deviationColor(sel.match_deviation_pct)">{{ sel.match_deviation_pct }}%</span></div>
          </div>
          <div class="h-48"><Line v-if="balanceChart.labels.length" :data="balanceChart" :options="dualAxisOpts" /></div>
        </div>
        <!-- Confidence Trend -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <h4 class="font-semibold text-sm mb-2">置信度 & 判决趋势</h4>
          <div class="h-40"><Bar v-if="confChart.labels.length" :data="confChart" :options="confOpts" /></div>
        </div>
      </div>

      <!-- Right 40%: KPIs + Fund + Timeline -->
      <div class="lg:col-span-2 space-y-4">
        <!-- Target KPI card -->
        <div class="bg-dark-100 rounded-xl p-4 border border-primary/30">
          <div class="flex items-center justify-between mb-3">
            <div>
              <span class="font-semibold">{{ sel.username }}</span>
              <span class="font-mono text-primary ml-1">{{ sel.pair_code }}</span>
            </div>
            <button @click="store.select(null)" class="text-xs text-text-tertiary hover:text-text-primary">✕</button>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">健康分</div><div class="font-mono font-bold text-xl" :class="healthColor(sel.health_score)">{{ sel.health_score }}</div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">告警级</div><div class="font-bold text-xl" :class="alertColor(sel.alert_level)">{{ alertLabel(sel.alert_level) }}</div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">24h 决策</div><div class="font-mono font-bold">{{ sel.executed_24h + sel.shadow_24h }} <span class="text-text-tertiary font-normal">/ {{ sel.total_24h }}</span></div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">24h PnL</div><div class="font-mono font-bold" :class="sel.daily_pnl_est >= 0 ? 'text-success' : 'text-danger'">{{ sel.daily_pnl_est >= 0 ? '+' : '' }}{{ sel.daily_pnl_est }}</div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">A 净资产</div><div class="font-mono font-bold">{{ fmtK(sel.net_assets_a) }}</div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">B 净资产</div><div class="font-mono font-bold">{{ fmtK(sel.net_assets_b) }}</div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">保证金%</div><div class="font-mono font-bold" :class="sel.margin_usage_pct > 70 ? 'text-danger' : ''">{{ sel.margin_usage_pct }}%</div></div>
            <div class="bg-dark-200 rounded p-2"><div class="text-[10px] text-text-tertiary">回撤</div><div class="font-mono font-bold text-danger">{{ sel.max_drawdown_24h }}%</div></div>
          </div>
          <!-- Alert reasons -->
          <div v-if="sel.alert_reasons?.length" class="mt-2 space-y-1">
            <div v-for="(r, i) in sel.alert_reasons" :key="i" class="text-[10px] px-2 py-1 rounded"
              :class="sel.alert_level === 'critical' ? 'bg-danger/10 text-danger' : 'bg-warning/10 text-warning'">{{ r }}</div>
          </div>
        </div>

        <!-- Fund Allocation (Doughnut) -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <h4 class="font-semibold text-sm mb-2">资金分配</h4>
          <div v-if="fundData.platforms?.length" class="space-y-3">
            <div class="h-32 flex justify-center"><Doughnut v-if="fundDonut.labels.length" :data="fundDonut" :options="donutOpts" /></div>
            <div v-for="p in fundData.platforms" :key="p.leg" class="flex items-center justify-between text-[10px]">
              <span class="font-semibold">{{ p.leg }} · {{ p.display_name || p.platform }}</span>
              <span class="font-mono">{{ fmtK(p.net_assets) }} <span class="text-text-tertiary">({{ p.margin_usage_pct }}%)</span></span>
            </div>
          </div>
          <div v-else class="text-text-tertiary text-xs text-center py-4">无数据</div>
        </div>

        <!-- Mini Decision Timeline (10 items) -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center justify-between mb-2">
            <h4 class="font-semibold text-sm">最近决策</h4>
            <router-link to="/decisions" class="text-[10px] text-primary hover:underline">全部 →</router-link>
          </div>
          <div v-if="targetDecisions.length" class="space-y-0 relative">
            <div class="absolute left-[7px] top-2 bottom-2 w-px bg-border-primary"></div>
            <div v-for="d in targetDecisions" :key="d.id" class="flex items-start gap-3 py-1.5 relative">
              <div class="w-[15px] h-[15px] rounded-full border-2 bg-dark-100 shrink-0 z-10"
                :class="verdictDotClass(d.verdict)"></div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 text-[10px]">
                  <span class="font-mono text-text-tertiary">{{ dayjs(d.created_at).format('HH:mm') }}</span>
                  <span :class="actionColor(d.action)">{{ d.action }}</span>
                  <span class="px-1 py-0.5 rounded text-[9px]" :class="verdictBadge(d.verdict)">{{ d.verdict }}</span>
                </div>
                <div v-if="d.reason || d.reject_reason" class="text-[9px] text-text-tertiary truncate mt-0.5">{{ d.reject_reason || d.reason }}</div>
              </div>
              <span v-if="d.confidence" class="text-[9px] font-mono text-text-tertiary shrink-0">{{ (d.confidence * 100).toFixed(0) }}%</span>
            </div>
          </div>
          <div v-else class="text-text-tertiary text-xs text-center py-3">暂无</div>
        </div>

        <!-- PnL Series -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center justify-between mb-2">
            <h4 class="font-semibold text-sm">PnL 趋势</h4>
            <span class="text-[10px] text-text-tertiary">{{ pnlData.source === 'trades' ? '交易数据' : '快照估算' }}</span>
          </div>
          <div v-if="pnlData.series?.length" class="h-28"><Bar :data="pnlChart" :options="pnlOpts" /></div>
          <div v-else class="text-text-tertiary text-xs text-center py-3">Shadow 模式 — 暂无交易数据</div>
          <div v-if="pnlData.total_pnl != null" class="text-xs text-right mt-1 font-mono"
            :class="pnlData.total_pnl >= 0 ? 'text-success' : 'text-danger'">
            累计 {{ pnlData.total_pnl >= 0 ? '+' : '' }}{{ pnlData.total_pnl }}
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ Layer 3: Global Comparison Table ═══ -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <h3 class="font-semibold text-sm mb-3">全局对比表</h3>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead class="text-text-tertiary">
            <tr class="text-left border-b border-border-primary">
              <th class="py-2 cursor-pointer hover:text-text-primary" @click="sortBy('username')">用户 {{ sortIcon('username') }}</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('pair_code')">交易对</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('health_score')">健康 {{ sortIcon('health_score') }}</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('total_24h')">24h决策 {{ sortIcon('total_24h') }}</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('avg_confidence')">置信度</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('match_deviation_pct')">偏差%</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('daily_pnl_est')">24h PnL {{ sortIcon('daily_pnl_est') }}</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('max_drawdown_24h')">回撤%</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('net_assets_total')">净资产 {{ sortIcon('net_assets_total') }}</th>
              <th class="cursor-pointer hover:text-text-primary" @click="sortBy('margin_usage_pct')">保证金%</th>
              <th>告警</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in sortedComparison" :key="t.target_id"
              @click="store.select(t.target_id)"
              class="border-t border-border-primary hover:bg-dark-200 cursor-pointer transition"
              :class="store.selectedTargetId === t.target_id ? 'bg-primary/5' : ''">
              <td class="py-2 font-semibold">{{ t.username }}</td>
              <td class="font-mono text-primary">{{ t.pair_code }}</td>
              <td><span class="font-mono font-bold" :class="healthColor(t.health_score)">{{ t.health_score }}</span></td>
              <td class="font-mono">{{ t.total_24h }}</td>
              <td class="font-mono">{{ (t.avg_confidence * 100).toFixed(0) }}%</td>
              <td class="font-mono" :class="deviationColor(t.match_deviation_pct)">{{ t.match_deviation_pct }}%</td>
              <td class="font-mono" :class="t.daily_pnl_est >= 0 ? 'text-success' : 'text-danger'">{{ t.daily_pnl_est >= 0 ? '+' : '' }}{{ t.daily_pnl_est }}</td>
              <td class="font-mono" :class="t.max_drawdown_24h > 5 ? 'text-danger' : ''">{{ t.max_drawdown_24h }}%</td>
              <td class="font-mono">{{ fmtK(t.net_assets_total) }}</td>
              <td class="font-mono" :class="t.margin_usage_pct > 70 ? 'text-danger' : ''">{{ t.margin_usage_pct }}%</td>
              <td><span class="px-1.5 py-0.5 rounded text-[10px] font-semibold" :class="alertBadge(t.alert_level)">{{ alertLabel(t.alert_level) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ═══ Decision Stream ═══ -->
    <div class="bg-dark-100 rounded-xl p-3 border border-border-primary">
      <div class="flex justify-between items-center mb-2">
        <h3 class="font-semibold text-sm">最近决策（实时）</h3>
        <router-link to="/decisions" class="text-xs text-primary hover:underline">查看全部 →</router-link>
      </div>
      <div class="max-h-60 overflow-y-auto">
        <div v-if="decisions.length === 0" class="text-text-tertiary text-sm py-6 text-center">暂无决策</div>
        <table v-else class="w-full text-xs">
          <thead class="text-text-tertiary">
            <tr class="text-left"><th class="py-1">时间</th><th>目标</th><th>动作</th><th>判决</th><th>置信</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in decisions.slice(0, 10)" :key="d.id" class="border-t border-border-primary hover:bg-dark-200">
              <td class="py-1.5 font-mono text-text-tertiary">{{ dayjs(d.created_at).format('HH:mm:ss') }}</td>
              <td class="text-[11px]">
                <span v-if="d.username" class="font-semibold text-text-secondary">{{ d.username }}</span>
                <span v-if="d.pair_code" class="font-mono text-primary">/{{ d.pair_code }}</span>
              </td>
              <td class="font-mono" :class="actionColor(d.action)">{{ d.action }}</td>
              <td><span class="px-1.5 py-0.5 rounded text-[10px]" :class="verdictBadge(d.verdict)">{{ d.verdict }}</span></td>
              <td class="font-mono text-text-tertiary">{{ d.confidence ? (d.confidence * 100).toFixed(0) + '%' : '--' }}</td>
              <td class="text-text-secondary truncate max-w-[200px]">{{ d.reject_reason || d.reason }}</td>
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
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { useTargetStore } from '@/stores/targetStore.js'
import { useWsStream } from '@/stores/wsStream.js'
import { Bar, Line, Doughnut } from 'vue-chartjs'
import {
  Chart, BarElement, LineElement, PointElement, ArcElement,
  CategoryScale, LinearScale, Tooltip, Legend, Filler,
} from 'chart.js'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')
Chart.register(BarElement, LineElement, PointElement, ArcElement, CategoryScale, LinearScale, Tooltip, Legend, Filler)

const WINDOWS = [
  { key: '1h', label: '1h' }, { key: '24h', label: '24h' },
  { key: '7d', label: '7d' }, { key: '30d', label: '30d' },
]

const store = useTargetStore()
const windowKey = ref('24h')
const decisions = ref([])
const targetDecisions = ref([])
const status = ref(null)
const equityData = ref({})
const balanceData = ref({})
const fundData = ref({})
const pnlData = ref({})
const confData = ref({})
const sortField = ref('health_score')
const sortAsc = ref(false)

const sel = computed(() => store.selectedTarget)

const sortedComparison = computed(() => {
  const arr = [...store.comparison]
  const f = sortField.value, dir = sortAsc.value ? 1 : -1
  arr.sort((a, b) => {
    const va = a[f] ?? 0, vb = b[f] ?? 0
    return typeof va === 'string' ? va.localeCompare(vb) * dir : (va - vb) * dir
  })
  return arr
})

function sortBy(field) {
  if (sortField.value === field) sortAsc.value = !sortAsc.value
  else { sortField.value = field; sortAsc.value = false }
}
function sortIcon(field) {
  if (sortField.value !== field) return ''
  return sortAsc.value ? '↑' : '↓'
}

const modeLabel = computed(() => ({ shadow: 'Shadow', semi: '半自动', auto: '全自动', off: '已停机' })[status.value?.mode] || 'Shadow')
const modeColor = computed(() => ({ shadow: 'text-yellow-400', semi: 'text-blue-400', auto: 'text-success', off: 'text-text-tertiary' })[status.value?.mode] || 'text-yellow-400')

function fmtK(n) {
  if (n == null) return '--'
  const v = Number(n)
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + 'k'
  return v.toFixed(2)
}
function verdictPct(t, v) { return t.total_24h ? ((t[v + '_24h'] || 0) / t.total_24h * 100).toFixed(1) : 0 }
function cardClass(t) {
  const s = store.selectedTargetId === t.target_id
  if (t.alert_level === 'critical') return s ? 'border-danger bg-danger/5' : 'border-danger/40 bg-dark-200 hover:border-danger/70'
  if (t.alert_level === 'warning') return s ? 'border-warning bg-warning/5' : 'border-warning/40 bg-dark-200 hover:border-warning/70'
  return s ? 'border-primary bg-primary/5' : 'border-border-primary bg-dark-200 hover:border-primary/40'
}
function healthBadge(s) { return s >= 80 ? 'bg-success/20 text-success' : s >= 50 ? 'bg-warning/20 text-warning' : 'bg-danger/20 text-danger' }
function healthColor(s) { return s >= 80 ? 'text-success' : s >= 50 ? 'text-warning' : 'text-danger' }
function deviationColor(p) { return p > 10 ? 'text-danger' : p > 5 ? 'text-warning' : 'text-text-primary' }
function alertColor(l) { return { critical: 'text-danger', warning: 'text-warning', normal: 'text-success' }[l] || '' }
function alertBadge(l) { return { critical: 'bg-danger/20 text-danger', warning: 'bg-warning/20 text-warning', normal: 'bg-success/20 text-success' }[l] || '' }
function alertLabel(l) { return { critical: '危险', warning: '警告', normal: '正常' }[l] || l }
function actionColor(a) {
  if (a === 'noop') return 'text-text-tertiary'
  if (a?.startsWith('open')) return 'text-primary'
  if (a?.startsWith('close')) return 'text-blue-400'
  return 'text-text-primary'
}
function verdictBadge(v) {
  return ({ executed: 'bg-success/20 text-success', shadow: 'bg-yellow-900/30 text-yellow-400', rejected: 'bg-danger/20 text-danger' })[v] || 'bg-dark-200 text-text-tertiary'
}
function verdictDotClass(v) {
  return ({ executed: 'border-success', shadow: 'border-yellow-500', rejected: 'border-danger', pending: 'border-blue-500' })[v] || 'border-text-tertiary'
}

// ── Charts ──
const equityChart = computed(() => {
  const s = equityData.value.series || []
  return {
    labels: s.map(r => dayjs(r.time).format('HH:mm')),
    datasets: [
      { label: '净资产', data: s.map(r => r.net_assets), borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.3, pointRadius: 0 },
      { label: '回撤%', data: s.map(r => r.drawdown_pct), borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.05)', fill: true, borderDash: [4, 2], tension: 0.3, pointRadius: 0, yAxisID: 'y1' },
    ],
  }
})

const balanceChart = computed(() => {
  const s = balanceData.value.series || []
  return {
    labels: s.map(r => dayjs(r.time).format('HH:mm')),
    datasets: [
      { label: 'A 仓位', data: s.map(r => r.a_size), borderColor: '#06b6d4', tension: 0.3, pointRadius: 0 },
      { label: 'B 标准化', data: s.map(r => r.b_normalized), borderColor: '#a855f7', tension: 0.3, pointRadius: 0 },
      { label: 'Delta', data: s.map(r => r.delta), borderColor: '#facc15', backgroundColor: 'rgba(250,204,21,0.1)', fill: true, tension: 0.3, pointRadius: 0, yAxisID: 'y1' },
    ],
  }
})

const confChart = computed(() => {
  const s = confData.value.series || []
  return {
    labels: s.map(r => r.date?.slice(5)),
    datasets: [
      { label: '执行', data: s.map(r => r.executed), backgroundColor: '#22c55ecc', stack: 's' },
      { label: '影子', data: s.map(r => r.shadow), backgroundColor: '#facc15cc', stack: 's' },
      { label: '拒绝', data: s.map(r => r.rejected), backgroundColor: '#ef4444cc', stack: 's' },
    ],
  }
})

const pnlChart = computed(() => {
  const s = pnlData.value.series || []
  return {
    labels: s.map(r => r.date?.slice(5)),
    datasets: [{ label: 'PnL', data: s.map(r => r.net_pnl), backgroundColor: s.map(r => r.net_pnl >= 0 ? '#22c55ecc' : '#ef4444cc') }],
  }
})

const fundDonut = computed(() => {
  const p = fundData.value.platforms || []
  const colors = ['#06b6d4', '#a855f7', '#22c55e', '#facc15']
  return {
    labels: p.map(x => x.leg + ' ' + (x.display_name || x.platform)),
    datasets: [{ data: p.map(x => x.net_assets), backgroundColor: colors.slice(0, p.length), borderWidth: 0 }],
  }
})

const SCALES = {
  x: { ticks: { color: '#71717a', font: { size: 8 }, maxRotation: 45, autoSkip: true, autoSkipPadding: 12 }, grid: { display: false } },
  y: { ticks: { color: '#71717a', font: { size: 9 } }, grid: { color: '#27272a' } },
}
const areaOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#a1a1aa', font: { size: 9 }, boxWidth: 8 } } }, scales: { ...SCALES, y1: { position: 'right', ticks: { color: '#ef4444', font: { size: 9 } }, grid: { display: false } } } }
const dualAxisOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#a1a1aa', font: { size: 9 }, boxWidth: 8 } } }, scales: { ...SCALES, y1: { position: 'right', ticks: { color: '#facc15', font: { size: 9 } }, grid: { display: false } } } }
const confOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#a1a1aa', font: { size: 9 }, boxWidth: 8 } } }, scales: { x: { ...SCALES.x, stacked: true }, y: { ...SCALES.y, stacked: true } } }
const pnlOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: SCALES }
const donutOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#a1a1aa', font: { size: 9 }, boxWidth: 8 } } } }

// ── Data loading ──
async function loadStatus() { try { status.value = (await api.get('/api/v1/agent/status')).data } catch {} }
async function loadDecisions() {
  try {
    const tid = store.selectedTargetId
    decisions.value = (await api.get('/api/v1/agent/decisions?limit=10' + (tid ? '&target_id=' + tid : ''))).data?.items || []
  } catch {}
}
async function loadTargetDecisions(tid) {
  if (!tid) { targetDecisions.value = []; return }
  try { targetDecisions.value = (await api.get('/api/v1/agent/decisions?limit=10&target_id=' + tid)).data?.items || [] } catch { targetDecisions.value = [] }
}
async function loadTargetDetail(tid) {
  if (!tid) { equityData.value = {}; balanceData.value = {}; fundData.value = {}; pnlData.value = {}; confData.value = {}; return }
  const w = windowKey.value
  const [eq, bal, fund, pnl, conf] = await Promise.all([
    api.get(`/api/v1/agent/targets/${tid}/equity-series?window=${w}`).catch(() => ({ data: {} })),
    api.get(`/api/v1/agent/targets/${tid}/balance-series?window=${w}`).catch(() => ({ data: {} })),
    api.get(`/api/v1/agent/targets/${tid}/fund-allocation`).catch(() => ({ data: {} })),
    api.get(`/api/v1/agent/targets/${tid}/pnl-series?window=${w}`).catch(() => ({ data: {} })),
    api.get(`/api/v1/agent/targets/${tid}/confidence-trend?window=${w}`).catch(() => ({ data: {} })),
  ])
  equityData.value = eq.data || {}; balanceData.value = bal.data || {}
  fundData.value = fund.data || {}; pnlData.value = pnl.data || {}; confData.value = conf.data || {}
}
async function refreshAll() { await Promise.all([store.refresh(), loadStatus(), loadDecisions()]) }

watch(() => store.selectedTargetId, (tid) => { loadTargetDetail(tid); loadTargetDecisions(tid); loadDecisions() })
watch(windowKey, () => { if (store.selectedTargetId) loadTargetDetail(store.selectedTargetId) })

const ws = useWsStream()
let coreTimer, wsStop
onMounted(() => {
  refreshAll()
  if (store.selectedTargetId) { loadTargetDetail(store.selectedTargetId); loadTargetDecisions(store.selectedTargetId) }
  coreTimer = setInterval(refreshAll, 10000)
  ws.connect(); ws.subscribe('agent.decisions')
  wsStop = watch(() => ws.channels['agent.decisions'], (p) => {
    if (!p || p.event !== 'decision_new') return
    if (store.selectedTargetId && p.target_id !== store.selectedTargetId) return
    if (!decisions.value.find(x => x.id === p.id)) decisions.value = [p, ...decisions.value].slice(0, 20)
  })
})
onUnmounted(() => { clearInterval(coreTimer); try { ws.unsubscribe('agent.decisions') } catch {}; if (wsStop) wsStop() })
</script>
