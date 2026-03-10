<template>
  <div class="h-full flex flex-col max-lg:h-auto">
    <!-- Total Profit Header -->
    <div class="p-2 lg:p-2 md:p-3 bg-[#252930] border-b border-[#2b3139]">
      <div class="bg-[#1e2329] rounded p-2 lg:p-1.5 flex items-center justify-center gap-2">
        <span class="text-xs lg:text-[10px] text-gray-400">总盈利</span>
        <span class="text-lg lg:text-base md:text-xl font-bold font-mono" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }}
        </span>
        <span class="text-xs lg:text-[10px] text-gray-400">USDT</span>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-2 lg:p-1.5 md:p-3">
      <div class="grid grid-cols-1 gap-2 lg:gap-1.5 md:gap-3">
      <!-- Bybit MT5 Card -->
      <div class="bg-[#252930] rounded p-2 lg:p-2 md:p-3 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1.5 lg:mb-1 md:mb-2">
          <div class="flex items-center space-x-2 lg:space-x-1.5">
            <div class="w-6 h-6 lg:w-5 lg:h-5 md:w-7 md:h-7 bg-[#ff9800] rounded flex items-center justify-center">
              <span class="text-white font-bold text-base lg:text-sm md:text-lg">B</span>
            </div>
            <div>
              <div class="font-medium text-base lg:text-sm md:text-lg">Bybit MT5 <span class="text-xs lg:text-[10px] md:text-sm text-gray-400">XAUUSD.s</span></div>
            </div>
          </div>
        </div>

        <!-- Real-time Price, ASK and BID in one row -->
        <div class="grid grid-cols-3 gap-1.5 lg:gap-1 md:gap-2 mb-1.5 lg:mb-1 md:mb-2">
          <div class="bg-[#1e2329] rounded px-2 lg:px-1.5 py-1 lg:py-0.5 md:py-1.5 border border-[#2b3139]">
            <div class="text-xs lg:text-[10px] md:text-sm text-gray-400 mb-0.5 lg:mb-0">实时价格</div>
            <div :class="['text-base lg:text-sm md:text-lg font-mono font-bold', getPriceClass(bybit.mid, bybit.prevMid)]">
              {{ formatPrice(bybit.mid) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 lg:px-1.5 py-1 lg:py-0.5 md:py-1.5 border border-[#2b3139]">
            <div class="text-xs lg:text-[10px] md:text-sm text-gray-400 mb-0.5 lg:mb-0">ASK</div>
            <div :class="['text-base lg:text-sm md:text-lg font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 lg:px-1.5 py-1 lg:py-0.5 md:py-1.5 border border-[#2b3139]">
            <div class="text-xs lg:text-[10px] md:text-sm text-gray-400 mb-0.5 lg:mb-0">BID</div>
            <div :class="['text-base lg:text-sm md:text-lg font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1 lg:pt-0.5 md:pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-xs lg:text-[10px] md:text-sm text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5 lg:space-x-1">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 lg:w-0.5 h-2.5 lg:h-2 md:h-3 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-xs lg:text-[10px] md:text-sm font-mono">{{ bybitLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Binance Card -->
      <div class="bg-[#252930] rounded p-2 lg:p-2 md:p-3 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1.5 lg:mb-1 md:mb-2">
          <div class="flex items-center space-x-2 lg:space-x-1.5">
            <div class="w-6 h-6 lg:w-5 lg:h-5 md:w-7 md:h-7 bg-[#f0b90b] rounded flex items-center justify-center">
              <span class="text-[#1a1d21] font-bold text-base lg:text-sm md:text-lg">B</span>
            </div>
            <div>
              <div class="font-medium text-base lg:text-sm md:text-lg">Binance <span class="text-xs lg:text-[10px] md:text-sm text-gray-400">XAUUSDT</span></div>
            </div>
          </div>
        </div>

        <!-- Real-time Price, ASK and BID in one row -->
        <div class="grid grid-cols-3 gap-1.5 lg:gap-1 md:gap-2 mb-1.5 lg:mb-1 md:mb-2">
          <div class="bg-[#1e2329] rounded px-2 lg:px-1.5 py-1 lg:py-0.5 md:py-1.5 border border-[#2b3139]">
            <div class="text-xs lg:text-[10px] md:text-sm text-gray-400 mb-0.5 lg:mb-0">实时价格</div>
            <div :class="['text-base lg:text-sm md:text-lg font-mono font-bold', getPriceClass(binance.mid, binance.prevMid)]">
              {{ formatPrice(binance.mid) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 lg:px-1.5 py-1 lg:py-0.5 md:py-1.5 border border-[#2b3139]">
            <div class="text-xs lg:text-[10px] md:text-sm text-gray-400 mb-0.5 lg:mb-0">ASK</div>
            <div :class="['text-base lg:text-sm md:text-lg font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 lg:px-1.5 py-1 lg:py-0.5 md:py-1.5 border border-[#2b3139]">
            <div class="text-xs lg:text-[10px] md:text-sm text-gray-400 mb-0.5 lg:mb-0">BID</div>
            <div :class="['text-base lg:text-sm md:text-lg font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1 lg:pt-0.5 md:pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-xs lg:text-[10px] md:text-sm text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5 lg:space-x-1">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 lg:w-0.5 h-2.5 lg:h-2 md:h-3 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-xs lg:text-[10px] md:text-sm font-mono">{{ binanceLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Spread Data Table -->
      <SpreadDataTable />

      <!-- Pending Orders -->
      <PendingOrders />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'
import SpreadDataTable from './SpreadDataTable.vue'
import PendingOrders from '@/views/PendingOrders.vue'

const marketStore = useMarketStore()

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })
const binance = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })

const bybitLagCount = ref(0)
const binanceLagCount = ref(0)
let lastUpdateTime = Date.now()
let lagTimer = null

// Profit and position data
const totalProfit = ref(0)
const forwardActualPosition = ref(0)
const reverseActualPosition = ref(0)

// Position spread data - store position details for cost calculation
const binanceShortPositions = ref([]) // Binance SHORT positions
const binanceLongPositions = ref([]) // Binance LONG positions
const bybitShortPositions = ref([]) // Bybit SHORT positions
const bybitLongPositions = ref([]) // Bybit LONG positions

// Fee data
const bybitLongSwapFee = ref(0)
const bybitShortSwapFee = ref(0)
const binanceLongFundingRate = ref(0)
const binanceShortFundingRate = ref(0)

const bybitLagLevel = computed(() => Math.min(Math.floor(bybitLagCount.value / 10), 5))
const binanceLagLevel = computed(() => Math.min(Math.floor(binanceLagCount.value / 10), 5))

// Calculate reverse spread: Binance SHORT cost - Bybit LONG cost
const reverseSpread = computed(() => {
  if (binanceShortPositions.value.length === 0 || bybitLongPositions.value.length === 0) {
    return 0
  }

  // Calculate Binance SHORT average cost price
  const binanceShortCost = binanceShortPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const binanceShortSize = binanceShortPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const binanceShortAvg = binanceShortSize > 0 ? binanceShortCost / binanceShortSize : 0

  // Calculate Bybit LONG average cost price
  const bybitLongCost = bybitLongPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const bybitLongSize = bybitLongPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const bybitLongAvg = bybitLongSize > 0 ? bybitLongCost / bybitLongSize : 0

  // Reverse spread = Binance SHORT cost - Bybit LONG cost
  return binanceShortAvg - bybitLongAvg
})

// Calculate forward spread: Bybit SHORT cost - Binance LONG cost
const forwardSpread = computed(() => {
  if (bybitShortPositions.value.length === 0 || binanceLongPositions.value.length === 0) {
    return 0
  }

  // Calculate Bybit SHORT average cost price
  const bybitShortCost = bybitShortPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const bybitShortSize = bybitShortPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const bybitShortAvg = bybitShortSize > 0 ? bybitShortCost / bybitShortSize : 0

  // Calculate Binance LONG average cost price
  const binanceLongCost = binanceLongPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const binanceLongSize = binanceLongPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const binanceLongAvg = binanceLongSize > 0 ? binanceLongCost / binanceLongSize : 0

  // Forward spread = Bybit SHORT cost - Binance LONG cost
  return bybitShortAvg - binanceLongAvg
})

watch(() => marketStore.marketData, (data) => {
  if (!data) return
  const now = Date.now()
  if (now - lastUpdateTime > 2000) {
    bybitLagCount.value++
    binanceLagCount.value++
  }
  lastUpdateTime = now

  bybit.value.prevBid = bybit.value.bid
  bybit.value.prevAsk = bybit.value.ask
  bybit.value.prevMid = bybit.value.mid
  binance.value.prevBid = binance.value.bid
  binance.value.prevAsk = binance.value.ask
  binance.value.prevMid = binance.value.prevMid

  bybit.value.bid = data.bybit_bid || 0
  bybit.value.ask = data.bybit_ask || 0
  bybit.value.mid = data.bybit_mid || ((bybit.value.bid + bybit.value.ask) / 2)

  binance.value.bid = data.binance_bid || 0
  binance.value.ask = data.binance_ask || 0
  binance.value.mid = data.binance_mid || ((binance.value.bid + binance.value.ask) / 2)

  bybitConnected.value = true
  binanceConnected.value = true
})

watch(() => marketStore.connected, (val) => {
  if (!val) {
    bybitConnected.value = false
    binanceConnected.value = false
  }
})

// Watch for account balance updates via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
})

