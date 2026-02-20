<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">点差记录分析</h1>

    <!-- Query Controls -->
    <div class="card mb-6">
      <h2 class="text-xl font-semibold mb-4">查询条件</h2>
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <!-- Query Type -->
        <div>
          <label class="block text-sm text-gray-400 mb-2">查询类型</label>
          <select v-model="queryType" @change="handleQueryTypeChange"
                  class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
            <option value="day">按日</option>
            <option value="week">按周</option>
            <option value="month">按月</option>
            <option value="custom">自定义时间段</option>
          </select>
        </div>

        <!-- Date Selection -->
        <div v-if="queryType === 'day'">
          <label class="block text-sm text-gray-400 mb-2">选择日期</label>
          <input type="date" v-model="selectedDate"
                 class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <div v-if="queryType === 'week'">
          <label class="block text-sm text-gray-400 mb-2">选择周</label>
          <input type="week" v-model="selectedWeek"
                 class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <div v-if="queryType === 'month'">
          <label class="block text-sm text-gray-400 mb-2">选择月份</label>
          <input type="month" v-model="selectedMonth"
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
          <button @click="querySpreadData" class="btn-primary w-full">
            查询
          </button>
        </div>
      </div>
    </div>

    <!-- Statistics Overview -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">总记录数</div>
        <div class="text-2xl font-bold">{{ spreadRecords.length }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">平均点差</div>
        <div class="text-2xl font-bold">{{ averageSpread.toFixed(2) }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">最大点差</div>
        <div class="text-2xl font-bold text-red-500">{{ maxSpread.toFixed(2) }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">最小点差</div>
        <div class="text-2xl font-bold text-green-500">{{ minSpread.toFixed(2) }}</div>
      </div>
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Forward Arbitrage Chart -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">正向套利线性分析</h3>
        <canvas ref="forwardChartRef"></canvas>
      </div>

      <!-- Reverse Arbitrage Chart -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">反向套利线性分析</h3>
        <canvas ref="reverseChartRef"></canvas>
      </div>
    </div>

    <!-- Spread Records Table -->
    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-semibold">点差记录列表</h2>
        <button @click="exportData" class="btn-secondary">
          导出数据
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-2">时间</th>
              <th class="pb-2">正向点差</th>
              <th class="pb-2">反向点差</th>
              <th class="pb-2">Binance买/卖</th>
              <th class="pb-2">Bybit买/卖</th>
              <th class="pb-2">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in paginatedRecords" :key="record.id" class="border-b border-gray-800">
              <td class="py-3">{{ formatDateTime(record.timestamp) }}</td>
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
              <td>
                <span v-if="Math.abs(record.forward_spread) >= 2.0 || Math.abs(record.reverse_spread) >= 2.0"
                      class="px-2 py-1 bg-green-900 text-green-300 rounded text-xs">
                  可套利
                </span>
                <span v-else class="px-2 py-1 bg-gray-700 text-gray-400 rounded text-xs">
                  正常
                </span>
              </td>
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

Chart.register(...registerables)

// Query Controls
const queryType = ref('day')
const selectedDate = ref(new Date().toISOString().split('T')[0])
const selectedWeek = ref('')
const selectedMonth = ref('')
const startDate = ref('')
const endDate = ref('')

// Data
const spreadRecords = ref([])
const currentPage = ref(1)
const pageSize = ref(20)

// Chart References
const forwardChartRef = ref(null)
const reverseChartRef = ref(null)
let forwardChart = null
let reverseChart = null

// Computed Statistics
const averageSpread = computed(() => {
  if (spreadRecords.value.length === 0) return 0
  const sum = spreadRecords.value.reduce((acc, r) => acc + r.forward_spread + r.reverse_spread, 0)
  return sum / (spreadRecords.value.length * 2)
})

const maxSpread = computed(() => {
  if (spreadRecords.value.length === 0) return 0
  return Math.max(...spreadRecords.value.map(r => Math.max(r.forward_spread, r.reverse_spread)))
})

const minSpread = computed(() => {
  if (spreadRecords.value.length === 0) return 0
  return Math.min(...spreadRecords.value.map(r => Math.min(r.forward_spread, r.reverse_spread)))
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
  try {
    // Calculate start and end time based on query type
    let start_time, end_time

    if (queryType.value === 'day') {
      // Query for selected day
      const startDate = new Date(selectedDate.value)
      startDate.setHours(0, 0, 0, 0)
      start_time = startDate.toISOString()

      const endDate = new Date(selectedDate.value)
      endDate.setHours(23, 59, 59, 999)
      end_time = endDate.toISOString()
    } else if (queryType.value === 'week') {
      // Query for selected week
      const [year, week] = selectedWeek.value.split('-W')
      const firstDay = getFirstDayOfWeek(parseInt(year), parseInt(week))
      firstDay.setHours(0, 0, 0, 0)
      start_time = firstDay.toISOString()

      const lastDay = new Date(firstDay)
      lastDay.setDate(lastDay.getDate() + 6)
      lastDay.setHours(23, 59, 59, 999)
      end_time = lastDay.toISOString()
    } else if (queryType.value === 'month') {
      // Query for selected month
      const [year, month] = selectedMonth.value.split('-')
      const startDate = new Date(parseInt(year), parseInt(month) - 1, 1, 0, 0, 0, 0)
      start_time = startDate.toISOString()

      const endDate = new Date(parseInt(year), parseInt(month), 0, 23, 59, 59, 999)
      end_time = endDate.toISOString()
    } else if (queryType.value === 'custom') {
      // Query for custom date range
      if (!startDate.value || !endDate.value) {
        alert('请选择开始时间和结束时间')
        return
      }
      start_time = new Date(startDate.value).toISOString()
      end_time = new Date(endDate.value).toISOString()
    }

    // Fetch spread records from database
    const response = await api.get('/api/v1/market/spread/history', {
      params: {
        start_time,
        end_time,
        binance_symbol: 'XAUUSDT',
        bybit_symbol: 'XAUUSDT'
      }
    })

    // Map the response data to the expected format
    spreadRecords.value = response.data.map((item, index) => ({
      id: item.id || index + 1,
      timestamp: item.timestamp,
      forward_spread: item.forward_spread || 0,
      reverse_spread: item.reverse_spread || 0,
      binance_bid: item.binance_quote?.bid || 0,
      binance_ask: item.binance_quote?.ask || 0,
      bybit_bid: item.bybit_quote?.bid || 0,
      bybit_ask: item.bybit_quote?.ask || 0
    }))

    currentPage.value = 1
  } catch (error) {
    console.error('Failed to query spread data:', error)
    alert('获取点差数据失败: ' + (error.response?.data?.detail || error.message))
    spreadRecords.value = []
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

  const labels = spreadRecords.value.map(r => formatTime(r.timestamp))
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
          label: '正向点差',
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
          label: '反向点差',
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

function formatDateTime(timestamp) {
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function formatTime(timestamp) {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

function exportData() {
  const csv = [
    ['时间', '正向点差', '反向点差', 'Binance买价', 'Binance卖价', 'Bybit买价', 'Bybit卖价'],
    ...spreadRecords.value.map(r => [
      formatDateTime(r.timestamp),
      r.forward_spread.toFixed(2),
      r.reverse_spread.toFixed(2),
      r.binance_bid.toFixed(2),
      r.binance_ask.toFixed(2),
      r.bybit_bid.toFixed(2),
      r.bybit_ask.toFixed(2)
    ])
  ].map(row => row.join(',')).join('\n')

  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `spread_records_${new Date().toISOString().split('T')[0]}.csv`
  link.click()
}
</script>
