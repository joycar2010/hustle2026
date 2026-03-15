<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">套利机会分析</h1>

    <!-- Weekend Market Closed Notice -->
    <div v-if="isWeekend && queryType === 'recent'" class="card mb-6 bg-yellow-900/20 border-yellow-600">
      <div class="flex items-start gap-3">
        <svg class="w-6 h-6 text-yellow-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <div>
          <h3 class="text-lg font-semibold text-yellow-500 mb-2">MT5市场休市提醒</h3>
          <p class="text-sm text-gray-300 mb-2">
            当前为周末时间，MT5市场休市（周六、周日不交易）。由于套利机会数据需要同时获取Binance和Bybit MT5的价格，因此周末期间无法生成新的套利机会记录。
          </p>
          <p class="text-sm text-gray-400">
            💡 您可以查询历史数据（选择"按日"或"自定义时间段"）来查看工作日的套利机会记录。
          </p>
        </div>
      </div>
    </div>

    <!-- No Data Notice -->
    <div v-if="!loading && spreadRecords.length === 0 && !isWeekend" class="card mb-6 bg-red-900/20 border-red-600">
      <div class="flex items-start gap-3">
        <svg class="w-6 h-6 text-red-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <h3 class="text-lg font-semibold text-red-500 mb-2">无数据</h3>
          <p class="text-sm text-gray-300">
            所选时间段内没有套利机会记录。这可能是因为：
          </p>
          <ul class="text-sm text-gray-400 mt-2 ml-4 list-disc">
            <li>所选时间段内点差未达到套利阈值</li>
            <li>市场数据服务未运行</li>
            <li>所选时间段在MT5休市期间（周末）</li>
            <li>账户未启用或API配置有误</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Query Controls -->
    <div class="card mb-6">
      <h2 class="text-xl font-semibold mb-4">查询条件</h2>
      <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
        <!-- Query Type -->
        <div>
          <label class="block text-sm text-gray-400 mb-2">查询类型</label>
          <select v-model="queryType" @change="handleQueryTypeChange"
                  class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
            <option value="recent">近2小时</option>
            <option value="day">按日</option>
            <option value="custom">自定义时间段</option>
          </select>
        </div>

        <!-- Opportunity Type Filter -->
        <div>
          <label class="block text-sm text-gray-400 mb-2">套利类型</label>
          <select v-model="opportunityType"
                  class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
            <option value="">全部</option>
            <option value="forward_open">正向开仓</option>
            <option value="forward_close">正向平仓</option>
            <option value="reverse_open">反向开仓</option>
            <option value="reverse_close">反向平仓</option>
          </select>
        </div>

        <!-- Date Selection -->
        <div v-if="queryType === 'day'">
          <label class="block text-sm text-gray-400 mb-2">选择日期</label>
          <input type="date" v-model="selectedDate"
                 class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <!-- Custom Date Range -->
        <div v-if="queryType === 'custom'">
          <label class="block text-sm text-gray-400 mb-2">开始时间</label>
          <input type="datetime-local" v-model="startDate"
                 class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <div v-if="queryType === 'custom'">
          <label class="block text-sm text-gray-400 mb-2">结束时间</label>
          <input type="datetime-local" v-model="endDate"
                 class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <!-- Query Button -->
        <div class="flex items-end">
          <button @click="querySpreadData" :disabled="loading" class="btn-primary w-full flex items-center justify-center">
            <svg v-if="loading" class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {{ loading ? '查询中...' : '查询' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Statistics Overview -->
    <div class="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">总机会数</div>
        <div class="text-2xl font-bold">{{ spreadRecords.length }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">正向开仓</div>
        <div class="text-2xl font-bold text-green-500">{{ forwardOpenCount }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">正向平仓</div>
        <div class="text-2xl font-bold text-blue-500">{{ forwardCloseCount }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">反向开仓</div>
        <div class="text-2xl font-bold text-orange-500">{{ reverseOpenCount }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">反向平仓</div>
        <div class="text-2xl font-bold text-purple-500">{{ reverseCloseCount }}</div>
      </div>
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Forward Arbitrage Chart -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">正向套利分析 (Binance做多)</h3>
        <div class="text-xs text-gray-400 mb-2">开仓点差 = Bybit卖价 - Binance买价</div>
        <canvas ref="forwardChartRef"></canvas>
      </div>

      <!-- Reverse Arbitrage Chart -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">反向套利分析 (Bybit做多)</h3>
        <div class="text-xs text-gray-400 mb-2">开仓点差 = Binance卖价 - Bybit卖价</div>
        <canvas ref="reverseChartRef"></canvas>
      </div>
    </div>

    <!-- Spread Records Table -->
    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-semibold">套利机会列表</h2>
        <button @click="exportData" class="btn-secondary">
          导出数据
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-2">时间</th>
              <th class="pb-2">套利类型</th>
              <th class="pb-2">正向点差</th>
              <th class="pb-2">反向点差</th>
              <th class="pb-2">Binance买/卖</th>
              <th class="pb-2">Bybit买/卖</th>
              <th class="pb-2">目标点差</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in paginatedRecords" :key="record.id" class="border-b border-gray-800">
              <td class="py-3">{{ formatDateTimeBeijing(record.timestamp) }}</td>
              <td>
                <span v-if="record.opportunity_type === 'forward_open'" class="px-2 py-1 bg-green-900 text-green-300 rounded text-xs">
                  正向开仓
                </span>
                <span v-else-if="record.opportunity_type === 'forward_close'" class="px-2 py-1 bg-blue-900 text-blue-300 rounded text-xs">
                  正向平仓
                </span>
                <span v-else-if="record.opportunity_type === 'reverse_open'" class="px-2 py-1 bg-orange-900 text-orange-300 rounded text-xs">
                  反向开仓
                </span>
                <span v-else-if="record.opportunity_type === 'reverse_close'" class="px-2 py-1 bg-purple-900 text-purple-300 rounded text-xs">
                  反向平仓
                </span>
              </td>
              <td :class="record.forward_spread >= 2.0 ? 'text-green-500' : record.forward_spread <= -2.0 ? 'text-red-500' : 'text-gray-400'">
                {{ record.forward_spread.toFixed(2) }}
              </td>
              <td :class="record.reverse_spread >= 2.0 ? 'text-green-500' : record.reverse_spread <= -2.0 ? 'text-red-500' : 'text-gray-400'">
                {{ record.reverse_spread.toFixed(2) }}
              </td>
              <td class="text-sm">
                <span class="text-green-500">{{ record.binance_bid.toFixed(2) }}</span> /
                <span class="text-red-500">{{ record.binance_ask.toFixed(2) }}</span>
              </td>
              <td class="text-sm">
                <span class="text-green-500">{{ record.bybit_bid.toFixed(2) }}</span> /
                <span class="text-red-500">{{ record.bybit_ask.toFixed(2) }}</span>
              </td>
              <td class="text-gray-400">{{ record.target_spread.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex justify-between items-center mt-4">
        <div class="text-sm text-gray-400">
          显示 {{ (currentPage - 1) * pageSize + 1 }} - {{ Math.min(currentPage * pageSize, spreadRecords.length) }}
          / 共 {{ spreadRecords.length }} 条
        </div>
        <div class="flex gap-2">
          <button @click="currentPage--" :disabled="currentPage === 1"
                  class="btn-secondary disabled:opacity-50 disabled:cursor-not-allowed">
            上一页
          </button>
          <button @click="currentPage++" :disabled="currentPage >= totalPages"
                  class="btn-secondary disabled:opacity-50 disabled:cursor-not-allowed">
            下一页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Chart, registerables } from 'chart.js'
import api from '@/services/api'
import { formatDateTimeBeijing, formatTimeBeijing } from '@/utils/timeUtils'

Chart.register(...registerables)

// Query Controls
const queryType = ref('recent')
const selectedDate = ref(new Date().toISOString().split('T')[0])
const selectedWeek = ref('')
const selectedMonth = ref('')
const startDate = ref('')
const endDate = ref('')
const opportunityType = ref('') // 套利类型筛选
const loading = ref(false)

// Data
const spreadRecords = ref([])
const currentPage = ref(1)
const pageSize = ref(20)

// Chart References
const forwardChartRef = ref(null)
const reverseChartRef = ref(null)
let forwardChart = null
let reverseChart = null

// Check if current time is weekend (Saturday or Sunday)
const isWeekend = computed(() => {
  const now = new Date()
  const day = now.getDay() // 0=Sunday, 6=Saturday
  return day === 0 || day === 6
})

// Computed Statistics
const forwardOpenCount = computed(() => {
  return spreadRecords.value.filter(r => r.opportunity_type === 'forward_open').length
})

const forwardCloseCount = computed(() => {
  return spreadRecords.value.filter(r => r.opportunity_type === 'forward_close').length
})

const reverseOpenCount = computed(() => {
  return spreadRecords.value.filter(r => r.opportunity_type === 'reverse_open').length
})

const reverseCloseCount = computed(() => {
  return spreadRecords.value.filter(r => r.opportunity_type === 'reverse_close').length
})

const averageSpread = computed(() => {
  if (spreadRecords.value.length === 0) return 0
  const sum = spreadRecords.value.reduce((acc, r) => acc + Math.abs(r.forward_spread) + Math.abs(r.reverse_spread), 0)
  return sum / (spreadRecords.value.length * 2)
})

const maxSpread = computed(() => {
  if (spreadRecords.value.length === 0) return 0
  return Math.max(...spreadRecords.value.map(r => Math.max(Math.abs(r.forward_spread), Math.abs(r.reverse_spread))))
})

const minSpread = computed(() => {
  if (spreadRecords.value.length === 0) return 0
  return Math.min(...spreadRecords.value.map(r => Math.min(Math.abs(r.forward_spread), Math.abs(r.reverse_spread))))
})

const totalPages = computed(() => Math.ceil(spreadRecords.value.length / pageSize.value))

const paginatedRecords = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return spreadRecords.value.slice(start, end)
})

// Initialize
onMounted(() => {
  querySpreadData()
})

onUnmounted(() => {
  if (forwardChart) forwardChart.destroy()
  if (reverseChart) reverseChart.destroy()
})

// Watch for data changes to update charts
watch(spreadRecords, () => {
  updateCharts()
}, { deep: true })

// Functions
function handleQueryTypeChange() {
  const today = new Date()
  if (queryType.value === 'day') {
    selectedDate.value = today.toISOString().split('T')[0]
  } else if (queryType.value === 'week') {
    const year = today.getFullYear()
    const week = getWeekNumber(today)
    selectedWeek.value = `${year}-W${week.toString().padStart(2, '0')}`
  } else if (queryType.value === 'month') {
    selectedMonth.value = `${today.getFullYear()}-${(today.getMonth() + 1).toString().padStart(2, '0')}`
  }
}

function getWeekNumber(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
  const dayNum = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7)
}

async function querySpreadData() {
  console.log('querySpreadData called, queryType:', queryType.value)
  console.log('startDate:', startDate.value, 'endDate:', endDate.value)

  try {
    loading.value = true
    // Calculate start and end time based on query type
    let start_time, end_time

    if (queryType.value === 'recent') {
      // Query for last 2 hours
      const now = new Date()
      const twoHoursAgo = new Date(now.getTime() - 2 * 60 * 60 * 1000)
      start_time = twoHoursAgo.toISOString()
      end_time = now.toISOString()
    } else if (queryType.value === 'day') {
      // Query for selected day (use UTC to avoid timezone issues)
      const dateStr = selectedDate.value
      start_time = `${dateStr}T00:00:00.000Z`
      end_time = `${dateStr}T23:59:59.999Z`
    } else if (queryType.value === 'custom') {
      // Query for custom date range
      console.log('Custom query - startDate:', startDate.value, 'endDate:', endDate.value)

      if (!startDate.value || !endDate.value) {
        alert('请选择开始时间和结束时间')
        loading.value = false
        return
      }

      const start = new Date(startDate.value)
      const end = new Date(endDate.value)
      console.log('Parsed dates - start:', start, 'end:', end)

      const daysDiff = (end - start) / (1000 * 60 * 60 * 24)
      console.log('Days difference:', daysDiff)

      // Warn if custom range is more than 7 days
      if (daysDiff > 7 && !confirm(`您选择的时间跨度为${daysDiff.toFixed(1)}天，数据量可能较大，查询可能需要较长时间，是否继续？`)) {
        loading.value = false
        return
      }

      start_time = `${startDate.value}:00`
      end_time = `${endDate.value}:59`
      console.log('ISO times - start_time:', start_time, 'end_time:', end_time)
    }

    // Fetch arbitrage opportunities from new API
    const params = {
      start_time,
      end_time,
      symbol: 'XAUUSD',
      limit: 10000
    }

    // Add opportunity type filter if selected
    if (opportunityType.value) {
      params.opportunity_type = opportunityType.value
    }

    const response = await api.get('/api/v1/opportunities', {
      params,
      timeout: 60000 // 60 seconds timeout for large data queries
    })

    // Show warning if data count is large
    if (response.data.length > 5000) {
      alert(`查询返回${response.data.length}条记录，数据量较大，页面渲染可能需要一些时间`)
    }

    // Map the response data to the expected format
    spreadRecords.value = response.data.map((item) => ({
      id: item.id,
      timestamp: item.timestamp,
      opportunity_type: item.opportunity_type,
      forward_spread: item.forward_spread || 0,
      reverse_spread: item.reverse_spread || 0,
      binance_bid: item.binance_bid || 0,
      binance_ask: item.binance_ask || 0,
      bybit_bid: item.bybit_bid || 0,
      bybit_ask: item.bybit_ask || 0,
      target_spread: item.target_spread || 0
    }))

    currentPage.value = 1
  } catch (error) {
    console.error('Failed to query arbitrage opportunities:', error)
    alert('获取套利机会数据失败: ' + (error.response?.data?.detail || error.message))
    spreadRecords.value = []
  } finally {
    loading.value = false
  }
}

function getFirstDayOfWeek(year, week) {
  const jan4 = new Date(year, 0, 4)
  const jan4Day = jan4.getDay() || 7
  const firstMonday = new Date(jan4)
  firstMonday.setDate(jan4.getDate() - jan4Day + 1)
  const targetDate = new Date(firstMonday)
  targetDate.setDate(firstMonday.getDate() + (week - 1) * 7)
  return targetDate
}

function updateCharts() {
  if (spreadRecords.value.length === 0) return

  const labels = spreadRecords.value.map(r => formatTimeBeijing(r.timestamp))
  const forwardData = spreadRecords.value.map(r => r.forward_spread)
  const reverseData = spreadRecords.value.map(r => r.reverse_spread)

  // Forward Chart
  if (forwardChart) forwardChart.destroy()
  if (forwardChartRef.value) {
    forwardChart = new Chart(forwardChartRef.value, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '正向开仓点差 (Bybit卖-Binance买)',
          data: forwardData,
          borderColor: 'rgb(34, 197, 94)',
          backgroundColor: 'rgba(34, 197, 94, 0.1)',
          tension: 0.4,
          fill: true
        }, {
          label: '套利阈值',
          data: Array(labels.length).fill(2.0),
          borderColor: 'rgb(239, 68, 68)',
          borderDash: [5, 5],
          pointRadius: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            labels: { color: '#9ca3af' }
          }
        },
        scales: {
          x: {
            ticks: { color: '#9ca3af', maxTicksLimit: 10 },
            grid: { color: '#374151' }
          },
          y: {
            ticks: { color: '#9ca3af' },
            grid: { color: '#374151' }
          }
        }
      }
    })
  }

  // Reverse Chart
  if (reverseChart) reverseChart.destroy()
  if (reverseChartRef.value) {
    reverseChart = new Chart(reverseChartRef.value, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '反向开仓点差 (Binance卖-Bybit卖)',
          data: reverseData,
          borderColor: 'rgb(239, 68, 68)',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          tension: 0.4,
          fill: true
        }, {
          label: '套利阈值',
          data: Array(labels.length).fill(2.0),
          borderColor: 'rgb(34, 197, 94)',
          borderDash: [5, 5],
          pointRadius: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            labels: { color: '#9ca3af' }
          }
        },
        scales: {
          x: {
            ticks: { color: '#9ca3af', maxTicksLimit: 10 },
            grid: { color: '#374151' }
          },
          y: {
            ticks: { color: '#9ca3af' },
            grid: { color: '#374151' }
          }
        }
      }
    })
  }
}

function exportData() {
  const csv = [
    ['时间', '套利类型', '正向点差', '反向点差', 'Binance买价', 'Binance卖价', 'Bybit买价', 'Bybit卖价', '目标点差'],
    ...spreadRecords.value.map(r => [
      formatDateTimeBeijing(r.timestamp),
      r.opportunity_type === 'forward_open' ? '正向开仓' :
      r.opportunity_type === 'forward_close' ? '正向平仓' :
      r.opportunity_type === 'reverse_open' ? '反向开仓' :
      r.opportunity_type === 'reverse_close' ? '反向平仓' : '',
      r.forward_spread.toFixed(2),
      r.reverse_spread.toFixed(2),
      r.binance_bid.toFixed(2),
      r.binance_ask.toFixed(2),
      r.bybit_bid.toFixed(2),
      r.bybit_ask.toFixed(2),
      r.target_spread.toFixed(2)
    ])
  ].map(row => row.join(',')).join('\n')

  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `arbitrage_opportunities_${new Date().toISOString().split('T')[0]}.csv`
  link.click()
}
</script>
