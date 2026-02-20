<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">Dashboard</h1>

    <!-- Stats Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">Total Balance</div>
        <div class="text-2xl font-bold">${{ formatNumber(stats.totalBalance) }}</div>
        <div class="text-xs text-green-500 mt-1">+2.5% today</div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">Open Positions</div>
        <div class="text-2xl font-bold">{{ stats.openPositions }}</div>
        <div class="text-xs text-gray-400 mt-1">Active trades</div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">Today's P&L</div>
        <div class="text-2xl font-bold" :class="stats.todayPnL >= 0 ? 'text-green-500' : 'text-red-500'">
          ${{ formatNumber(stats.todayPnL) }}
        </div>
        <div class="text-xs text-gray-400 mt-1">{{ stats.todayPnL >= 0 ? '+' : '' }}{{ ((stats.todayPnL / stats.totalBalance) * 100).toFixed(2) }}%</div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">Running Strategies</div>
        <div class="text-2xl font-bold">{{ stats.runningStrategies }}</div>
        <div class="text-xs text-gray-400 mt-1">Automated</div>
      </div>
    </div>

    <!-- Market Overview -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <div class="card">
        <h2 class="text-xl font-bold mb-4">Market Overview</h2>
        <div v-if="marketData" class="space-y-3">
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Binance Bid</span>
            <span class="text-lg font-bold">${{ formatPrice(marketData.binance_bid) }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Bybit Ask</span>
            <span class="text-lg font-bold">${{ formatPrice(marketData.bybit_ask) }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Current Spread</span>
            <span class="text-lg font-bold text-primary">${{ formatPrice(marketData.spread) }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Direction</span>
            <span class="text-lg font-bold capitalize">{{ marketData.direction }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <h2 class="text-xl font-bold mb-4">Account Summary</h2>
        <div class="space-y-3">
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Binance Balance</span>
            <span class="text-lg font-bold">${{ formatNumber(accountSummary.binance) }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Bybit Balance</span>
            <span class="text-lg font-bold">${{ formatNumber(accountSummary.bybit) }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-gray-400">Total Equity</span>
            <span class="text-lg font-bold text-primary">${{ formatNumber(accountSummary.total) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Recent Activity -->
    <div class="card">
      <h2 class="text-xl font-bold mb-4">Recent Activity</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-2">Time</th>
              <th class="pb-2">Type</th>
              <th class="pb-2">Direction</th>
              <th class="pb-2">Quantity</th>
              <th class="pb-2">P&L</th>
              <th class="pb-2">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="activity in recentActivity" :key="activity.id" class="border-b border-gray-800">
              <td class="py-3">{{ formatTime(activity.time) }}</td>
              <td>{{ activity.type }}</td>
              <td>
                <span :class="activity.direction === 'forward' ? 'text-green-500' : 'text-red-500'">
                  {{ activity.direction }}
                </span>
              </td>
              <td>{{ activity.quantity }}</td>
              <td :class="activity.pnl >= 0 ? 'text-green-500' : 'text-red-500'">
                ${{ activity.pnl.toFixed(2) }}
              </td>
              <td>
                <span class="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">
                  {{ activity.status }}
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
import { ref, onMounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import dayjs from 'dayjs'
import api from '@/services/api'

const marketStore = useMarketStore()
const marketData = ref(null)

const stats = ref({
  totalBalance: 50000,
  openPositions: 3,
  todayPnL: 1250.50,
  runningStrategies: 2
})

const accountSummary = ref({
  binance: 25000,
  bybit: 25000,
  total: 50000
})

const recentActivity = ref([])

onMounted(async () => {
  await fetchDashboardData()
  setInterval(fetchDashboardData, 5000)
})

async function fetchDashboardData() {
  try {
    marketData.value = await marketStore.fetchMarketData()
    // Fetch other dashboard data
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error)
  }
}

function formatNumber(num) {
  return num ? num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'
}

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function formatTime(time) {
  return dayjs(time).format('MM-DD HH:mm:ss')
}
</script>
