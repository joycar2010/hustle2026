<template>
  <div class="space-y-4">
    <!-- Main Stats Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Total Assets -->
      <div class="card-elevated">
        <div class="flex items-center justify-between mb-2">
          <span class="text-text-tertiary text-sm">Total Assets</span>
          <svg class="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <div class="text-3xl font-bold font-mono mb-1">
          {{ formatNumber(assets.total) }} USDT
        </div>
        <div :class="['text-sm flex items-center', assets.totalChange >= 0 ? 'text-success' : 'text-danger']">
          <svg v-if="assets.totalChange >= 0" class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" clip-rule="evenodd" />
          </svg>
          <svg v-else class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z" clip-rule="evenodd" />
          </svg>
          {{ assets.totalChange >= 0 ? '+' : '' }}{{ assets.totalChange.toFixed(2) }}% (24h)
        </div>
      </div>

      <!-- Net Assets -->
      <div class="card-elevated">
        <div class="flex items-center justify-between mb-2">
          <span class="text-text-tertiary text-sm">Net Assets</span>
          <svg class="w-5 h-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
          </svg>
        </div>
        <div class="text-3xl font-bold font-mono mb-1">
          {{ formatNumber(assets.net) }} USDT
        </div>
        <div class="text-sm text-text-tertiary">
          Available: {{ formatNumber(assets.available) }} USDT
        </div>
      </div>

      <!-- Open Positions -->
      <div class="card-elevated">
        <div class="flex items-center justify-between mb-2">
          <span class="text-text-tertiary text-sm">Open Positions</span>
          <svg class="w-5 h-5 text-info" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        </div>
        <div class="text-3xl font-bold mb-1">
          {{ positions.count }}
        </div>
        <div class="text-sm text-text-tertiary">
          Volume: {{ formatNumber(positions.volume) }} USDT
        </div>
      </div>

      <!-- Today's P&L -->
      <div class="card-elevated">
        <div class="flex items-center justify-between mb-2">
          <span class="text-text-tertiary text-sm">Today's P&L</span>
          <svg class="w-5 h-5" :class="pnl.today >= 0 ? 'text-success' : 'text-danger'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
        </div>
        <div class="text-3xl font-bold font-mono mb-1" :class="pnl.today >= 0 ? 'text-success' : 'text-danger'">
          {{ pnl.today >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(pnl.today)) }} USDT
        </div>
        <div class="text-sm text-text-tertiary">
          ROI: {{ pnl.todayPercent >= 0 ? '+' : '' }}{{ pnl.todayPercent.toFixed(2) }}%
        </div>
      </div>
    </div>

    <!-- Detailed Stats -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Account Breakdown -->
      <div class="card-elevated">
        <h3 class="text-lg font-bold mb-4">Account Breakdown</h3>
        <div class="space-y-3">
          <div class="flex items-center justify-between p-3 bg-dark-300 rounded-lg">
            <div class="flex items-center space-x-3">
              <div class="w-10 h-10 bg-primary rounded-full flex items-center justify-center">
                <span class="text-dark-300 font-bold">B</span>
              </div>
              <div>
                <div class="font-medium">Binance</div>
                <div class="text-xs text-text-tertiary">XAUUSDT</div>
              </div>
            </div>
            <div class="text-right">
              <div class="font-bold font-mono">{{ formatNumber(accounts.binance.balance) }} USDT</div>
              <div class="text-xs text-text-tertiary">{{ accounts.binance.positions }} positions</div>
            </div>
          </div>

          <div class="flex items-center justify-between p-3 bg-dark-300 rounded-lg">
            <div class="flex items-center space-x-3">
              <div class="w-10 h-10 bg-warning rounded-full flex items-center justify-center">
                <span class="text-white font-bold">B</span>
              </div>
              <div>
                <div class="font-medium">Bybit</div>
                <div class="text-xs text-text-tertiary">XAUUSDT</div>
              </div>
            </div>
            <div class="text-right">
              <div class="font-bold font-mono">{{ formatNumber(accounts.bybit.balance) }} USDT</div>
              <div class="text-xs text-text-tertiary">{{ accounts.bybit.positions }} positions</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Risk Metrics -->
      <div class="card-elevated">
        <h3 class="text-lg font-bold mb-4">Risk Metrics</h3>
        <div class="space-y-4">
          <div>
            <div class="flex justify-between text-sm mb-2">
              <span class="text-text-tertiary">Risk Ratio</span>
              <span class="font-medium" :class="getRiskColor(risk.ratio)">
                {{ risk.ratio.toFixed(2) }}%
              </span>
            </div>
            <div class="w-full bg-dark-300 rounded-full h-2">
              <div
                class="h-2 rounded-full transition-all"
                :class="getRiskBarColor(risk.ratio)"
                :style="{ width: `${Math.min(risk.ratio, 100)}%` }"
              ></div>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <div class="text-text-tertiary text-sm mb-1">Margin Used</div>
              <div class="font-bold font-mono">{{ formatNumber(risk.marginUsed) }} USDT</div>
            </div>
            <div>
              <div class="text-text-tertiary text-sm mb-1">Available Margin</div>
              <div class="font-bold font-mono">{{ formatNumber(risk.marginAvailable) }} USDT</div>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <div class="text-text-tertiary text-sm mb-1">Max Drawdown</div>
              <div class="font-bold font-mono text-danger">{{ risk.maxDrawdown.toFixed(2) }}%</div>
            </div>
            <div>
              <div class="text-text-tertiary text-sm mb-1">Win Rate</div>
              <div class="font-bold font-mono text-success">{{ risk.winRate.toFixed(2) }}%</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()

