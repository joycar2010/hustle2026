<template>
  <div class="h-full flex flex-col max-lg:h-auto overflow-hidden">
    <!-- Total Profit Header -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0">
      <div class="bg-[#1e2329] rounded p-1.5 lg:p-1 flex items-center justify-center gap-2">
        <span class="text-xs lg:text-[10px] text-gray-400">总盈利</span>
        <span class="text-base lg:text-sm md:text-lg font-bold font-mono" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }}
        </span>
        <span class="text-xs lg:text-[10px] text-gray-400">USDT</span>
      </div>
    </div>

    <!-- Content Area -->
    <div class="flex-1 overflow-y-auto overflow-x-hidden p-1.5 lg:p-1 md:p-2 scrollbar-hide">
      <div class="grid grid-cols-1 gap-1.5 lg:gap-1 md:gap-2">
      <!-- Bybit MT5 Card -->
      <div class="bg-[#252930] rounded p-1.5 lg:p-1.5 md:p-2 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="flex items-center space-x-1.5 lg:space-x-1">
            <div class="w-5 h-5 lg:w-4 lg:h-4 md:w-6 md:h-6 bg-[#ff9800] rounded flex items-center justify-center">
              <span class="text-white font-bold text-sm lg:text-xs md:text-base">B</span>
            </div>
            <div>
              <div class="font-medium text-sm lg:text-xs md:text-base">Bybit MT5 <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">XAUUSD.s</span></div>
            </div>
          </div>
        </div>

        <!-- Real-time Price (Full Width) -->
        <div class="mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400 text-center">实时价格</div>
            <div class="text-xl lg:text-lg md:text-2xl font-mono font-bold text-[#0ecb81] text-center">
              {{ formatPrice(bybit.mid) }}
            </div>
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-1 lg:gap-0.5 md:gap-1.5 mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">ASK</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">BID</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }}
            </div>
          </div>
        </div>

        <!-- Order Book Data Row (Bybit MT5 XAUUSD.s) -->
        <div class="grid grid-cols-4 gap-0.5 mb-1 lg:mb-0.5 md:mb-1.5 text-base lg:text-sm md:text-xl">
          <div class="text-center text-[#3b82f6] font-mono">{{ formatVolume(bybitOrderBook.ask_volume) }}</div>
          <div class="text-center text-[#0ecb81] font-mono">{{ formatPrice(bybitOrderBook.ask_price) }}</div>
          <div class="text-center text-[#f6465d] font-mono">{{ formatPrice(bybitOrderBook.bid_price) }}</div>
          <div class="text-center text-[#3b82f6] font-mono">{{ formatVolume(bybitOrderBook.bid_volume) }}</div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-0.5 lg:pt-0.5 md:pt-1 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1 lg:space-x-0.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-0.5 lg:w-0.5 h-2 lg:h-1.5 md:h-2.5 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-[10px] lg:text-[9px] md:text-xs font-mono">{{ bybitLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Binance Card -->
      <div class="bg-[#252930] rounded p-1.5 lg:p-1.5 md:p-2 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="flex items-center space-x-1.5 lg:space-x-1">
            <div class="w-5 h-5 lg:w-4 lg:h-4 md:w-6 md:h-6 bg-[#f0b90b] rounded flex items-center justify-center">
              <span class="text-[#1a1d21] font-bold text-sm lg:text-xs md:text-base">B</span>
            </div>
            <div>
              <div class="font-medium text-sm lg:text-xs md:text-base">Binance <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">XAUUSDT</span></div>
            </div>
          </div>
        </div>

        <!-- Real-time Price (Full Width) -->
        <div class="mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400 text-center">实时价格</div>
            <div class="text-xl lg:text-lg md:text-2xl font-mono font-bold text-[#f6465d] text-center">
              {{ formatPrice(binance.mid) }}
            </div>
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-1 lg:gap-0.5 md:gap-1.5 mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139] relative cursor-pointer hover:border-[#3b4149] transition-colors" @click="showPendingOrdersModal('ASK')">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">ASK</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }}
            </div>
            <div v-if="askOrderCount > 0" class="absolute top-0.5 right-0.5 bg-yellow-600 text-white text-[9px] px-1 py-0.5 rounded font-bold">
              挂{{ askOrderCount }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139] relative cursor-pointer hover:border-[#3b4149] transition-colors" @click="showPendingOrdersModal('BID')">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">BID</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }}
            </div>
            <div v-if="bidOrderCount > 0" class="absolute top-0.5 right-0.5 bg-yellow-600 text-white text-[9px] px-1 py-0.5 rounded font-bold">
              挂{{ bidOrderCount }}
            </div>
          </div>
        </div>

        <!-- Order Book Data Row (Binance XAUUSDT) -->
        <div class="grid grid-cols-4 gap-0.5 mb-1 lg:mb-0.5 md:mb-1.5 text-base lg:text-sm md:text-xl">
          <div class="text-center text-[#3b82f6] font-mono">{{ formatVolume(binanceOrderBook.ask_volume) }}</div>
          <div class="text-center text-[#0ecb81] font-mono">{{ formatPrice(binanceOrderBook.ask_price) }}</div>
          <div class="text-center text-[#f6465d] font-mono">{{ formatPrice(binanceOrderBook.bid_price) }}</div>
          <div class="text-center text-[#3b82f6] font-mono">{{ formatVolume(binanceOrderBook.bid_volume) }}</div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-0.5 lg:pt-0.5 md:pt-1 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1 lg:space-x-0.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-0.5 lg:w-0.5 h-2 lg:h-1.5 md:h-2.5 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-[10px] lg:text-[9px] md:text-xs font-mono">{{ binanceLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Spread Data Table -->
      <div class="mt-1">
        <SpreadDataTable />
      </div>

      <!-- Pending Orders Modal -->
      <div v-if="showModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click="closeModal">
        <div class="bg-[#1e2329] rounded-lg p-6 max-w-4xl w-full mx-4 max-h-[80vh] overflow-auto" @click.stop>
          <div class="flex justify-between items-center mb-4">
            <h3 class="text-xl font-bold text-white">{{ modalType === 'ASK' ? 'ASK挂单' : 'BID挂单' }}</h3>
            <button @click="closeModal" class="text-gray-400 hover:text-white text-2xl">&times;</button>
          </div>

          <div v-if="pendingOrders.length === 0" class="text-center text-gray-400 py-8">
            暂无挂单
          </div>

          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-[#2b3139]">
                  <th class="text-left py-2 px-3 text-gray-400">交易所</th>
                  <th class="text-left py-2 px-3 text-gray-400">方向</th>
                  <th class="text-right py-2 px-3 text-gray-400">价格</th>
                  <th class="text-right py-2 px-3 text-gray-400">数量</th>
                  <th class="text-right py-2 px-3 text-gray-400">已成交</th>
                  <th class="text-left py-2 px-3 text-gray-400">状态</th>
                  <th class="text-left py-2 px-3 text-gray-400">时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="order in pendingOrders" :key="order.order_id" class="border-b border-[#2b3139] hover:bg-[#2b3139]">
                  <td class="py-2 px-3 text-white">{{ order.exchange }}</td>
                  <td class="py-2 px-3">
                    <span :class="order.side === 'Buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                      {{ order.side === 'Buy' ? '买入' : '卖出' }}
                    </span>
                  </td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.price?.toFixed(2) || '-' }}</td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.qty?.toFixed(4) || '-' }}</td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.cum_exec_qty?.toFixed(4) || '0' }}</td>
                  <td class="py-2 px-3 text-white">{{ order.order_status }}</td>
                  <td class="py-2 px-3 text-gray-400 text-xs">{{ formatTime(order.created_time) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      </div>
    </div>

    <!-- Fixed Navigation Panel at Bottom -->
    <div class="flex-shrink-0" style="margin-top: 10%;">
      <NavigationPanel />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'
import SpreadDataTable from './SpreadDataTable.vue'
import NavigationPanel from './NavigationPanel.vue'

const marketStore = useMarketStore()

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })
const binance = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })

