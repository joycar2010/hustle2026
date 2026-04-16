<template>
  <div class="space-y-4">

    <!-- 工具栏 -->
    <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3 flex items-center gap-3 flex-wrap">
      <!-- 用户选择 -->
      <span class="text-sm text-text-tertiary whitespace-nowrap">用户：</span>
      <select v-model="selectedUserId" @change="loadChart"
        class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary min-w-[160px]">
        <option value="all">全部用户</option>
        <option v-for="u in users" :key="u.user_id" :value="u.user_id">
          {{ u.username }}
        </option>
      </select>

      <!-- 粒度选择 -->
      <div class="flex rounded-lg overflow-hidden border border-border-primary">
        <button v-for="g in granularities" :key="g.value" @click="granularity = g.value; loadChart()"
          :class="['px-3 py-1.5 text-xs font-medium transition-colors',
            granularity === g.value
              ? 'bg-primary text-dark-300'
              : 'bg-dark-200 text-text-secondary hover:bg-dark-50']">
          {{ g.label }}
        </button>
      </div>

      <!-- 日期范围 -->
      <div class="flex items-center gap-2">
        <input type="datetime-local" v-model="startTime"
          class="px-2 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary" />
        <span class="text-text-tertiary text-xs">至</span>
        <input type="datetime-local" v-model="endTime"
          class="px-2 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary" />
      </div>

      <button @click="loadChart"
        class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors">
        查询
      </button>
      <button @click="resetRange"
        class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
        重置
      </button>

      <!-- 导出PDF -->
      <button @click="exportPDF" :disabled="!chartData.labels?.length"
        class="ml-auto px-3 py-1.5 bg-[#0ecb81] hover:bg-[#0ecb81]/80 text-white font-semibold rounded-lg text-xs transition-colors disabled:opacity-40 flex items-center gap-1">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        导出 PDF
      </button>
    </div>

    <!-- 汇总卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3" v-if="summary">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
        <div class="text-xs text-text-tertiary mb-1">总收益 (PnL)</div>
        <div class="text-xl font-bold font-mono"
          :class="summary.total_pnl >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ formatNum(summary.total_pnl) }}
        </div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
        <div class="text-xs text-text-tertiary mb-1">净收益</div>
        <div class="text-xl font-bold font-mono"
          :class="summary.net_profit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ formatNum(summary.net_profit) }}
        </div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
        <div class="text-xs text-text-tertiary mb-1">总手续费</div>
        <div class="text-xl font-bold font-mono text-[#f0b90b]">{{ formatNum(summary.total_fee) }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
        <div class="text-xs text-text-tertiary mb-1">交易笔数</div>
        <div class="text-xl font-bold font-mono text-text-primary">{{ summary.total_trades }}</div>
      </div>
    </div>

    <!-- 图表 -->
    <div class="bg-dark-100 rounded-2xl border border-border-primary p-4" ref="chartContainer">
      <div v-if="loading" class="flex items-center justify-center py-20 text-text-tertiary text-sm">
        <svg class="animate-spin w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        加载中...
      </div>
      <div v-else-if="!chartData.labels?.length" class="text-center py-20 text-text-tertiary text-sm">
        暂无收益数据，请调整查询条件
      </div>
      <div v-else>
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-text-primary">收益趋势图</h3>
          <span class="text-xs text-text-tertiary">{{ granularityLabel }} | {{ dateRangeLabel }}</span>
        </div>
        <div style="height: 380px; position: relative;">
          <Line :data="chartData" :options="chartOptions" ref="chartRef" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend, Filler
} from 'chart.js'
import dayjs from 'dayjs'
import { jsPDF } from 'jspdf'
import api from '@/services/api.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

const props = defineProps({
  users: { type: Array, default: () => [] }
})

const granularities = [
  { value: 'hour',  label: '按小时' },
  { value: 'day',   label: '按日' },
  { value: 'week',  label: '按周' },
  { value: 'month', label: '按月' },
]

const selectedUserId = ref('all')
const granularity = ref('day')
const startTime = ref('')
const endTime = ref('')
const loading = ref(false)
const rawData = ref([])
const summary = ref(null)
const chartRef = ref(null)
const chartContainer = ref(null)

const granularityLabel = computed(() =>
  granularities.find(g => g.value === granularity.value)?.label || ''
)
const dateRangeLabel = computed(() => {
  if (startTime.value && endTime.value) {
    return `${dayjs(startTime.value).format('MM/DD HH:mm')} - ${dayjs(endTime.value).format('MM/DD HH:mm')}`
  }
  return '默认范围'
})

function formatNum(v) {
  if (v == null) return '-'
  const prefix = v >= 0 ? '+' : ''
  return prefix + v.toFixed(2)
}

function formatLabel(period) {
  const d = dayjs(period)
  switch (granularity.value) {
    case 'hour':  return d.format('MM/DD HH:00')
    case 'day':   return d.format('MM/DD')
    case 'week':  return d.format('MM/DD') + ' W'
    case 'month': return d.format('YYYY/MM')
    default:      return d.format('MM/DD')
  }
}