const assets = ref({
  total: 0,
  totalChange: 0,
  net: 0,
  available: 0,
})

const positions = ref({
  count: 0,
  volume: 0,
})

const pnl = ref({
  today: 0,
  todayPercent: 0,
})

const accounts = ref({
  binance: {
    balance: 0,
    positions: 0,
  },
  bybit: {
    balance: 0,
    positions: 0,
  },
})

const risk = ref({
  ratio: 0,
  marginUsed: 0,
  marginAvailable: 0,
  maxDrawdown: 0,
  winRate: 0,
})

onMounted(async () => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  await fetchDashboardData()

  // Removed polling - rely on WebSocket account_balance messages (backend broadcasts every 10s)
})

onUnmounted(() => {
  // Cleanup handled by marketStore
})

// Watch for account balance updates via WebSocket (when backend implements it)
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    updateAccountData(message.data)
  }
})

function updateAccountData(data) {
  if (data.summary) {
    assets.value.total = data.summary.total_assets || assets.value.total
    assets.value.net = data.summary.net_assets || assets.value.net
    assets.value.available = data.summary.available_balance || assets.value.available

    positions.value.count = data.summary.position_count || positions.value.count
    positions.value.volume = data.summary.margin_balance || positions.value.volume

    pnl.value.today = data.summary.daily_pnl || pnl.value.today
    pnl.value.todayPercent = data.summary.total_assets > 0
      ? (data.summary.daily_pnl / data.summary.total_assets) * 100
      : pnl.value.todayPercent

    risk.value.ratio = data.summary.risk_ratio || risk.value.ratio
    risk.value.marginUsed = data.summary.margin_balance || risk.value.marginUsed
    risk.value.marginAvailable = data.summary.available_balance || risk.value.marginAvailable
  }
}

async function fetchDashboardData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

    if (data.summary) {
      // Update assets
      assets.value.total = data.summary.total_assets || 0
      assets.value.net = data.summary.net_assets || 0
      assets.value.available = data.summary.available_balance || 0
      assets.value.totalChange = 0 // TODO: Calculate from historical data if available

      // Update positions
      positions.value.count = data.summary.position_count || 0
      positions.value.volume = data.summary.margin_balance || 0

      // Update P&L
      pnl.value.today = data.summary.daily_pnl || 0
      pnl.value.todayPercent = data.summary.total_assets > 0
        ? (data.summary.daily_pnl / data.summary.total_assets) * 100
        : 0

      // Update risk
      risk.value.ratio = data.summary.risk_ratio || 0
      risk.value.marginUsed = data.summary.margin_balance || 0
      risk.value.marginAvailable = data.summary.available_balance || 0

      // Calculate max drawdown and win rate from positions if available
      if (data.positions && data.positions.length > 0) {
        calculateRiskMetrics(data.positions)
      }
    }

    // Update account breakdown
    if (data.accounts && data.accounts.length > 0) {
      // Find Binance accounts (platform_id === 1)
      const binanceAccounts = data.accounts.filter(acc => acc.platform_id === 1)
      if (binanceAccounts.length > 0) {
        accounts.value.binance.balance = binanceAccounts.reduce((sum, acc) =>
          sum + (acc.balance?.total_assets || 0), 0)
        accounts.value.binance.positions = binanceAccounts.reduce((sum, acc) =>
          sum + (acc.positions?.length || 0), 0)
      }

      // Find Bybit accounts (platform_id === 2)
      const bybitAccounts = data.accounts.filter(acc => acc.platform_id === 2 || acc.platform_id === 3)
      if (bybitAccounts.length > 0) {
        accounts.value.bybit.balance = bybitAccounts.reduce((sum, acc) =>
          sum + (acc.balance?.total_assets || 0), 0)
        accounts.value.bybit.positions = bybitAccounts.reduce((sum, acc) =>
          sum + (acc.positions?.length || 0), 0)
      }
    }
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error)
  }
}

function calculateRiskMetrics(positions) {
  // Calculate max drawdown from unrealized PnL
  const unrealizedPnls = positions.map(p => p.unrealized_pnl || 0)
  if (unrealizedPnls.length > 0) {
    const minPnl = Math.min(...unrealizedPnls)
    const totalValue = assets.value.total
    risk.value.maxDrawdown = totalValue > 0 ? Math.abs((minPnl / totalValue) * 100) : 0
  }

  // Calculate win rate from closed positions (if available)
  // For now, set a default value since we don't have historical trade data
  risk.value.winRate = 0
}

function formatNumber(num) {
  return num ? num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'
}

function getRiskColor(ratio) {
  if (ratio < 30) return 'text-success'
  if (ratio < 60) return 'text-warning'
  return 'text-danger'
}

function getRiskBarColor(ratio) {
  if (ratio < 30) return 'bg-success'
  if (ratio < 60) return 'bg-warning'
  return 'bg-danger'
}
</script>