const bybitLagCount = ref(0)
const binanceLagCount = ref(0)
let lastUpdateTime = Date.now()
let lagTimer = null

// Pending orders data
const askOrderCount = ref(0)
const bidOrderCount = ref(0)
const showModal = ref(false)
const modalType = ref('') // 'ASK' or 'BID'
const pendingOrders = ref([])
let orderFetchTimer = null

// Order book data
const bybitOrderBook = ref({ bid_price: 0, bid_volume: 0, ask_price: 0, ask_volume: 0 })
const binanceOrderBook = ref({ bid_price: 0, bid_volume: 0, ask_price: 0, ask_volume: 0 })
let orderBookFetchTimer = null

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

  // Throttle updates to reduce re-renders
  const now = Date.now()
  if (now - lastUpdateTime > 2000) {
    bybitLagCount.value++
    binanceLagCount.value++
  }
  lastUpdateTime = now

  // Only update if values actually changed
  const bybitBidChanged = bybit.value.bid !== (data.bybit_bid || 0)
  const bybitAskChanged = bybit.value.ask !== (data.bybit_ask || 0)
  const binanceBidChanged = binance.value.bid !== (data.binance_bid || 0)
  const binanceAskChanged = binance.value.ask !== (data.binance_ask || 0)

  if (bybitBidChanged || bybitAskChanged || binanceBidChanged || binanceAskChanged) {
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
  }
}, { deep: false }) // Shallow watch for better performance

