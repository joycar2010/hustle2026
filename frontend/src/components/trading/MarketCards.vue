<template>
  <div class="h-full flex flex-col max-lg:h-auto overflow-hidden w-full">
    <!-- System Status Marquee -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <button
        @click="showSystemStatusModal = true"
        :class="[
          'w-full marquee-container flex items-center px-3 py-2 rounded-lg transition-colors cursor-pointer',
          systemHealthy ? 'bg-[#0ecb81]/20 hover:bg-[#0ecb81]/30' : 'bg-[#f6465d]/20 hover:bg-[#f6465d]/30'
        ]"
        :title="'点击查看详细系统状态'"
      >
        <div class="marquee-content text-xs whitespace-nowrap" :class="systemHealthy ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ systemStatusText }}
        </div>
      </button>
    </div>

    <!-- Total Profit Header -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <div class="bg-[#1e2329] rounded p-1.5 lg:p-1 flex items-center justify-center gap-2 w-full">
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
            <span
              @dblclick="resetBybitLag"
              class="text-[10px] lg:text-[9px] md:text-xs font-mono cursor-pointer hover:text-[#f0b90b] transition-colors"
              title="双击清零"
            >{{ bybitLagCount }}</span>
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
            <span
              @dblclick="resetBinanceLag"
              class="text-[10px] lg:text-[9px] md:text-xs font-mono cursor-pointer hover:text-[#f0b90b] transition-colors"
              title="双击清零"
            >{{ binanceLagCount }}</span>
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

    <!-- System Status Modal -->
    <SystemStatusModal :isOpen="showSystemStatusModal" @close="showSystemStatusModal = false" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'
import SystemStatusModal from '@/components/SystemStatusModal.vue'
import api from '@/services/api'
import SpreadDataTable from './SpreadDataTable.vue'

const marketStore = useMarketStore()
const notificationStore = useNotificationStore()

// System Status Modal
const showSystemStatusModal = ref(false)
const systemStatusText = ref('系统正常运行')
const systemHealthy = ref(true)
const redisStatus = ref({ healthy: false, last_error: null })

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })
const binance = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })

// Lag detection with sliding window (last 60 seconds)
const SLIDING_WINDOW_SIZE = 60 // 60 seconds
const LAG_THRESHOLD = 2000 // 2 seconds
const bybitUpdateTimestamps = ref([]) // Store last N update timestamps
const binanceUpdateTimestamps = ref([]) // Store last N update timestamps
let lastUpdateTime = Date.now()
let lagTimer = null

// Computed lag count based on sliding window
const bybitLagCount = computed(() => {
  const now = Date.now()
  const windowStart = now - SLIDING_WINDOW_SIZE * 1000

  // Remove old timestamps outside the window
  const recentTimestamps = bybitUpdateTimestamps.value.filter(t => t > windowStart)

  // Count gaps > LAG_THRESHOLD
  let lagCount = 0
  for (let i = 1; i < recentTimestamps.length; i++) {
    if (recentTimestamps[i] - recentTimestamps[i - 1] > LAG_THRESHOLD) {
      lagCount++
    }
  }

  // Check if current time has a lag
  if (recentTimestamps.length > 0 && now - recentTimestamps[recentTimestamps.length - 1] > LAG_THRESHOLD) {
    lagCount++
  }

  return lagCount
})

const binanceLagCount = computed(() => {
  const now = Date.now()
  const windowStart = now - SLIDING_WINDOW_SIZE * 1000

  // Remove old timestamps outside the window
  const recentTimestamps = binanceUpdateTimestamps.value.filter(t => t > windowStart)

  // Count gaps > LAG_THRESHOLD
  let lagCount = 0
  for (let i = 1; i < recentTimestamps.length; i++) {
    if (recentTimestamps[i] - recentTimestamps[i - 1] > LAG_THRESHOLD) {
      lagCount++
    }
  }

  // Check if current time has a lag
  if (recentTimestamps.length > 0 && now - recentTimestamps[recentTimestamps.length - 1] > LAG_THRESHOLD) {
    lagCount++
  }

  return lagCount
})

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

