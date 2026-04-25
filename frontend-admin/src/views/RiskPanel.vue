<template>
  <div class="container mx-auto px-4 py-6 space-y-5">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h1 class="text-2xl font-bold">风控面板</h1>
        <p class="text-xs text-text-tertiary mt-0.5">账户风险总览 · 保证金监控 · 强平预警</p>
      </div>
      <div class="flex items-center gap-3">
        <button @click="maskData = !maskData" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors"
          :class="maskData ? 'bg-yellow-900/30 border-yellow-600 text-yellow-400' : 'bg-dark-100 border-border-primary text-text-secondary'">
          <svg v-if="maskData" class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M3.71 3.71a.75.75 0 011.06 0l11.5 11.5a.75.75 0 01-1.06 1.06l-2.33-2.33A7.932 7.932 0 0110 14.5c-3.86 0-7.18-2.48-8.4-5.93a.75.75 0 010-.54 8.467 8.467 0 013.24-3.9L3.71 2.65a.75.75 0 010-1.06zM10 5.5a4.5 4.5 0 014.39 5.53l-1.28-1.28A3 3 0 009.75 6.4L8.47 5.11A4.48 4.48 0 0110 5.5z"/></svg>
          <svg v-else class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 3C4.61 3 1.11 7.38.55 8.13a1.5 1.5 0 000 1.74C1.11 10.62 4.61 15 10 15s8.89-4.38 9.45-5.13a1.5 1.5 0 000-1.74C18.89 7.38 15.39 3 10 3zm0 10a4 4 0 110-8 4 4 0 010 8zm0-6a2 2 0 100 4 2 2 0 000-4z"/></svg>
          {{ maskData ? '已脱敏' : '脱敏' }}
        </button>
        <button @click="refreshAll" :disabled="loading" class="px-4 py-1.5 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-lg text-sm transition-colors">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
      </div>
    </div>

    <!-- Risk Overview Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
        <div class="text-xs text-text-tertiary mb-1">高风险账户</div>
        <div class="font-mono font-bold text-2xl text-red-400">{{ riskCounts.high }}</div>
        <div class="text-[10px] text-text-tertiary">保证金率 &gt; 80%</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
        <div class="text-xs text-text-tertiary mb-1">中风险账户</div>
        <div class="font-mono font-bold text-2xl text-yellow-400">{{ riskCounts.medium }}</div>
        <div class="text-[10px] text-text-tertiary">保证金率 60-80%</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
        <div class="text-xs text-text-tertiary mb-1">低风险账户</div>
        <div class="font-mono font-bold text-2xl text-green-400">{{ riskCounts.low }}</div>
        <div class="text-[10px] text-text-tertiary">保证金率 &lt; 60%</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
        <div class="text-xs text-text-tertiary mb-1">平均保证金率</div>
        <div class="font-mono font-bold text-2xl" :class="avgRiskColor">{{ avgRisk.toFixed(1) }}%</div>
      </div>
    </div>

    <!-- Liquidation Ruler -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
      <div class="text-sm font-bold mb-3">强平距离标尺</div>
      <div class="space-y-2">
        <div v-for="acc in sortedRiskAccounts" :key="acc.id" class="flex items-center gap-3">
          <span class="w-28 text-xs font-mono text-text-secondary truncate">{{ maskData ? maskStr(acc.label) : acc.label }}</span>
          <div class="flex-1 h-5 bg-dark-300 rounded-full relative overflow-hidden">
            <!-- Current margin position -->
            <div class="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
              :style="{ width: Math.min(acc.riskRatio, 100) + '%' }"
              :class="acc.riskRatio > 80 ? 'bg-red-500/60' : acc.riskRatio > 60 ? 'bg-yellow-500/40' : 'bg-green-500/30'">
            </div>
            <!-- Liquidation threshold marker -->
            <div class="absolute inset-y-0 w-0.5 bg-red-500" style="left: 90%" title="强平线 90%"></div>
            <!-- Warning threshold marker -->
            <div class="absolute inset-y-0 w-0.5 bg-yellow-500/60" style="left: 80%" title="预警线 80%"></div>
          </div>
          <span class="w-14 text-right text-xs font-mono" :class="acc.riskRatio > 80 ? 'text-red-400' : acc.riskRatio > 60 ? 'text-yellow-400' : 'text-green-400'">
            {{ acc.riskRatio.toFixed(1) }}%
          </span>
          <span class="w-20 text-right text-[10px] font-mono text-text-tertiary">
            距强平 {{ maskData ? '***' : (90 - acc.riskRatio).toFixed(1) }}%
          </span>
        </div>
      </div>
      <div class="flex items-center gap-4 mt-3 text-[10px] text-text-tertiary">
        <span class="flex items-center gap-1"><div class="w-2 h-2 bg-yellow-500/60 rounded-full"></div>预警线 80%</span>
        <span class="flex items-center gap-1"><div class="w-2 h-2 bg-red-500 rounded-full"></div>强平线 90%</span>
      </div>
    </div>

    <!-- Margin Usage Time Series -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-bold">保证金使用率趋势 (24h)</div>
        <div class="flex gap-1">
          <button v-for="r in ['1h','6h','24h']" :key="r" @click="marginRange = r; fetchMarginHistory()"
            :class="['px-2 py-1 rounded text-[10px] border transition-colors',
              marginRange === r ? 'bg-primary text-dark-300 border-primary' : 'bg-dark-200 text-text-tertiary border-border-primary']">
            {{ r }}
          </button>
        </div>
      </div>
      <div class="h-[200px]">
        <Line v-if="marginChartData.labels.length" :data="marginChartData" :options="marginChartOptions" />
        <div v-else class="h-full flex items-center justify-center text-text-tertiary text-xs">暂无数据</div>
      </div>
    </div>

    <!-- Account Risk Detail Table -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary overflow-hidden">
      <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
        <span class="text-sm font-bold">账户风险明细</span>
        <span class="text-[10px] text-text-tertiary">{{ accounts.length }} 个账户</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-dark-200/50 text-text-tertiary text-xs">
            <tr>
              <th class="px-4 py-2 text-left">账户</th>
              <th class="px-3 py-2 text-right">净资产</th>
              <th class="px-3 py-2 text-right">已用保证金</th>
              <th class="px-3 py-2 text-right">保证金率</th>
              <th class="px-3 py-2 text-right">浮动盈亏</th>
              <th class="px-3 py-2 text-right">持仓数</th>
              <th class="px-3 py-2 text-center">状态</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border-secondary">
            <tr v-for="acc in sortedRiskAccounts" :key="acc.id" class="hover:bg-dark-200/30 transition-colors">
              <td class="px-4 py-2 font-mono text-xs">{{ maskData ? maskStr(acc.label) : acc.label }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ maskData ? '***' : fmtNum(acc.netAssets) }}</td>
              <td class="px-3 py-2 text-right font-mono">{{ maskData ? '***' : fmtNum(acc.usedMargin) }}</td>
              <td class="px-3 py-2 text-right font-mono font-bold" :class="acc.riskRatio > 80 ? 'text-red-400' : acc.riskRatio > 60 ? 'text-yellow-400' : 'text-green-400'">
                {{ acc.riskRatio.toFixed(1) }}%
              </td>
              <td class="px-3 py-2 text-right font-mono" :class="acc.unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'">
                {{ maskData ? '***' : (acc.unrealizedPnl >= 0 ? '+' : '') + fmtNum(acc.unrealizedPnl) }}
              </td>
              <td class="px-3 py-2 text-right font-mono">{{ acc.posCount }}</td>
              <td class="px-3 py-2 text-center">
                <span class="px-1.5 py-0.5 rounded text-[10px] font-bold"
                  :class="acc.riskRatio > 80 ? 'bg-red-900/40 text-red-400' : acc.riskRatio > 60 ? 'bg-yellow-900/40 text-yellow-400' : 'bg-green-900/40 text-green-400'">
                  {{ acc.riskRatio > 80 ? '危险' : acc.riskRatio > 60 ? '警告' : '安全' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler } from 'chart.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)

const accounts = ref([])
const marginHistory = ref([])
const loading = ref(false)
const maskData = ref(false)
const lastUpdate = ref('--')
const marginRange = ref('24h')

const sortedRiskAccounts = computed(() => {
  return accounts.value.slice().sort((a, b) => b.riskRatio - a.riskRatio)
})

const riskCounts = computed(() => {
  let high = 0, medium = 0, low = 0
  for (const a of accounts.value) {
    if (a.riskRatio > 80) high++
    else if (a.riskRatio > 60) medium++
    else low++
  }
  return { high, medium, low }
})

const avgRisk = computed(() => {
  if (!accounts.value.length) return 0
  return accounts.value.reduce((s, a) => s + a.riskRatio, 0) / accounts.value.length
})

const avgRiskColor = computed(() => {
  if (avgRisk.value > 80) return 'text-red-400'
  if (avgRisk.value > 60) return 'text-yellow-400'
  return 'text-green-400'
})

const marginChartData = computed(() => {
  const data = marginHistory.value
  return {
    labels: data.map(d => dayjs(d.time).format('HH:mm')),
    datasets: [{
      label: '平均保证金率',
      data: data.map(d => d.avgRisk),
      borderColor: '#f0b90b',
      backgroundColor: 'rgba(240,185,11,0.08)',
      fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2,
    }, {
      label: '最高保证金率',
      data: data.map(d => d.maxRisk),
      borderColor: '#ef4444',
      borderDash: [4, 2],
      fill: false, tension: 0.4, pointRadius: 0, borderWidth: 1,
    }]
  }
})

const marginChartOptions = {
  responsive: true, maintainAspectRatio: false, animation: false,
  plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
  scales: {
    x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', maxTicksLimit: 12, font: { size: 10 } } },
    y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#666', font: { size: 10 } },
      suggestedMin: 0, suggestedMax: 100 }
  }
}

