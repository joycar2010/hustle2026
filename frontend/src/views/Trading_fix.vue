<!-- Trading.vue - 修复版前端组件 -->
<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">交易历史数据</h1>

    <!-- Query Controls -->
    <div class="card mb-6">
      <div class="flex flex-wrap items-center gap-4">
        <!-- Date Selector -->
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">查询日期 (UTC):</label>
          <input type="date" v-model="queryDate"
                 class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <!-- Time Range Selector -->
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">时间范围:</label>
          <select v-model="timeRange" class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
            <option value="">自定义</option>
            <option value="today">今日</option>
            <option value="week">本周</option>
            <option value="month">本月</option>
          </select>
        </div>

        <!-- Query Button -->
        <button @click="queryData" class="btn-primary">
          查询
        </button>

        <!-- Show All Button -->
        <button @click="showAllData" class="btn-secondary">
          显示全部
        </button>

        <!-- Sync Trades Button -->
        <button @click="syncTrades" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded" :disabled="syncing">
          {{ syncing ? '同步中...' : '同步交易记录' }}
        </button>

        <!-- Validate Button -->
        <button @click="validateData" class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded" :disabled="validating">
          {{ validating ? '校验中...' : '校验数据' }}
        </button>

        <!-- Delete All Button -->
        <button @click="deleteAllHistory" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded">
          删除所有历史数据
        </button>
      </div>
    </div>

    <!-- Validation Alert -->
    <div v-if="validationResult && validationResult.deviation_alert" class="card mb-6 bg-yellow-900/20 border-yellow-600">
      <div class="flex items-center gap-2 text-yellow-500">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <div>
          <div class="font-bold">数据偏差告警</div>
          <div class="text-sm">
            佣金偏差: {{ validationResult.commission_deviation?.toFixed(4) }} USDT |
            成交额偏差: {{ validationResult.amount_deviation?.toFixed(2) }} USDT
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
              <div class="text-lg font-bold">{{ stats.totalVolume }}</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额汇总</div>
              <div class="text-lg font-bold">{{ stats.totalAmount.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额(买卖)</div>
              <div class="text-lg font-bold">{{ stats.buySellAmount.toFixed(2) }} USDT</div>
              <div class="text-xs text-gray-500 mt-1">手动+策略交易</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额(任务)</div>
              <div class="text-lg font-bold">{{ stats.taskAmount.toFixed(2) }} USDT</div>
              <div class="text-xs text-gray-500 mt-1">同步交易</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">手续费汇总</div>
              <div class="text-lg font-bold text-red-500">{{ stats.totalFees.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">实际佣金</div>
              <div class="text-lg font-bold text-yellow-500">{{ stats.actualCommission?.toFixed(4) || '0.00' }} USDT</div>
              <div class="text-xs text-gray-500 mt-1">Binance API</div>
            </div>
          </div>

          <!-- Binance API Validation -->
          <div v-if="validationResult && validationResult.validated" class="bg-blue-900/20 p-3 rounded border border-blue-600">
            <div class="text-xs text-blue-400 mb-2">Binance API 校验结果</div>
            <div class="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span class="text-gray-400">API 佣金:</span>
                <span class="text-white ml-2">{{ validationResult.binance_actual_commission?.toFixed(4) }} USDT</span>
              </div>
              <div>
                <span class="text-gray-400">API 成交额:</span>
                <span class="text-white ml-2">{{ validationResult.binance_actual_amount?.toFixed(2) }} USDT</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Right Column Statistics -->
        <div class="space-y-4">
          <h3 class="text-lg font-semibold mb-4 border-b border-gray-700 pb-2">Bybit MT5成交历史</h3>

          <div class="grid grid-cols-2 gap-4">
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">市场资金率</div>
              <div class="text-lg font-bold text-yellow-500">{{ stats.marketFundingRate.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">MT5过夜费</div>
              <div class="text-lg font-bold text-red-500">{{ stats.mt5OvernightFee.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">市场手续费</div>
              <div class="text-lg font-bold text-red-500">{{ stats.marketFee.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">MT5手续费</div>
              <div class="text-lg font-bold text-red-500">{{ stats.mt5Fee.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">市盈率</div>
              <div class="text-lg font-bold text-green-500">{{ stats.peRatio.toFixed(2) }}%</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">MT5今返回</div>
              <div class="text-lg font-bold text-green-500">{{ stats.mt5TodayReturn.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded col-span-2">
              <div class="text-xs text-gray-400 mb-1">总回报利润</div>
              <div class="text-lg font-bold text-green-500">{{ stats.totalReturnProfit.toFixed(2) }} USDT</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Net Profit Summary -->
      <div class="mt-6 pt-4 border-t border-gray-700">
        <div class="text-center">
          <span class="text-gray-400">返佣后净利润汇总: </span>
          <span class="text-2xl font-bold" :class="netProfit >= 0 ? 'text-green-500' : 'text-red-500'">
            {{ netProfit.toFixed(2) }} USDT
          </span>
        </div>
      </div>
      </div>
    </div>

    <!-- Trading History Tables (保持原有表格结构) -->
    <!-- ... 省略表格代码，与原版相同 ... -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api'

// Query Controls
const queryDate = ref(new Date().toISOString().split('T')[0])
const timeRange = ref('')
const syncing = ref(false)
const validating = ref(false)
const validationResult = ref(null)

// Statistics Data
const stats = ref({
  totalVolume: 0,
  totalAmount: 0,
  buySellAmount: 0,
  taskAmount: 0,
  totalFees: 0,
  actualCommission: 0,
  overnightFees: 0,
  marketFundingRate: 0,
  mt5OvernightFee: 0,
  marketFee: 0,
  mt5Fee: 0,
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
    const params = {}
    if (timeRange.value) {
      params.time_range = timeRange.value
    } else if (queryDate.value) {
      params.date = queryDate.value
    }

    const response = await api.get('/api/v1/trading/history', { params })
    updateData(response.data)
  } catch (error) {
    console.error('Failed to query trading data:', error)
    clearData()
  }
}

async function showAllData() {
  try {
    const response = await api.get('/api/v1/trading/history/all')
    updateData(response.data)
  } catch (error) {
    console.error('Failed to fetch all trading data:', error)
    clearData()
  }
}

async function validateData() {
  validating.value = true
  try {
    const params = { validate: true }
    if (timeRange.value) {
      params.time_range = timeRange.value
    } else if (queryDate.value) {
      params.date = queryDate.value
    }

    const response = await api.get('/api/v1/trading/history', { params })
    updateData(response.data)

    if (response.data.validation) {
      validationResult.value = response.data.validation
      if (response.data.validation.deviation_alert) {
        alert('检测到数据偏差！请查看告警信息。')
      } else {
        alert('数据校验通过，与 Binance API 一致。')
      }
    }
  } catch (error) {
    console.error('Failed to validate data:', error)
    alert('数据校验失败，请重试')
  } finally {
    validating.value = false
  }
}

async function syncTrades() {
  syncing.value = true
  try {
    const response = await api.post('/api/v1/trading/sync-trades', null, {
      params: { days: 7 }
    })
    alert(`成功同步 ${response.data.synced_count} 条交易记录`)
    await showAllData()
  } catch (error) {
    console.error('Failed to sync trades:', error)
    alert('同步失败，请重试')
  } finally {
    syncing.value = false
  }
}

async function deleteAllHistory() {
  if (!confirm('确定要删除所有历史数据吗？此操作不可恢复！')) {
    return
  }

  try {
    await api.delete('/api/v1/trading/history/all')
    alert('历史数据已删除')
    clearData()
  } catch (error) {
    console.error('Failed to delete history:', error)
    alert('删除失败，请重试')
  }
}

function updateData(data) {
  if (data.stats) {
    stats.value = data.stats
  }
  if (data.accountTrades) {
    accountTrades.value = data.accountTrades
  }
  if (data.mt5Trades) {
    mt5Trades.value = data.mt5Trades
  }
  if (data.validation) {
    validationResult.value = data.validation
  }
}

function clearData() {
  stats.value = {
    totalVolume: 0,
    totalAmount: 0,
    buySellAmount: 0,
    taskAmount: 0,
    totalFees: 0,
    actualCommission: 0,
    overnightFees: 0,
    marketFundingRate: 0,
    mt5OvernightFee: 0,
    marketFee: 0,
    mt5Fee: 0,
    peRatio: 0,
    mt5TodayReturn: 0,
    totalReturnProfit: 0
  }
  accountTrades.value = []
  mt5Trades.value = []
  validationResult.value = null
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
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
  timeRange.value = 'today'
  queryData()
})
</script>