// USD/USDT exchange rate
const usdToUsdtRate = ref(1.0)
let exchangeRateTimer = null

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

// Calculate Binance floating profit (USDT)
const binanceFloatingProfit = computed(() => {
  let profit = 0

  // Binance LONG positions: (current_price - entry_price) × size
  binanceLongPositions.value.forEach(pos => {
    const currentPrice = binance.value.mid || pos.current_price
    profit += (currentPrice - pos.entry_price) * pos.size
  })

  // Binance SHORT positions: (entry_price - current_price) × size
  binanceShortPositions.value.forEach(pos => {
    const currentPrice = binance.value.mid || pos.current_price
    profit += (pos.entry_price - currentPrice) * pos.size
  })

  return profit
})

// Calculate Bybit floating profit (USD converted to USDT)
const bybitFloatingProfit = computed(() => {
  let profitUSD = 0

  // Bybit LONG positions: (current_price - entry_price) × size
  bybitLongPositions.value.forEach(pos => {
    const currentPrice = bybit.value.mid || pos.current_price
    profitUSD += (currentPrice - pos.entry_price) * pos.size
  })

  // Bybit SHORT positions: (entry_price - current_price) × size
  bybitShortPositions.value.forEach(pos => {
    const currentPrice = bybit.value.mid || pos.current_price
    profitUSD += (pos.entry_price - currentPrice) * pos.size
  })

  // Convert USD to USDT using real-time exchange rate
  return profitUSD * usdToUsdtRate.value
})

// Calculate total dual-side floating profit (USDT)
const totalProfit = computed(() => {
  return binanceFloatingProfit.value + bybitFloatingProfit.value
})

watch(() => marketStore.marketData, (data) => {
  if (!data) return

  const now = Date.now()

  // Add timestamp to sliding window
  bybitUpdateTimestamps.value.push(now)
  binanceUpdateTimestamps.value.push(now)

  // Keep only recent timestamps (last 60 seconds + buffer)
  const windowStart = now - (SLIDING_WINDOW_SIZE + 10) * 1000
  bybitUpdateTimestamps.value = bybitUpdateTimestamps.value.filter(t => t > windowStart)
  binanceUpdateTimestamps.value = binanceUpdateTimestamps.value.filter(t => t > windowStart)

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
  }
  // Note: If positions is empty or undefined, keep existing position arrays unchanged
}

onMounted(() => {
  marketStore.connect()

  // Initialize timestamps with current time
  const now = Date.now()
  bybitUpdateTimestamps.value = [now]
  binanceUpdateTimestamps.value = [now]
  lastUpdateTime = now

  // No longer need lagTimer as we use sliding window

  // Initial fetch (账户数据改为WebSocket推送，只保留初始加载)
  fetchAccountData()
  fetchPendingOrderCounts()
  fetchOrderBook()
  fetchRedisStatus()
  fetchExchangeRate()

  // Fetch pending order counts every 3 seconds
  orderFetchTimer = setInterval(() => {
    fetchPendingOrderCounts()
  }, 3000)

  // Fetch order book every 500ms
  orderBookFetchTimer = setInterval(() => {
    fetchOrderBook()
  }, 500)

  // Fetch exchange rate every 10 minutes
  exchangeRateTimer = setInterval(() => {
    fetchExchangeRate()
  }, 600000)

  // 监听 Redis 状态推送
  watch(() => marketStore.lastMessage, (message) => {
    if (message && message.type === 'redis_status') {
      redisStatus.value = message.data
    }
  })

  // 监听账户余额WebSocket推送（替代定时轮询）
  watch(() => marketStore.accountBalanceData, (data) => {
    if (data) {
      updateAccountBalanceFromWebSocket(data)
    }
  })

  // 初始化系统状态并开始轮询
  updateSystemStatus()
  const statusInterval = setInterval(updateSystemStatus, 10000)
  onUnmounted(() => {
    clearInterval(statusInterval)
  })
})