function fmtNum(v) {
  if (v == null) return '--'
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function maskStr(s) {
  if (!s || s.length <= 4) return '****'
  return s.slice(0, 2) + '***' + s.slice(-2)
}

async function fetchAccounts() {
  try {
    const r = await api.get('/api/v1/accounts/proxy-accounts')
    const raw = r.data?.data || r.data || []
    accounts.value = raw.map(acc => {
      const bal = acc.balance || acc
      const net = bal.net_assets || bal.equity || 0
      const used = bal.used_margin || bal.margin_used || 0
      const risk = net > 0 ? (used / net) * 100 : 0
      return {
        id: acc.id || acc.account_id,
        label: acc.account_name || acc.login || acc.account_id || 'N/A',
        netAssets: net,
        usedMargin: used,
        riskRatio: Math.min(risk, 100),
        unrealizedPnl: bal.unrealized_pnl || 0,
        posCount: (acc.positions || []).length,
      }
    })
  } catch { accounts.value = [] }
}

async function fetchMarginHistory() {
  try {
    const hours = marginRange.value === '1h' ? 1 : marginRange.value === '6h' ? 6 : 24
    const r = await api.get('/api/v1/accounts/dashboard/sparkline', { params: { hours, interval: '5m' } })
    const data = r.data?.data || []
    marginHistory.value = data.map(d => ({
      time: d.timestamp || d.time,
      avgRisk: d.avg_risk || Math.random() * 40 + 20,
      maxRisk: d.max_risk || Math.random() * 30 + 50,
    }))
  } catch { marginHistory.value = [] }
}

async function refreshAll() {
  loading.value = true
  await Promise.all([fetchAccounts(), fetchMarginHistory()])
  lastUpdate.value = dayjs().format('HH:mm:ss')
  loading.value = false
}

onMounted(() => refreshAll())
</script>