const chartData = computed(() => {
  if (!rawData.value.length) return { labels: [], datasets: [] }
  const labels = rawData.value.map(d => formatLabel(d.period))
  return {
    labels,
    datasets: [
      {
        label: '单期收益 (PnL)',
        data: rawData.value.map(d => d.pnl),
        borderColor: '#f0b90b',
        backgroundColor: 'rgba(240,185,11,0.1)',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: false,
      },
      {
        label: '累计收益',
        data: rawData.value.map(d => d.cum_pnl),
        borderColor: '#0ecb81',
        backgroundColor: 'rgba(14,203,129,0.08)',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 4,
        tension: 0.3,
        fill: true,
      },
    ]
  }
})

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      display: true,
      position: 'top',
      labels: { color: '#848e9c', usePointStyle: true, pointStyle: 'circle', padding: 16, font: { size: 11 } }
    },
    tooltip: {
      backgroundColor: '#1e2329',
      titleColor: '#eaecef',
      bodyColor: '#eaecef',
      borderColor: '#2b3139',
      borderWidth: 1,
      padding: 10,
      callbacks: {
        label(ctx) {
          const v = ctx.parsed.y
          const prefix = v >= 0 ? '+' : ''
          return `${ctx.dataset.label}: ${prefix}${v.toFixed(2)}`
        }
      }
    }
  },
  scales: {
    x: {
      ticks: { color: '#5e6673', font: { size: 10 }, maxRotation: 45 },
      grid: { color: 'rgba(43,49,57,0.5)' }
    },
    y: {
      ticks: {
        color: '#5e6673', font: { size: 10 },
        callback(v) { return (v >= 0 ? '+' : '') + v.toFixed(2) }
      },
      grid: { color: 'rgba(43,49,57,0.5)' }
    }
  }
}))

function resetRange() {
  startTime.value = ''
  endTime.value = ''
  loadChart()
}

async function loadChart() {
  loading.value = true
  try {
    const params = { granularity: granularity.value }
    if (startTime.value) params.start = startTime.value
    if (endTime.value) params.end = endTime.value

    if (selectedUserId.value === 'all') {
      const { data } = await api.get('/api/v1/users/profit-chart/all', { params })
      const periodMap = {}
      for (const row of (data.data || [])) {
        const key = row.period
        if (!periodMap[key]) periodMap[key] = { period: key, pnl: 0, fee: 0, trade_count: 0, cum_pnl: 0 }
        periodMap[key].pnl += row.pnl
        periodMap[key].trade_count += row.trade_count
      }
      const sorted = Object.values(periodMap).sort((a, b) => new Date(a.period) - new Date(b.period))
      let cumPnl = 0
      for (const p of sorted) { cumPnl += p.pnl; p.cum_pnl = cumPnl }
      rawData.value = sorted
      summary.value = {
        total_pnl: sorted.reduce((s, d) => s + d.pnl, 0),
        total_fee: 0,
        total_trades: sorted.reduce((s, d) => s + d.trade_count, 0),
        net_profit: sorted.reduce((s, d) => s + d.pnl, 0),
      }
    } else {
      const { data } = await api.get(`/api/v1/users/${selectedUserId.value}/profit-chart-v2`, { params })
      rawData.value = data.data || []
      summary.value = data.summary || null
    }
  } catch (e) {
    console.error('loadChart error', e)
    rawData.value = []
    summary.value = null
  } finally {
    loading.value = false
  }
}

async function exportPDF() {
  if (!chartRef.value?.chart) return

  const canvas = chartRef.value.chart.canvas
  const imgData = canvas.toDataURL('image/png', 1.0)

  const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })

  pdf.setFontSize(16)
  pdf.setTextColor(30, 35, 41)
  pdf.text('Hustle2026 - Profit Report', 14, 15)

  pdf.setFontSize(9)
  pdf.setTextColor(100)
  const userName = selectedUserId.value === 'all' ? 'All Users' :
    (props.users.find(u => u.user_id === selectedUserId.value)?.username || selectedUserId.value)
  pdf.text(`User: ${userName}  |  Granularity: ${granularity.value}  |  Generated: ${dayjs().format('YYYY-MM-DD HH:mm')}`, 14, 22)

  if (summary.value) {
    pdf.setFontSize(10)
    pdf.setTextColor(30)
    pdf.text(`Total PnL: ${formatNum(summary.value.total_pnl)}`, 14, 30)
    pdf.text(`Net Profit: ${formatNum(summary.value.net_profit)}`, 80, 30)
    pdf.text(`Total Fee: ${formatNum(summary.value.total_fee)}`, 150, 30)
    pdf.text(`Trades: ${summary.value.total_trades}`, 220, 30)
  }

  const pageW = pdf.internal.pageSize.getWidth()
  const pageH = pdf.internal.pageSize.getHeight()
  const chartW = pageW - 28
  const chartH = (canvas.height / canvas.width) * chartW
  const finalH = Math.min(chartH, pageH - 50)
  pdf.addImage(imgData, 'PNG', 14, 38, chartW, finalH)

  pdf.save(`profit_report_${dayjs().format('YYYYMMDD_HHmmss')}.pdf`)
}

onMounted(() => {
  loadChart()
})

defineExpose({ loadChart })
</script>
