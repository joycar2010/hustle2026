<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">交易历史数据</h1>

    <!-- Query Controls -->
    <div class="card mb-6">
      <div class="flex flex-wrap items-center gap-4">
        <!-- Date Selector -->
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">查询日期:</label>
          <input type="date" v-model="queryDate"
                 class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
        </div>

        <!-- Query Button -->
        <button @click="queryData" class="btn-primary">
          查询
        </button>

        <!-- Show All Button -->
        <button @click="showAllData" class="btn-secondary">
          显示全部
        </button>

        <!-- Accounting Sync Toggle -->
        <div class="flex items-center gap-2 ml-auto">
          <label class="text-sm text-gray-400">会计同步型</label>
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" v-model="accountingSync" class="sr-only peer">
            <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer
                        peer-checked:after:translate-x-full peer-checked:after:border-white
                        after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                        after:bg-white after:border-gray-300 after:border after:rounded-full
                        after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600">
            </div>
          </label>
        </div>

        <!-- Delete All Button -->
        <button @click="deleteAllHistory" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded">
          删除所有历史数据
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
          <h3 class="text-lg font-semibold mb-4 border-b border-gray-700 pb-2">账户成交历史</h3>

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
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">成交额(任务)</div>
              <div class="text-lg font-bold">{{ stats.taskAmount.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">手续费汇总</div>
              <div class="text-lg font-bold text-red-500">{{ stats.totalFees.toFixed(2) }} USDT</div>
            </div>
            <div class="bg-gray-800 p-3 rounded">
              <div class="text-xs text-gray-400 mb-1">过夜费汇总</div>
              <div class="text-lg font-bold text-red-500">{{ stats.overnightFees.toFixed(2) }} USDT</div>
            </div>
          </div>
        </div>

        <!-- Right Column Statistics -->
        <div class="space-y-4">
          <h3 class="text-lg font-semibold mb-4 border-b border-gray-700 pb-2">MT5成交历史</h3>

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

    <!-- Trading History Tables -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Account Trading History Table -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">账户成交历史</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-gray-400 border-b border-gray-700">
                <th class="pb-2">时间</th>
                <th class="pb-2">交易对</th>
                <th class="pb-2">方向</th>
                <th class="pb-2">数量</th>
                <th class="pb-2">价格</th>
                <th class="pb-2">手续费</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="accountTrades.length === 0">
                <td colspan="6" class="text-center py-8 text-gray-500">暂无数据</td>
              </tr>
              <tr v-for="trade in accountTrades" :key="trade.id" class="border-b border-gray-800">
                <td class="py-3">{{ formatDateTime(trade.timestamp) }}</td>
                <td>{{ trade.symbol }}</td>
                <td>
                  <span :class="trade.side === 'buy' ? 'text-green-500' : 'text-red-500'">
                    {{ trade.side === 'buy' ? '买入' : '卖出' }}
                  </span>
                </td>
                <td>{{ trade.quantity }}</td>
                <td>{{ trade.price.toFixed(2) }} USDT</td>
                <td class="text-red-500">{{ trade.fee.toFixed(2) }} USDT</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- MT5 Trading History Table -->
      <div class="card">
        <h3 class="text-lg font-semibold mb-4">MT5成交历史</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-gray-400 border-b border-gray-700">
                <th class="pb-2">时间</th>
                <th class="pb-2">交易对</th>
                <th class="pb-2">方向</th>
                <th class="pb-2">数量</th>
                <th class="pb-2">价格</th>
                <th class="pb-2">手续费</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="mt5Trades.length === 0">
                <td colspan="6" class="text-center py-8 text-gray-500">暂无数据</td>
              </tr>
              <tr v-for="trade in mt5Trades" :key="trade.id" class="border-b border-gray-800">
                <td class="py-3">{{ formatDateTime(trade.timestamp) }}</td>
                <td>{{ trade.symbol }}</td>
                <td>
                  <span :class="trade.side === 'buy' ? 'text-green-500' : 'text-red-500'">
                    {{ trade.side === 'buy' ? '买入' : '卖出' }}
                  </span>
                </td>
                <td>{{ trade.quantity }}</td>
                <td>{{ trade.price.toFixed(2) }} USDT</td>
                <td class="text-red-500">{{ trade.fee.toFixed(2) }} USDT</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '@/services/api'

// Query Controls
const queryDate = ref(new Date().toISOString().split('T')[0])
const accountingSync = ref(false)

// Statistics Data
const stats = ref({
  totalVolume: 0,
  totalAmount: 0,
  buySellAmount: 0,
  taskAmount: 0,
  totalFees: 0,
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
    const response = await api.get('/api/v1/trading/history', {
      params: { date: queryDate.value }
    })
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
}

function clearData() {
  stats.value = {
    totalVolume: 0,
    totalAmount: 0,
    buySellAmount: 0,
    taskAmount: 0,
    totalFees: 0,
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
</script>
