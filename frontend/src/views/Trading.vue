<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">交易历史数据</h1>

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
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api'

// Query Controls
const startTime = ref('')
const endTime = ref('')
const loading = ref(false)

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
  buySellAmount: 0,
  taskAmount: 0,
  totalFees: 0,
  realizedPnL: 0,
  overnightFees: 0,
  marketFundingRate: 0,
  mt5OvernightFee: 0,
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
    stats.value = data.stats
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
    buySellAmount: 0,
    taskAmount: 0,
    totalFees: 0,
    realizedPnL: 0,
    overnightFees: 0,
    marketFundingRate: 0,
    mt5OvernightFee: 0,
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

// Load today's data on mount
onMounted(() => {
  initializeDateRange()
  queryData()
})
</script>
