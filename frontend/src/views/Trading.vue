<template>
  <div class="container mx-auto px-4 py-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-3xl font-bold">交易历史数据</h1>
      <div class="flex items-center gap-2">
        <span class="text-sm text-gray-400">套利组合总盈亏:</span>
        <span class="text-2xl font-bold" :class="totalArbitragePnL >= 0 ? 'text-green-500' : 'text-red-500'">
          {{ totalArbitragePnL >= 0 ? '+' : '' }}{{ totalArbitragePnL.toFixed(2) }} USDT
        </span>
      </div>
    </div>

    <!-- Query Controls -->
    <div class="card mb-6">
      <div class="flex flex-wrap items-center gap-4">
        <!-- DateTime Range Selector -->
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">开始时间 (北京时间):</label>
          <input type="datetime-local" v-model="startTime"
                 class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">结束时间 (北京时间):</label>
          <input type="datetime-local" v-model="endTime"
                 class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <!-- Query Button -->
        <button @click="queryData" class="btn-primary" :disabled="loading">
          {{ loading ? '查询中...' : '查询' }}
        </button>

        <!-- Show Recent 1 Day Button -->
        <button @click="showRecentDays(1)" class="btn-secondary" :disabled="loading">
          最近1天
        </button>

        <!-- Show Recent 7 Days Button -->
        <button @click="showRecentDays(7)" class="btn-secondary" :disabled="loading">
          最近7天
        </button>

        <!-- Show Recent 30 Days Button -->
        <button @click="showRecentDays(30)" class="btn-secondary" :disabled="loading">
          最近30天
        </button>

        <!-- Export Dropdown -->
        <div class="relative" v-if="hasData">
          <button @click="showExportMenu = !showExportMenu" class="btn-secondary flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            导出数据
          </button>
          <div v-if="showExportMenu" class="absolute right-0 mt-2 w-48 bg-dark-100 border border-border-primary rounded shadow-lg z-10">
            <button @click="exportData('csv')" class="w-full text-left px-4 py-2 hover:bg-dark-200 transition-colors">
              导出为 CSV
            </button>
            <button @click="exportData('xlsx')" class="w-full text-left px-4 py-2 hover:bg-dark-200 transition-colors">
              导出为 Excel (XLSX)
            </button>
            <button @click="exportData('pdf')" class="w-full text-left px-4 py-2 hover:bg-dark-200 transition-colors">
              导出为 PDF
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Statistics Section -->
    <div class="card mb-6">
      <!-- No Data Message -->
      <div v-if="!hasData" class="text-center py-12">
        <div class="text-gray-400 text-lg mb-2">暂无交易数据</div>
        <div class="text-gray-500 text-sm">请选择日期查询或点击"显示全部"查看所有数据</div>
      </div>

      <!-- Statistics Content -->
      <div v-else>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Left Column Statistics -->
        <div class="space-y-4">
          <h3 class="text-lg font-semibold mb-4 border-b border-gray-700 pb-2">Binance账户成交历史</h3>

          <div class="grid grid-cols-2 gap-4">
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交量汇总</div>
              <div class="text-lg font-bold">{{ stats.totalVolume.toFixed(2) }}</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额汇总</div>
              <div class="text-lg font-bold">{{ stats.totalAmount.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额(吃单)</div>
              <div class="text-lg font-bold">{{ stats.takerAmount.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额(挂单)</div>
              <div class="text-lg font-bold">{{ stats.makerAmount.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">手续费汇总(USDT)</div>
              <div class="text-lg font-bold text-red-500">{{ stats.totalFees.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">手续费汇总(BNB)</div>
              <div class="text-lg font-bold text-red-500">{{ stats.bnbFees.toFixed(4) }} BNB</div>
            </div>
            <div class="bg-gray-800 p-3 rounded col-span-2">
              <div class="text-xs text-gray-400 mb-1">已实现盈亏</div>
              <div class="text-lg font-bold" :class="(stats.realizedPnL || 0) >= 0 ? 'text-green-500' : 'text-red-500'">
                {{ (stats.realizedPnL || 0) >= 0 ? '+' : '' }}{{ (stats.realizedPnL || 0).toFixed(2) }} USDT
              </div>
            </div>
          </div>
        </div>

        <!-- Right Column Statistics -->
        <div class="space-y-4">
          <h3 class="text-lg font-semibold mb-4 border-b border-gray-700 pb-2">Bybit MT5成交历史</h3>

          <div class="grid grid-cols-2 gap-4">
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交量汇总</div>
              <div class="text-lg font-bold">{{ stats.mt5Volume.toFixed(2) }}</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额汇总</div>
              <div class="text-lg font-bold">{{ stats.mt5Amount.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">MT5过夜费</div>
              <div class="text-lg font-bold text-red-500">{{ stats.mt5OvernightFee.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">MT5手续费</div>
              <div class="text-lg font-bold text-red-500">{{ stats.mt5Fee.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded col-span-2">
              <div class="text-xs text-gray-400 mb-1">MT5已实现盈亏</div>
              <div class="text-lg font-bold" :class="(stats.mt5RealizedPnL || 0) >= 0 ? 'text-green-500' : 'text-red-500'">
                {{ (stats.mt5RealizedPnL || 0) >= 0 ? '+' : '' }}{{ (stats.mt5RealizedPnL || 0).toFixed(2) }} USDT
              </div>
            </div>
          </div>
        </div>
      </div>
      </div>
    </div>

    <!-- Trading History Tables -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Account Trading History Table -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">Binance账户成交历史</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-gray-400 border-b border-gray-700">
                <th class="pb-2">交易对</th>
                <th class="pb-2">方向</th>
                <th class="pb-2">成交价</th>
                <th class="pb-2">成交量</th>
                <th class="pb-2">成交额</th>
                <th class="pb-2">类别</th>
                <th class="pb-2">时间 (北京)</th>
                <th class="pb-2">手续费</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="accountTrades.length === 0">
                <td colspan="8" class="text-center py-8 text-gray-500">暂无数据</td>
              </tr>
              <tr v-for="trade in accountTrades" :key="trade.id" class="border-b border-gray-800">
                <td class="py-3">{{ trade.symbol }}</td>
                <td>
                  <span :class="trade.side === 'buy' ? 'text-green-500' : 'text-red-500'">
                    {{ trade.side === 'buy' ? '买入' : '卖出' }}
                  </span>
                </td>
                <td>{{ trade.price != null ? Number(trade.price).toFixed(2) : '-' }} USDT</td>
                <td>{{ trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-' }}</td>
                <td>{{ trade.amount != null ? Number(trade.amount).toFixed(2) : '-' }} USDT</td>
                <td class="text-xs">
                  <span :class="trade.maker ? 'text-blue-500' : 'text-orange-500'">
                    {{ trade.maker ? '挂单' : '吃单' }}
                  </span>
                </td>
                <td class="text-xs text-gray-400">{{ formatDateTime(trade.timestamp) }}</td>
                <td class="text-red-500">{{ trade.fee != null ? Number(trade.fee).toFixed(2) : '-' }} USDT</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- MT5 Trading History Table -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">Bybit MT5成交历史</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-gray-400 border-b border-gray-700">
                <th class="pb-2">交易对</th>
                <th class="pb-2">方向</th>
                <th class="pb-2">成交价</th>
                <th class="pb-2">成交量</th>
                <th class="pb-2">成交额</th>
                <th class="pb-2">过夜费</th>
                <th class="pb-2">时间 (北京)</th>
                <th class="pb-2">手续费</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="mt5Trades.length === 0">
                <td colspan="8" class="text-center py-8 text-gray-500">暂无数据</td>
              </tr>
              <tr v-for="trade in mt5Trades" :key="trade.id" class="border-b border-gray-800">
                <td class="py-3">{{ trade.symbol }}</td>
                <td>
                  <span :class="trade.side === 'buy' ? 'text-green-500' : 'text-red-500'">
                    {{ trade.side === 'buy' ? '买入' : '卖出' }}
                  </span>
                </td>
                <td>{{ trade.price != null ? Number(trade.price).toFixed(2) : '-' }} USDT</td>
                <td>{{ trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-' }}</td>
                <td>{{ trade.amount != null ? Number(trade.amount).toFixed(2) : '-' }} USDT</td>
                <td class="text-red-500">{{ trade.overnight_fee != null ? Number(trade.overnight_fee).toFixed(2) : '0.00' }} USDT</td>
                <td class="text-xs text-gray-400">{{ formatDateTime(trade.timestamp) }}</td>
                <td class="text-red-500">{{ trade.fee != null ? Number(trade.fee).toFixed(2) : '-' }} USDT</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/services/api'
import * as XLSX from 'xlsx'
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'

// Query Controls
const startTime = ref('')
const endTime = ref('')
const loading = ref(false)
const showExportMenu = ref(false)

// Initialize with today's date range (00:00:00 to 23:59:59)
function initializeDateRange() {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')

  startTime.value = `${year}-${month}-${day}T00:00`
  endTime.value = `${year}-${month}-${day}T23:59`
}

// Statistics Data
const stats = ref({
  totalVolume: 0,
  totalAmount: 0,
  takerAmount: 0,
  makerAmount: 0,
  bnbFees: 0,
  buySellAmount: 0,
  taskAmount: 0,
  totalFees: 0,
  realizedPnL: 0,
  overnightFees: 0,
  marketFundingRate: 0,
  mt5OvernightFee: 0,
  mt5Volume: 0,
  mt5Amount: 0,
  marketFee: 0,
  mt5Fee: 0,
  mt5RealizedPnL: 0,
  peRatio: 0,
  mt5TodayReturn: 0,
  totalReturnProfit: 0
})

// Trading History Data
const accountTrades = ref([])
const mt5Trades = ref([])

// Computed Net Profit
const netProfit = computed(() => {
  return stats.value.totalReturnProfit - stats.value.totalFees - stats.value.overnightFees
})

// Computed Total Arbitrage PnL (MT5 + Binance)
const totalArbitragePnL = computed(() => {
  return (stats.value.mt5RealizedPnL || 0) + (stats.value.realizedPnL || 0)
})

// Check if there's any data
const hasData = computed(() => {
  return accountTrades.value.length > 0 || mt5Trades.value.length > 0
})

// Functions
async function queryData() {
  try {
    // Validate datetime inputs
    if (!startTime.value || !endTime.value) {
      alert('请选择开始时间和结束时间')
      return
    }

    loading.value = true

    // Convert datetime-local format to "YYYY-MM-DD HH:MM:SS"
    const startTimeStr = startTime.value.replace('T', ' ') + ':00'
    const endTimeStr = endTime.value.replace('T', ' ') + ':59'

    const response = await api.get('/api/v1/trading/history/realtime', {
      params: {
        start_time: startTimeStr,
        end_time: endTimeStr
      }
    })
    updateData(response.data)
  } catch (error) {
    console.error('Failed to query trading data:', error)
    alert('查询失败: ' + (error.response?.data?.detail || error.message))
    clearData()
  } finally {
    loading.value = false
  }
}

async function showRecentDays(days) {
  try {
    loading.value = true

    const now = new Date()
    const endDate = new Date(now)
    const startDate = new Date(now)
    startDate.setDate(startDate.getDate() - days)

    // Format as "YYYY-MM-DD HH:MM:SS"
    const formatDateTime = (date) => {
      const year = date.getFullYear()
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hours = String(date.getHours()).padStart(2, '0')
      const minutes = String(date.getMinutes()).padStart(2, '0')
      const seconds = String(date.getSeconds()).padStart(2, '0')
      return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
    }

    const startTimeStr = formatDateTime(startDate)
    const endTimeStr = formatDateTime(endDate)

    // Update the datetime inputs
    startTime.value = startTimeStr.replace(' ', 'T').substring(0, 16)
    endTime.value = endTimeStr.replace(' ', 'T').substring(0, 16)

    const response = await api.get('/api/v1/trading/history/realtime', {
      params: {
        start_time: startTimeStr,
        end_time: endTimeStr
      }
    })
    updateData(response.data)
  } catch (error) {
    console.error('Failed to query recent data:', error)
    alert('查询失败: ' + (error.response?.data?.detail || error.message))
    clearData()
  } finally {
    loading.value = false
  }
}

function updateData(data) {
  if (data.stats) {
    stats.value = { ...stats.value, ...data.stats }
  }
  if (data.accountTrades) {
    // Sort by timestamp descending (newest first)
    accountTrades.value = data.accountTrades.sort((a, b) => {
      const timeA = new Date(a.timestamp).getTime()
      const timeB = new Date(b.timestamp).getTime()
      return timeB - timeA
    })
  }
  if (data.mt5Trades) {
    // Sort by timestamp descending (newest first)
    mt5Trades.value = data.mt5Trades.sort((a, b) => {
      const timeA = new Date(a.timestamp).getTime()
      const timeB = new Date(b.timestamp).getTime()
      return timeB - timeA
    })
  }
}

function clearData() {
  stats.value = {
    totalVolume: 0,
    totalAmount: 0,
    takerAmount: 0,
    makerAmount: 0,
    bnbFees: 0,
    buySellAmount: 0,
    taskAmount: 0,
    totalFees: 0,
    realizedPnL: 0,
    overnightFees: 0,
    marketFundingRate: 0,
    mt5OvernightFee: 0,
    mt5Volume: 0,
    mt5Amount: 0,
    marketFee: 0,
    mt5Fee: 0,
    mt5RealizedPnL: 0,
    peRatio: 0,
    mt5TodayReturn: 0,
    totalReturnProfit: 0
  }
  accountTrades.value = []
  mt5Trades.value = []
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  // Timestamp is already in Beijing time format from backend
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

// Export functions
function exportData(format) {
  showExportMenu.value = false

  if (!hasData.value) {
    alert('没有数据可导出')
    return
  }

  const timestamp = new Date().toISOString().split('T')[0]
  const filename = `trading_history_${timestamp}`

  if (format === 'csv') {
    exportToCSV(filename)
  } else if (format === 'xlsx') {
    exportToExcel(filename)
  } else if (format === 'pdf') {
    exportToPDF(filename)
  }
}

function exportToCSV(filename) {
  const binanceHeaders = ['交易对', '方向', '成交价', '成交量', '成交额', '类别', '时间', '手续费']
  const binanceRows = accountTrades.value.map(trade => [
    trade.symbol,
    trade.side === 'buy' ? '买入' : '卖出',
    trade.price != null ? Number(trade.price).toFixed(2) : '-',
    trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-',
    trade.amount != null ? Number(trade.amount).toFixed(2) : '-',
    trade.maker ? '挂单' : '吃单',
    formatDateTime(trade.timestamp),
    trade.fee != null ? Number(trade.fee).toFixed(2) : '-'
  ])

  const mt5Headers = ['交易对', '方向', '成交价', '成交量', '成交额', '过夜费', '时间', '手续费']
  const mt5Rows = mt5Trades.value.map(trade => [
    trade.symbol,
    trade.side === 'buy' ? '买入' : '卖出',
    trade.price != null ? Number(trade.price).toFixed(2) : '-',
    trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-',
    trade.amount != null ? Number(trade.amount).toFixed(2) : '-',
    trade.overnight_fee != null ? Number(trade.overnight_fee).toFixed(2) : '0.00',
    formatDateTime(trade.timestamp),
    trade.fee != null ? Number(trade.fee).toFixed(2) : '-'
  ])

  const csvContent = [
    ['交易历史数据报告'],
    [`查询时间: ${startTime.value} 至 ${endTime.value}`],
    [],
    ['=== Binance账户统计 ==='],
    ['成交量汇总', stats.value.totalVolume?.toFixed(2) || '0.00'],
    ['成交额汇总', (stats.value.totalAmount?.toFixed(2) || '0.00') + ' USDT'],
    ['成交额(吃单)', (stats.value.takerAmount?.toFixed(2) || '0.00') + ' USDT'],
    ['成交额(挂单)', (stats.value.makerAmount?.toFixed(2) || '0.00') + ' USDT'],
    ['手续费汇总(USDT)', (stats.value.totalFees?.toFixed(2) || '0.00') + ' USDT'],
    ['手续费汇总(BNB)', (stats.value.bnbFees?.toFixed(4) || '0.0000') + ' BNB'],
    ['已实现盈亏', (stats.value.realizedPnL?.toFixed(2) || '0.00') + ' USDT'],
    [],
    ['=== Bybit MT5统计 ==='],
    ['成交量汇总', stats.value.mt5Volume?.toFixed(2) || '0.00'],
    ['成交额汇总', (stats.value.mt5Amount?.toFixed(2) || '0.00') + ' USDT'],
    ['MT5过夜费', (stats.value.mt5OvernightFee?.toFixed(2) || '0.00') + ' USDT'],
    ['MT5手续费', (stats.value.mt5Fee?.toFixed(2) || '0.00') + ' USDT'],
    ['MT5已实现盈亏', (stats.value.mt5RealizedPnL?.toFixed(2) || '0.00') + ' USDT'],
    [],
    ['=== Binance账户成交历史 ==='],
    binanceHeaders,
    ...binanceRows,
    [],
    ['=== Bybit MT5成交历史 ==='],
    mt5Headers,
    ...mt5Rows
  ].map(row => row.join(',')).join('\n')

  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${filename}.csv`
  link.click()
}

function exportToExcel(filename) {
  const wb = XLSX.utils.book_new()

  // Statistics sheet
  const statsData = [
    ['交易历史数据报告'],
    [`查询时间: ${startTime.value} 至 ${endTime.value}`],
    [],
    ['Binance账户统计', ''],
    ['成交量汇总', stats.value.totalVolume?.toFixed(2) || '0.00'],
    ['成交额汇总', (stats.value.totalAmount?.toFixed(2) || '0.00') + ' USDT'],
    ['成交额(吃单)', (stats.value.takerAmount?.toFixed(2) || '0.00') + ' USDT'],
    ['成交额(挂单)', (stats.value.makerAmount?.toFixed(2) || '0.00') + ' USDT'],
    ['手续费汇总(USDT)', (stats.value.totalFees?.toFixed(2) || '0.00') + ' USDT'],
    ['手续费汇总(BNB)', (stats.value.bnbFees?.toFixed(4) || '0.0000') + ' BNB'],
    ['已实现盈亏', (stats.value.realizedPnL?.toFixed(2) || '0.00') + ' USDT'],
    [],
    ['Bybit MT5统计', ''],
    ['成交量汇总', stats.value.mt5Volume?.toFixed(2) || '0.00'],
    ['成交额汇总', (stats.value.mt5Amount?.toFixed(2) || '0.00') + ' USDT'],
    ['MT5过夜费', (stats.value.mt5OvernightFee?.toFixed(2) || '0.00') + ' USDT'],
    ['MT5手续费', (stats.value.mt5Fee?.toFixed(2) || '0.00') + ' USDT'],
    ['MT5已实现盈亏', (stats.value.mt5RealizedPnL?.toFixed(2) || '0.00') + ' USDT']
  ]
  const statsSheet = XLSX.utils.aoa_to_sheet(statsData)
  XLSX.utils.book_append_sheet(wb, statsSheet, '统计数据')

  // Binance sheet
  const binanceData = [
    ['交易对', '方向', '成交价', '成交量', '成交额', '类别', '时间', '手续费'],
    ...accountTrades.value.map(trade => [
      trade.symbol,
      trade.side === 'buy' ? '买入' : '卖出',
      trade.price != null ? Number(trade.price).toFixed(2) : '-',
      trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-',
      trade.amount != null ? Number(trade.amount).toFixed(2) : '-',
      trade.maker ? '挂单' : '吃单',
      formatDateTime(trade.timestamp),
      trade.fee != null ? Number(trade.fee).toFixed(2) : '-'
    ])
  ]
  const binanceSheet = XLSX.utils.aoa_to_sheet(binanceData)
  XLSX.utils.book_append_sheet(wb, binanceSheet, 'Binance成交历史')

  // MT5 sheet
  const mt5Data = [
    ['交易对', '方向', '成交价', '成交量', '成交额', '过夜费', '时间', '手续费'],
    ...mt5Trades.value.map(trade => [
      trade.symbol,
      trade.side === 'buy' ? '买入' : '卖出',
      trade.price != null ? Number(trade.price).toFixed(2) : '-',
      trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-',
      trade.amount != null ? Number(trade.amount).toFixed(2) : '-',
      trade.overnight_fee != null ? Number(trade.overnight_fee).toFixed(2) : '0.00',
      formatDateTime(trade.timestamp),
      trade.fee != null ? Number(trade.fee).toFixed(2) : '-'
    ])
  ]
  const mt5Sheet = XLSX.utils.aoa_to_sheet(mt5Data)
  XLSX.utils.book_append_sheet(wb, mt5Sheet, 'MT5成交历史')

  XLSX.writeFile(wb, `${filename}.xlsx`)
}

function exportToPDF(filename) {
  try {
    // Create PDF document
    const doc = new jsPDF()

    // Title
    doc.setFontSize(16)
    doc.text('Trading History Report', 14, 15)

    // Date range
    doc.setFontSize(10)
    doc.text(`Query Time: ${startTime.value} to ${endTime.value}`, 14, 25)

    // Binance Statistics
    doc.setFontSize(12)
    doc.text('Binance Account Statistics', 14, 35)

    autoTable(doc, {
      startY: 40,
      head: [['Item', 'Value']],
      body: [
        ['Total Volume', stats.value.totalVolume?.toFixed(2) || '0.00'],
        ['Total Amount', (stats.value.totalAmount?.toFixed(2) || '0.00') + ' USDT'],
        ['Taker Amount', (stats.value.takerAmount?.toFixed(2) || '0.00') + ' USDT'],
        ['Maker Amount', (stats.value.makerAmount?.toFixed(2) || '0.00') + ' USDT'],
        ['Total Fees (USDT)', (stats.value.totalFees?.toFixed(2) || '0.00') + ' USDT'],
        ['Total Fees (BNB)', (stats.value.bnbFees?.toFixed(4) || '0.0000') + ' BNB'],
        ['Realized PnL', (stats.value.realizedPnL?.toFixed(2) || '0.00') + ' USDT']
      ],
      styles: { fontSize: 9 },
      headStyles: { fillColor: [41, 128, 185] }
    })

    // MT5 Statistics
    let currentY = doc.previousAutoTable.finalY + 10
    doc.text('Bybit MT5 Statistics', 14, currentY)

    autoTable(doc, {
      startY: currentY + 5,
      head: [['Item', 'Value']],
      body: [
        ['Total Volume', stats.value.mt5Volume?.toFixed(2) || '0.00'],
        ['Total Amount', (stats.value.mt5Amount?.toFixed(2) || '0.00') + ' USDT'],
        ['Overnight Fee', (stats.value.mt5OvernightFee?.toFixed(2) || '0.00') + ' USDT'],
        ['MT5 Fee', (stats.value.mt5Fee?.toFixed(2) || '0.00') + ' USDT'],
        ['MT5 Realized PnL', (stats.value.mt5RealizedPnL?.toFixed(2) || '0.00') + ' USDT']
      ],
      styles: { fontSize: 9 },
      headStyles: { fillColor: [231, 76, 60] }
    })

    // Binance trades table
    currentY = doc.previousAutoTable.finalY + 10
    doc.text('Binance Account Trade History', 14, currentY)

    autoTable(doc, {
      startY: currentY + 5,
      head: [['Symbol', 'Side', 'Price', 'Qty', 'Amount', 'Type', 'Time', 'Fee']],
      body: accountTrades.value.map(trade => [
        trade.symbol,
        trade.side === 'buy' ? 'Buy' : 'Sell',
        trade.price != null ? Number(trade.price).toFixed(2) : '-',
        trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-',
        trade.amount != null ? Number(trade.amount).toFixed(2) : '-',
        trade.maker ? 'Maker' : 'Taker',
        formatDateTime(trade.timestamp),
        trade.fee != null ? Number(trade.fee).toFixed(2) : '-'
      ]),
      styles: { fontSize: 7 },
      headStyles: { fillColor: [41, 128, 185] }
    })

    // MT5 trades table
    currentY = doc.previousAutoTable.finalY + 10

    // Check if we need a new page
    if (currentY > 250) {
      doc.addPage()
      currentY = 15
    }

    doc.text('Bybit MT5 Trade History', 14, currentY)

    autoTable(doc, {
      startY: currentY + 5,
      head: [['Symbol', 'Side', 'Price', 'Qty', 'Amount', 'Overnight', 'Time', 'Fee']],
      body: mt5Trades.value.map(trade => [
        trade.symbol,
        trade.side === 'buy' ? 'Buy' : 'Sell',
        trade.price != null ? Number(trade.price).toFixed(2) : '-',
        trade.quantity != null ? Number(trade.quantity).toFixed(2) : '-',
        trade.amount != null ? Number(trade.amount).toFixed(2) : '-',
        trade.overnight_fee != null ? Number(trade.overnight_fee).toFixed(2) : '0.00',
        formatDateTime(trade.timestamp),
        trade.fee != null ? Number(trade.fee).toFixed(2) : '-'
      ]),
      styles: { fontSize: 7 },
      headStyles: { fillColor: [231, 76, 60] }
    })

    doc.save(`${filename}.pdf`)
    console.log('PDF exported successfully')
  } catch (error) {
    console.error('PDF export error:', error)
    console.error('Error stack:', error.stack)
    alert('PDF导出失败: ' + error.message + '\n\n请尝试：\n1. 刷新页面 (Ctrl+Shift+R)\n2. 清除浏览器缓存\n3. 使用CSV或Excel导出')
  }
}

// Close export menu when clicking outside
function handleClickOutside(event) {
  const exportMenu = event.target.closest('.relative')
  if (!exportMenu && showExportMenu.value) {
    showExportMenu.value = false
  }
}

// Load today's data on mount
onMounted(() => {
  initializeDateRange()
  queryData()
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