onUnmounted(() => {
  if (lagTimer) clearInterval(lagTimer)
  if (orderFetchTimer) clearInterval(orderFetchTimer)
  if (orderBookFetchTimer) clearInterval(orderBookFetchTimer)
  if (exchangeRateTimer) clearInterval(exchangeRateTimer)
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

// Reset lag count by clearing timestamp history
function resetBybitLag() {
  const now = Date.now()
  bybitUpdateTimestamps.value = [now]
  console.log('Bybit lag count reset')
}

function resetBinanceLag() {
  const now = Date.now()
  binanceUpdateTimestamps.value = [now]
  console.log('Binance lag count reset')
}

// Update account balance from WebSocket push
function updateAccountBalanceFromWebSocket(data) {
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

    // Categorize positions by platform and side
    data.positions.forEach(pos => {
      const posSize = Math.abs(pos.size || 0)
      const posData = {
        size: posSize,
        entry_price: pos.entry_price || 0,
        current_price: pos.current_price || 0
      }

      if (pos.platform_id === 1) {
        // Binance positions - check both 'SHORT'/'LONG' and 'Sell'/'Buy' formats
        if (pos.side === 'SHORT' || pos.side === 'Sell') {
          binanceShortPositions.value.push(posData)
        } else if (pos.side === 'LONG' || pos.side === 'Buy') {
          binanceLongPositions.value.push(posData)
        }
      } else if (pos.platform_id === 2) {
        // Bybit positions - check both 'SHORT'/'LONG' and 'Sell'/'Buy' formats
        if (pos.side === 'SHORT' || pos.side === 'Sell') {
          bybitShortPositions.value.push(posData)
        } else if (pos.side === 'LONG' || pos.side === 'Buy') {
          bybitLongPositions.value.push(posData)
        }
      }
    })
  }
  // Note: If positions is empty or undefined, keep existing position arrays unchanged
}

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

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
    }
    // Note: If positions is empty or undefined, keep existing position arrays unchanged
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

// System Status Update - 整合所有系统状态和服务状态
async function updateSystemStatus() {
  try {
    const response = await api.get('/api/v1/system/status')
    const data = response.data

    const statuses = []

    // WebSocket状态
    if (marketStore.connected) {
      statuses.push('WS已连接')
    } else {
      statuses.push('WS未连接')
    }

    // 数据库连接池状态
    if (data.dbPool) {
      const usage = Math.round((data.dbPool.active / data.dbPool.max) * 100)
      statuses.push(`DB连接池:${usage}%`)
    }

    // 后端服务状态
    if (data.backend) {
      statuses.push('后端API正常')
    }

    // 持仓监控状态
    if (data.positionMonitor) {
      statuses.push('持仓监控运行中')
    }

    // 策略管理状态
    if (data.strategyManager) {
      statuses.push('策略管理运行中')
    }

    // Binance连接状态
    if (data.binance) {
      statuses.push('Binance已连接')
    }

    // Bybit连接状态
    if (data.bybit) {
      statuses.push('Bybit已连接')
    }

    // MT5连接状态
    if (data.mt5) {
      statuses.push('MT5已连接')
    }

    // 飞书服务状态
    if (notificationStore.feishuServiceStatus) {
      statuses.push('飞书服务正常')
    } else {
      statuses.push('飞书服务异常')
    }

    // Redis状态
    if (redisStatus.value.healthy) {
      statuses.push('Redis正常')
    } else {
      statuses.push('Redis异常')
    }

    // 系统运行时间
    if (data.uptime) {
      statuses.push(`运行:${data.uptime}`)
    }

    systemStatusText.value = statuses.join(' | ') || '系统正常运行'

    // 判断系统健康状态
    const dbUsage = data.dbPool ? (data.dbPool.active / data.dbPool.max) : 0
    systemHealthy.value = data.backend &&
                          marketStore.connected &&
                          dbUsage < 0.8 &&
                          notificationStore.feishuServiceStatus &&
                          redisStatus.value.healthy
  } catch (error) {
    systemStatusText.value = '无法获取系统状态'
    systemHealthy.value = false
  }
}