function handleAccountBalanceUpdate(data) {
  // Update total profit
  if (data.summary) {
    totalProfit.value = data.summary.daily_pnl || 0
  }

  // Extract fee data from accounts
  if (data.accounts && data.accounts.length > 0) {
    // Reset fee values
    bybitLongSwapFee.value = 0
    bybitShortSwapFee.value = 0
    binanceLongFundingRate.value = 0
    binanceShortFundingRate.value = 0

    // Reset position values
    forwardActualPosition.value = 0
    reverseActualPosition.value = 0

    // Get first account's positions and aggregate fees from all accounts
    const bybitAccounts = data.accounts.filter(acc => acc.platform_id === 2)
    const binanceAccounts = data.accounts.filter(acc => acc.platform_id === 1)

    // Use first account's total_positions instead of aggregating
    if (bybitAccounts.length > 0) {
      reverseActualPosition.value = bybitAccounts[0].balance?.total_positions || 0
    }
    if (binanceAccounts.length > 0) {
      forwardActualPosition.value = binanceAccounts[0].balance?.total_positions || 0
    }

    // Aggregate fees from all accounts
    data.accounts.forEach(account => {
      if (account.platform_id === 2) {
        // Bybit accounts
        bybitLongSwapFee.value += account.balance?.long_swap_fee || 0
        bybitShortSwapFee.value += account.balance?.short_swap_fee || 0
      } else if (account.platform_id === 1) {
        // Binance accounts
        binanceLongFundingRate.value += account.balance?.long_funding_rate || 0
        binanceShortFundingRate.value += account.balance?.short_funding_rate || 0
      }
    })
  }

  // Extract actual positions from positions array for spread calculation
  if (data.positions && data.positions.length > 0) {
    // Reset position arrays
    binanceShortPositions.value = []
    binanceLongPositions.value = []
    bybitShortPositions.value = []
    bybitLongPositions.value = []

    // Aggregate positions by platform and side
    data.positions.forEach(position => {
      // Find the account for this position to get platform_id
      const account = data.accounts?.find(acc => acc.account_id === position.account_id)
      if (!account) return

      const posSize = Math.abs(position.size || 0)
      const posData = {
        size: posSize,
        entry_price: position.entry_price || 0,
        current_price: position.current_price || 0
      }

      if (account.platform_id === 2) {
        // Bybit MT5 positions
        if (position.side === 'Buy') {
          bybitLongPositions.value.push(posData)
        } else if (position.side === 'Sell') {
          bybitShortPositions.value.push(posData)
        }
      } else if (account.platform_id === 1) {
        // Binance positions
        if (position.side === 'Buy') {
          binanceLongPositions.value.push(posData)
        } else if (position.side === 'Sell') {
          binanceShortPositions.value.push(posData)
        }
      }
    })
  } else {
    // No positions, reset position arrays only
    binanceShortPositions.value = []
    binanceLongPositions.value = []
    bybitShortPositions.value = []
    bybitLongPositions.value = []
  }
}

