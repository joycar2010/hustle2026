<template>
  <div class="card-elevated">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xl font-bold">Historical Spread Data</h2>
      <div class="flex items-center space-x-2">
        <button
          @click="refreshData"
          class="p-2 rounded hover:bg-dark-50 transition-colors"
          :disabled="loading"
        >
          <svg
            class="w-5 h-5"
            :class="{ 'animate-spin': loading }"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
        </button>
      </div>
    </div>

    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left border-b border-border-primary">
            <th class="table-header pb-3">Time</th>
            <th class="table-header pb-3">Binance Bid</th>
            <th class="table-header pb-3">Bybit Ask</th>
            <th class="table-header pb-3">Spread</th>
            <th class="table-header pb-3">Direction</th>
            <th class="table-header pb-3">Profit %</th>
            <th class="table-header pb-3">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in spreadHistory"
            :key="item.id"
            class="table-row"
          >
            <td class="py-3 text-text-secondary">
              {{ formatTime(item.timestamp) }}
            </td>
            <td class="py-3 font-mono">
              {{ formatPrice(item.binance_bid) }} USDT
            </td>
            <td class="py-3 font-mono">
              {{ formatPrice(item.bybit_ask) }} USDT
            </td>
            <td class="py-3">
              <span :class="['font-mono font-medium', getSpreadClass(item.spread)]">
                {{ formatPrice(item.spread) }} USDT
              </span>
            </td>
            <td class="py-3">
              <span :class="['capitalize', item.direction === 'forward' ? 'text-success' : 'text-info']">
                {{ item.direction }}
              </span>
            </td>
            <td class="py-3">
              <span :class="['font-mono', item.profit_percent > 0 ? 'text-success' : 'text-text-secondary']">
                {{ item.profit_percent.toFixed(3) }}%
              </span>
            </td>
            <td class="py-3">
              <span :class="getStatusBadgeClass(item.status)">
                {{ item.status }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="spreadHistory.length === 0" class="text-center py-8 text-text-tertiary">
        No historical data available
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="flex items-center justify-between mt-4 pt-4 border-t border-border-secondary">
      <div class="text-sm text-text-tertiary">
        Showing {{ (currentPage - 1) * pageSize + 1 }} to {{ Math.min(currentPage * pageSize, totalItems) }} of {{ totalItems }} entries
      </div>
      <div class="flex space-x-2">
        <button
          @click="currentPage--"
          :disabled="currentPage === 1"
          class="px-3 py-1 rounded bg-dark-300 hover:bg-dark-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Previous
        </button>
        <button
          @click="currentPage++"
          :disabled="currentPage === totalPages"
          class="px-3 py-1 rounded bg-dark-300 hover:bg-dark-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import dayjs from 'dayjs'
import api from '@/services/api'

const loading = ref(false)
const spreadHistory = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const totalItems = ref(0)

const totalPages = computed(() => Math.ceil(totalItems.value / pageSize.value))

onMounted(() => {
  fetchSpreadHistory()
})

async function fetchSpreadHistory() {
  loading.value = true
  try {
    const response = await api.get('/api/v1/market/spread/history', {
      params: {
        limit: 100,
        binance_symbol: 'XAUUSDT',
        bybit_symbol: 'XAUUSDT'
      }
    })

    const data = response.data

    // Transform backend data to component format
    const transformedData = data.map((item, index) => {
      const forwardSpread = item.bybit_quote.ask - item.binance_quote.bid
      const reverseSpread = item.binance_quote.bid - item.bybit_quote.ask
      const isForward = Math.abs(forwardSpread) > Math.abs(reverseSpread)
      const spread = isForward ? forwardSpread : reverseSpread

      return {
        id: index + 1,
        timestamp: item.timestamp,
        binance_bid: item.binance_quote.bid,
        bybit_ask: item.bybit_quote.ask,
        spread: Math.abs(spread),
        direction: isForward ? 'forward' : 'reverse',
        profit_percent: (Math.abs(spread) / item.binance_quote.bid) * 100,
        status: Math.abs(spread) > 3 ? 'opportunity' : 'normal',
      }
    })

    totalItems.value = transformedData.length
    spreadHistory.value = transformedData.slice(
      (currentPage.value - 1) * pageSize.value,
      currentPage.value * pageSize.value
    )
  } catch (error) {
    console.error('Failed to fetch spread history:', error)
  } finally {
    loading.value = false
  }
}

function refreshData() {
  fetchSpreadHistory()
}

function formatTime(timestamp) {
  return dayjs(timestamp).format('MM-DD HH:mm:ss')
}

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function getSpreadClass(spread) {
  if (spread > 3) return 'text-success'
  if (spread > 2) return 'text-primary'
  return 'text-text-secondary'
}

function getStatusBadgeClass(status) {
  const classes = {
    opportunity: 'badge-success',
    normal: 'badge-info',
    executed: 'badge-warning',
  }
  return classes[status] || 'badge-info'
}
</script>