async function fetchRedisStatus() {
  try {
    const response = await api.get('/api/v1/system/redis/status')
    redisStatus.value = response.data
  } catch (error) {
    console.error('Failed to fetch Redis status:', error)
    redisStatus.value = { healthy: false, last_error: 'Failed to fetch status' }
  }
}

// Fetch USD/USDT exchange rate from Binance API
async function fetchExchangeRate() {
  try {
    // Use Binance public API to get USDT price relative to USD
    // We use USDC/USDT as a proxy since USDC ≈ USD
    const response = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT')
    const data = await response.json()

    if (data.price) {
      // USDC/USDT price represents how many USDT = 1 USDC (≈ 1 USD)
      // So USD/USDT rate = USDC/USDT rate
      usdToUsdtRate.value = parseFloat(data.price)
      console.log('USD/USDT exchange rate updated:', usdToUsdtRate.value)
    }
  } catch (error) {
    console.error('Failed to fetch exchange rate, using default 1.0:', error)
    // Fallback to 1:1 if API fails
    usdToUsdtRate.value = 1.0
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
/* Hide scrollbar but keep scroll functionality */
.scrollbar-hide {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
}

.scrollbar-hide::-webkit-scrollbar {
  display: none; /* Chrome, Safari, Opera */
}

/* Marquee Animation */
.marquee-container {
  overflow: hidden;
  position: relative;
}

.marquee-content {
  display: inline-block;
  animation: marquee 20s linear infinite;
  padding-left: 100%;
}

.marquee-content:hover {
  animation-play-state: paused;
}

@keyframes marquee {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(-100%);
  }
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

/* 移动端H5竖屏适配 - 确保完全撑满宽度 (包括2K屏幕) */
@media (orientation: portrait) and (max-width: 1500px), (max-width: 750px) {
  /* 移除所有内边距，让内容完全撑满 */
  :deep(.grid) {
    width: 100%;
  }

  /* 确保所有子元素也是100%宽度 */
  :deep(.bg-\[\#1e2329\]) {
    width: 100%;
    box-sizing: border-box;
  }

  /* 确保容器占满宽度 */
  .h-full {
    width: 100% !important;
    max-width: 100vw;
  }

  /* 优化内边距 */
  .p-1\.5,
  .p-2 {
    padding: 0.375rem !important;
  }

  /* 统一字体大小 - 适用于所有移动设备（参考iPhone显示效果）*/
  .text-xs {
    font-size: 1rem !important;
  }

  .text-sm {
    font-size: 1.125rem !important;
  }

  .text-base {
    font-size: 1.25rem !important;
  }

  .text-lg {
    font-size: 1.5rem !important;
  }

  /* 统一内边距 */
  .p-1\.5,
  .p-2 {
    padding: 0.65rem !important;
  }

  .p-1 {
    padding: 0.45rem !important;
  }

  /* 统一间距 */
  .gap-1,
  .gap-1\.5,
  .gap-2 {
    gap: 0.45rem !important;
  }

  .space-x-1,
  .space-x-1\.5 {
    margin-left: 0.45rem !important;
  }

  .mb-1,
  .mb-1\.5 {
    margin-bottom: 0.45rem !important;
  }

  /* 统一图标大小 */
  .w-5,
  .h-5 {
    width: 1.5rem !important;
    height: 1.5rem !important;
  }

  .w-4,
  .h-4 {
    width: 1.25rem !important;
    height: 1.25rem !important;
  }

  /* 完全禁用动画 */
  * {
    animation: none !important;
    transition: none !important;
  }
}

/* ========== 移除单独的2K屏幕媒体查询 ========== */

</style>