onMounted(() => {
  marketStore.connect()
  lagTimer = setInterval(() => {
    if (Date.now() - lastUpdateTime > 2000) {
      bybitLagCount.value++
      binanceLagCount.value++
    }
  }, 2000)

  // Initial fetch
  fetchAccountData()
})

onUnmounted(() => {
  if (lagTimer) clearInterval(lagTimer)
})

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function getPriceClass(current, previous) {
  if (!previous || current === previous) return 'text-white'
  return current > previous ? 'text-[#0ecb81]' : 'text-[#f6465d]'
}

function formatNumber(num) {
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatSpread(spread) {
  if (!spread || isNaN(spread)) return '0.00'
  const sign = spread >= 0 ? '+' : ''
  return sign + spread.toFixed(2)
}

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data
    if (data.summary) {
      totalProfit.value = data.summary.daily_pnl || 0
    }

    // Extract fee data and positions from accounts
    if (data.accounts && data.accounts.length > 0) {
      // Reset fee values
      bybitLongSwapFee.value = 0
      bybitShortSwapFee.value = 0
      binanceLongFundingRate.value = 0
      binanceShortFundingRate.value = 0

      // Reset position values
      forwardActualPosition.value = 0
      reverseActualPosition.value = 0

      // Get first account's positions and aggregate fees from all accounts
      const bybitAccounts = data.accounts.filter(acc => acc.platform_id === 2)
      const binanceAccounts = data.accounts.filter(acc => acc.platform_id === 1)

      // Use first account's total_positions instead of aggregating
      if (bybitAccounts.length > 0) {
        reverseActualPosition.value = bybitAccounts[0].balance?.total_positions || 0
      }
      if (binanceAccounts.length > 0) {
        forwardActualPosition.value = binanceAccounts[0].balance?.total_positions || 0
      }

      // Aggregate fees from all accounts
      data.accounts.forEach(account => {
        if (account.platform_id === 2) {
          // Bybit accounts
          bybitLongSwapFee.value += account.balance?.long_swap_fee || 0
          bybitShortSwapFee.value += account.balance?.short_swap_fee || 0
        } else if (account.platform_id === 1) {
          // Binance accounts
          binanceLongFundingRate.value += account.balance?.long_funding_rate || 0
          binanceShortFundingRate.value += account.balance?.short_funding_rate || 0
        }
      })
    }

    // Extract actual positions from positions array for spread calculation
    if (data.positions && data.positions.length > 0) {
      // Reset position arrays
      binanceShortPositions.value = []
      binanceLongPositions.value = []
      bybitShortPositions.value = []
      bybitLongPositions.value = []

      // Aggregate positions by platform and side
      data.positions.forEach(position => {
        // Find the account for this position to get platform_id
        const account = data.accounts?.find(acc => acc.account_id === position.account_id)
        if (!account) return

        const posSize = Math.abs(position.size || 0)
        const posData = {
          size: posSize,
          entry_price: position.entry_price || 0,
          current_price: position.current_price || 0
        }

        if (account.platform_id === 2) {
          // Bybit MT5 positions
          if (position.side === 'Buy') {
            bybitLongPositions.value.push(posData)
          } else if (position.side === 'Sell') {
            bybitShortPositions.value.push(posData)
          }
        } else if (account.platform_id === 1) {
          // Binance positions
          if (position.side === 'Buy') {
            binanceLongPositions.value.push(posData)
          } else if (position.side === 'Sell') {
            binanceShortPositions.value.push(posData)
          }
        }
      })
    } else {
      // No positions, reset position arrays only
      binanceShortPositions.value = []
      binanceLongPositions.value = []
      bybitShortPositions.value = []
      bybitLongPositions.value = []
    }
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

// Export data for StrategyPanel to use
defineExpose({
  reverseActualPosition,
  forwardActualPosition,
  reverseSpread,
  forwardSpread,
  bybitLongSwapFee,
  bybitShortSwapFee,
  binanceLongFundingRate,
  binanceShortFundingRate
})
</script>

<style scoped>
/* 移动端H5竖屏适配 - 确保完全撑满宽度 */
@media (orientation: portrait), (max-width: 750px) {
  /* 移除所有内边距，让内容完全撑满 */
  :deep(.grid) {
    width: 100%;
  }

  /* 确保所有子元素也是100%宽度 */
  :deep(.bg-\[\#1e2329\]) {
    width: 100%;
    box-sizing: border-box;
  }
}
</style>