watch(() => marketStore.connected, (val) => {
  if (!val) {
    bybitConnected.value = false
    binanceConnected.value = false
  }
}, { deep: false })

// Watch for account balance updates via WebSocket
// Optimized: Only trigger when message type is account_balance
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
}, { deep: false })

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
  fetchPendingOrderCounts()
  fetchOrderBook()

  // Fetch pending order counts every 3 seconds
  orderFetchTimer = setInterval(() => {
    fetchPendingOrderCounts()
  }, 3000)

  // Fetch order book every 500ms
  orderBookFetchTimer = setInterval(() => {
    fetchOrderBook()
  }, 500)
})

onUnmounted(() => {
  if (lagTimer) clearInterval(lagTimer)
  if (orderFetchTimer) clearInterval(orderFetchTimer)
  if (orderBookFetchTimer) clearInterval(orderBookFetchTimer)
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

async function fetchPendingOrderCounts() {
  try {
    const response = await api.get('/api/v1/trading/orders/realtime')
    const orders = response.data || []

    // Count ASK and BID orders
    askOrderCount.value = orders.filter(order => order.side === 'Sell').length
    bidOrderCount.value = orders.filter(order => order.side === 'Buy').length
  } catch (error) {
    console.error('Failed to fetch pending orders:', error)
  }
}

async function fetchOrderBook() {
  try {
    const response = await api.get('/api/v1/market/orderbook')
    const data = response.data || {}

    // Update Bybit order book (MT5 volume in lots, 1 lot = 100 oz)
    if (data.bybit && data.bybit.bid_price) {
      bybitOrderBook.value = {
        bid_price: data.bybit.bid_price || 0,
        bid_volume: data.bybit.bid_volume || 0,
        ask_price: data.bybit.ask_price || 0,
        ask_volume: data.bybit.ask_volume || 0
      }
    }

    // Update Binance order book (volume in contracts, 1 contract = 1 oz)
    if (data.binance && data.binance.bid_price) {
      binanceOrderBook.value = {
        bid_price: data.binance.bid_price || 0,
        bid_volume: data.binance.bid_volume || 0,
        ask_price: data.binance.ask_price || 0,
        ask_volume: data.binance.ask_volume || 0
      }
    }
  } catch (error) {
    console.error('Failed to fetch order book:', error)
  }
}

async function showPendingOrdersModal(type) {
  try {
    const response = await api.get('/api/v1/trading/orders/realtime')
    const orders = response.data || []

    // Filter orders by type
    if (type === 'ASK') {
      pendingOrders.value = orders.filter(order => order.side === 'Sell')
    } else {
      pendingOrders.value = orders.filter(order => order.side === 'Buy')
    }

    modalType.value = type
    showModal.value = true
  } catch (error) {
    console.error('Failed to fetch pending orders:', error)
  }
}

function closeModal() {
  showModal.value = false
  pendingOrders.value = []
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatVolume(volume) {
  if (!volume || volume === 0) return '0'
  return volume.toFixed(2)
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
/* Hide scrollbar but keep scroll functionality */
.scrollbar-hide {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
}

.scrollbar-hide::-webkit-scrollbar {
  display: none; /* Chrome, Safari, Opera */
}

/* Smooth transitions for price updates */
.text-2xl, .text-xl, .text-lg {
  transition: color 0.3s ease-in-out, transform 0.2s ease-in-out;
}

/* Pulse animation for price changes */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.8;
  }
}

.font-mono {
  transition: all 0.2s ease-in-out;
}

/* Smooth background transitions */
.bg-\[#1e2329\] {
  transition: background-color 0.3s ease-in-out;
}

/* Smooth status indicator transitions */
.bg-green-500, .bg-red-500, .bg-gray-500 {
  transition: background-color 0.3s ease-in-out;
}

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
