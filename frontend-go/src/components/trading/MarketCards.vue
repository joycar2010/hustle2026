<template>
  <div class="h-full flex flex-col max-lg:h-auto overflow-hidden w-full">
    <!-- System Status Marquee -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <button
        @click="showSystemStatusModal = true"
        :class="[
          'w-full flex items-center px-3 py-2 rounded-lg transition-colors cursor-pointer',
          systemHealthy ? 'bg-[#0ecb81]/20 hover:bg-[#0ecb81]/30' : 'bg-[#f6465d]/20 hover:bg-[#f6465d]/30'
        ]"
        :title="'点击查看详细系统状态'"
      >
        <div class="marquee-container w-full overflow-hidden">
          <div class="marquee-content text-xs whitespace-nowrap" :class="systemHealthy ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ systemStatusText }}
          </div>
        </div>
      </button>
    </div>

    <!-- Market Close Warning -->
    <div v-if="!marketOpen" class="px-1.5 lg:px-1.5 md:px-2 pt-1.5 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <div class="bg-[#f6465d]/15 border border-[#f6465d]/30 rounded px-3 py-1.5 flex items-center justify-center gap-2">
        <span class="text-[#f6465d] text-xs font-medium">{{ marketMessage }}</span>
      </div>
    </div>
    <div v-else-if="marketWarning" class="px-1.5 lg:px-1.5 md:px-2 pt-1.5 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <div class="bg-[#f0b90b]/15 border border-[#f0b90b]/30 rounded px-3 py-1.5 flex items-center justify-center gap-2">
        <span class="text-[#f0b90b] text-xs font-medium">{{ marketMessage }}</span>
      </div>
    </div>

    <!-- Total Profit Header -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <div class="bg-[#1e2329] rounded p-1.5 lg:p-1 flex items-center justify-center gap-2 w-full">
        <span class="text-xs lg:text-[10px] text-gray-400">实时持仓盈利</span>
        <span class="text-base lg:text-sm md:text-lg font-bold font-mono" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }}
        </span>
        <span class="text-xs lg:text-[10px] text-gray-400">USDT</span>
      </div>
    </div>

    <!-- Content Area -->
    <div class="flex-1 overflow-y-auto overflow-x-hidden p-1.5 lg:p-1 md:p-2 scrollbar-hide">
      <div class="grid grid-cols-1 gap-1.5 lg:gap-1 md:gap-2">
      <!-- 对冲账户 Card -->
      <div class="bg-[#252930] rounded p-1.5 lg:p-1.5 md:p-2 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="font-medium text-sm lg:text-xs md:text-base">对冲账户 <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">{{ pairConfig.mt5 }}</span></div>
        </div>

        <!-- Real-time Price with liquidation prices on left (long) and right (short) -->
        <div class="mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400 text-center">实时价格</div>
            <div class="flex items-center justify-between gap-1">
              <!-- 多头强平价（左侧）-->
              <div class="flex flex-col items-start min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">多强平</span>
                <span class="text-[20px] lg:text-[18px] font-mono font-bold text-[#0ecb81] leading-tight">
                  {{ strategyStore.liquidationPrices.mt5.long != null ? formatPrice(strategyStore.liquidationPrices.mt5.long) : '暂无' }}
                </span>
              </div>
              <!-- 实时价格（中间）-->
              <div class="text-xl lg:text-lg md:text-2xl font-mono font-bold text-[#0ecb81] text-center flex-1">
                {{ formatPrice(bybit.mid) }}
              </div>
              <!-- 空头强平价（右侧）-->
              <div class="flex flex-col items-end min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">空强平</span>
                <span class="text-[20px] lg:text-[18px] font-mono font-bold text-[#f6465d] leading-tight">
                  {{ strategyStore.liquidationPrices.mt5.short != null ? formatPrice(strategyStore.liquidationPrices.mt5.short) : '暂无' }}
                </span>
              </div>
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

        <!-- Order Book Data Row (对冲账户 XAUUSD.s) -->
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

      <!-- 主账号 Card -->
      <div class="bg-[#252930] rounded p-1.5 lg:p-1.5 md:p-2 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="font-medium text-sm lg:text-xs md:text-base">主账号 <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">{{ pairConfig.binance }}</span></div>
        </div>

        <!-- Real-time Price with liquidation prices on left (long) and right (short) -->
        <div class="mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400 text-center">实时价格</div>
            <div class="flex items-center justify-between gap-1">
              <!-- 多头强平价（左侧）-->
              <div class="flex flex-col items-start min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">多强平</span>
                <span class="text-[20px] lg:text-[18px] font-mono font-bold text-[#0ecb81] leading-tight">
                  {{ strategyStore.liquidationPrices.binance.long != null ? formatPrice(strategyStore.liquidationPrices.binance.long) : '暂无' }}
                </span>
              </div>
              <!-- 实时价格（中间）-->
              <div class="text-xl lg:text-lg md:text-2xl font-mono font-bold text-[#f6465d] text-center flex-1">
                {{ formatPrice(binance.mid) }}
              </div>
              <!-- 空头强平价（右侧）-->
              <div class="flex flex-col items-end min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">空强平</span>
                <span class="text-[20px] lg:text-[18px] font-mono font-bold text-[#f6465d] leading-tight">
                  {{ strategyStore.liquidationPrices.binance.short != null ? formatPrice(strategyStore.liquidationPrices.binance.short) : '暂无' }}
                </span>
              </div>
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

        <!-- Order Book Data Row (主账号 XAUUSDT) -->
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
                <tr v-for="order in pendingOrders" :key="order.id" class="border-b border-[#2b3139] hover:bg-[#2b3139]">
                  <td class="py-2 px-3 text-white">{{ order.exchange }}</td>
                  <td class="py-2 px-3">
                    <span :class="order.side === 'buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                      {{ order.side === 'buy' ? '买入' : '卖出' }}
                    </span>
                  </td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.price?.toFixed(2) || '-' }}</td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.quantity?.toFixed(4) || '-' }}</td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ (order.executed_qty ?? order.cum_exec_qty)?.toFixed(4) || '0' }}</td>
                  <td class="py-2 px-3 text-white">{{ order.status || order.order_status }}</td>
                  <td class="py-2 px-3 text-gray-400 text-xs">{{ formatTime(order.timestamp || order.created_time) }}</td>
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
import { useProxyStore } from '@/stores/proxy'
import { useStrategyStore } from '@/stores/strategy'
import SystemStatusModal from '@/components/SystemStatusModal.vue'
import api from '@/services/api'
import SpreadDataTable from './SpreadDataTable.vue'
import { useTradingPair } from '@/composables/useTradingPair'

const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const { currentPair, pairConfig } = useTradingPair()
const proxyStore = useProxyStore()
const strategyStore = useStrategyStore()

// System Status Modal
const showSystemStatusModal = ref(false)
const systemStatusText = ref('系统正常运行')
const systemHealthy = ref(true)
const redisStatus = ref({ healthy: false, last_error: null })

// Market close status
const marketOpen = ref(true)
const marketWarning = ref(false)
const marketMessage = ref('')
let marketStatusTimer = null

async function checkMarketStatus() {
  try {
    const r = await api.get('/api/v1/system/market-status')
    const d = r.data
    marketOpen.value = d.is_open !== false
    marketMessage.value = d.message || ''
    marketWarning.value = marketOpen.value && marketMessage.value.includes('即将休市')
  } catch { /* silent */ }
}
const sslCertStatus = ref({ status: 'unknown', days_remaining: 0 })
const proxyHealthStatus = ref({ total: 0, active: 0, failed: 0, avgHealth: 100 })

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

// 后端已算好的账户余额缓存（含 unrealized_pnl）
// 由 fetchAccountData / handleAccountBalanceUpdate 更新
// key: platform_id (1=Binance, 2=MT5)
const accountsBalanceByPlatform = ref({})  // { 1: balance, 2: balance }

// Position spread data - store position details for cost calculation
const binanceShortPositions = ref([]) // Binance SHORT positions
const binanceLongPositions = ref([]) // Binance LONG positions
const bybitShortPositions = ref([]) // Bybit SHORT positions
const bybitLongPositions = ref([]) // Bybit LONG positions

// Computed position totals
const binanceLongTotal = computed(() => {
  return binanceLongPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})
const binanceShortTotal = computed(() => {
  return binanceShortPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})
const bybitLongTotal = computed(() => {
  return bybitLongPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})
const bybitShortTotal = computed(() => {
  return bybitShortPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})

// Fee data
const bybitLongSwapFee = ref(0)
const bybitShortSwapFee = ref(0)
let bybitSwapRateTimer = null
// Binance real-time funding rate (per lot = 100 XAU)
const binanceLongFundingRate = ref(0)   // long_cost_per_lot: >0 long pays, <0 long receives
const binanceShortFundingRate = ref(0)  // short_cost_per_lot: opposite sign
const binanceFundingRatePct = ref(0)    // raw rate percentage for display
const binanceNextFundingTime = ref(0)   // next settlement timestamp ms
let fundingRateTimer = null

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
// 优先使用后端已算好的 unrealized_pnl（来自 Binance totalUnrealizedProfit）
// 后端 balance.unrealized_pnl 即为 Binance 账户当前持仓实时浮动盈亏（USDT）
const binanceFloatingProfit = computed(() => {
  const b = accountsBalanceByPlatform.value[1]
  if (b && b.unrealized_pnl != null) return parseFloat(b.unrealized_pnl)

  // fallback：用仓位数据估算（仅在后端数据未到达时）
  let profit = 0
  binanceLongPositions.value.forEach(pos => {
    const markPrice = binance.value.mid || pos.mark_price
    profit += (markPrice - pos.entry_price) * pos.size
  })
  binanceShortPositions.value.forEach(pos => {
    const markPrice = binance.value.mid || pos.mark_price
    profit += (pos.entry_price - markPrice) * pos.size
  })
  return profit
})

// Calculate Bybit/MT5 floating profit (USDT)
// 优先使用后端已算好的 unrealized_pnl（= equity - balance，MT5 终端"盈亏"列）
// 后端已处理合约乘数和 USD→USDT 汇率换算，直接使用，无需前端重算
const bybitFloatingProfit = computed(() => {
  const b = accountsBalanceByPlatform.value[2]
  if (b && b.unrealized_pnl != null) return parseFloat(b.unrealized_pnl)

  // fallback：用仓位数据估算（仅在后端数据未到达时，注意汇率可能有偏差）
  let profitUSD = 0
  bybitLongPositions.value.forEach(pos => {
    const markPrice = bybit.value.mid || pos.mark_price
    profitUSD += (markPrice - pos.entry_price) * pos.size
  })
  bybitShortPositions.value.forEach(pos => {
    const markPrice = bybit.value.mid || pos.mark_price
    profitUSD += (pos.entry_price - markPrice) * pos.size
  })
  return profitUSD * usdToUsdtRate.value
})

// 总盈利 = Binance 实时浮动盈亏 + MT5 实时浮动盈亏
// Binance: totalUnrealizedProfit（当前所有仓位的未实现盈亏）
// MT5:     equity - balance（当前所有仓位的浮动盈亏，MT5 终端"盈亏"列之和）
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

// Watch global pair selection — refresh all market data when pair changes
watch(currentPair, () => {
  fetchOrderBook()
  fetchBinanceFundingRate()
  fetchBybitSwapRate()
})

watch(() => marketStore.connected, (val) => {
  if (!val) {
    bybitConnected.value = false
    binanceConnected.value = false
  }
}, { deep: false })

// Watch for account balance updates via WebSocket
// Optimized: Only trigger when message type is account_balance
watch(() => marketStore.lastMessage, (message) => {
  if (!message) return
  if (message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  } else if (message.type === 'position_snapshot') {
    handlePositionSnapshot(message.data)
  } else if (message.type === 'mt5_position_update') {
    handleMt5PositionUpdate(message.data)
  } else if (message.type === 'pending_orders' && message.data) {
    // Real-time pending orders from WS (pushed every 2s by PendingOrdersStreamer)
    if (Array.isArray(message.data)) {
      pendingOrderCount.value = message.data.length
    }
  } else if (message.type === 'redis_status') {
    redisStatus.value = message.data
  }
}, { deep: false })

// position_snapshot: real-time data pushed immediately after a trade fill.
// Atomically replaces both Bybit and Binance positions — no intermediate zero state, no flash.
function handlePositionSnapshot(data) {
  if (!data) return
  const longLots = data.bybit_long_lots ?? 0
  const shortLots = data.bybit_short_lots ?? 0
  const binanceLong = data.binance_long_xau ?? 0
  const binanceShort = data.binance_short_xau ?? 0
  // Atomic swap: replace all arrays in one tick
  bybitLongPositions.value = longLots > 0 ? [{ size: longLots }] : []
  bybitShortPositions.value = shortLots > 0 ? [{ size: shortLots }] : []
  if (binanceLong > 0 || binanceShort > 0) {
    binanceLongPositions.value = binanceLong > 0 ? [{ size: binanceLong }] : []
    binanceShortPositions.value = binanceShort > 0 ? [{ size: binanceShort }] : []
  }
}

function handleAccountBalanceUpdate(data) {
  console.log('[handleAccountBalanceUpdate] Received data:', {
    accountsCount: data.accounts?.length,
    positionsCount: data.positions?.length,
    positions: data.positions
  })

  // 缓存各平台余额 unrealized_pnl，供 totalProfit 计算使用
  // 每用户一个 Binance(1) + 一个 MT5(2)，直接按 platform_id 存
  if (data.accounts && data.accounts.length > 0) {
    const newBalances = {}
    data.accounts.forEach(acc => {
      if (acc.balance && acc.platform_id) {
        newBalances[acc.platform_id] = acc.balance
      }
    })
    accountsBalanceByPlatform.value = newBalances
  }

  // Extract fee data from accounts
  if (data.accounts && data.accounts.length > 0) {
    // Note: bybitLongSwapFee / bybitShortSwapFee are now fetched in real-time
    // via fetchBybitSwapRate() polling — do NOT overwrite them here.

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
        // Bybit swap rate is now fetched in real-time via fetchBybitSwapRate()
        // Binance funding rate is fetched in real-time via fetchBinanceFundingRate()
      }
    })
  }

  // Extract actual positions from positions array for spread calculation
  if (data.positions && data.positions.length > 0) {
    // Build new arrays first, then atomically swap — prevents flash-to-zero
    const newBinanceLong = []
    const newBinanceShort = []
    const newBybitLong = []
    const newBybitShort = []

    data.positions.forEach(position => {
      const account = data.accounts?.find(acc => acc.account_id === position.account_id)
      if (!account) return

      // Backend schema (AccountPosition): side / size / entry_price / mark_price / unrealized_pnl
      const posData = {
        size: Math.abs(position.size || 0),
        entry_price: position.entry_price || 0,
        mark_price: position.mark_price || 0
      }

      if (account.platform_id === 2) {
        if (position.side === 'Buy') newBybitLong.push(posData)
        else if (position.side === 'Sell') newBybitShort.push(posData)
      } else if (account.platform_id === 1) {
        if (position.side === 'Buy') newBinanceLong.push(posData)
        else if (position.side === 'Sell') newBinanceShort.push(posData)
      }
    })

    // Atomic swap — all four refs update in the same microtask, no intermediate empty state
    binanceLongPositions.value = newBinanceLong
    binanceShortPositions.value = newBinanceShort
    bybitLongPositions.value = newBybitLong
    bybitShortPositions.value = newBybitShort
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

  // Fetch initial position data immediately on page load (prevents 0.00 display until WebSocket update)
  fetchAccountData()
  // Position data is then kept up-to-date via WebSocket (account_balance / position_snapshot)
  fetchPendingOrderCounts()
  fetchOrderBook()
  fetchRedisStatus()
  fetchSSLCertStatus()
  fetchProxyHealthStatus()
  fetchExchangeRate()
  fetchBinanceFundingRate()
  checkMarketStatus()

  // Pending orders: WS pending_orders pushed every 2s from backend; no HTTP polling needed

  // Order book: removed 500ms polling (WS spread provides bid/ask in real-time)
  // fetchOrderBook() called once on mount above

  // Fetch exchange rate every 10 minutes
  exchangeRateTimer = setInterval(() => {
    fetchExchangeRate()
  }, 600000)

  // Funding rate changes every 8h; poll every 5 minutes as safety fallback
  fundingRateTimer = setInterval(() => {
    fetchBinanceFundingRate()
  }, 300000)

  // Swap rate changes daily; poll every 5 minutes
  fetchBybitSwapRate()
  bybitSwapRateTimer = setInterval(() => {
    fetchBybitSwapRate()
  }, 300000)

  // Check market status every 60 seconds
  marketStatusTimer = setInterval(checkMarketStatus, 300000) // market open/close changes ~2x/day

  // 初始化系统状态并开始轮询
  updateSystemStatus()
  const statusInterval = setInterval(updateSystemStatus, 60000) // WS redis_status is real-time; HTTP as 60s fallback
  const proxyHealthInterval = setInterval(fetchProxyHealthStatus, 120000) // proxy health every 2 min
  onUnmounted(() => {
    clearInterval(statusInterval)
    clearInterval(proxyHealthInterval)
  })
})

onUnmounted(() => {
  if (lagTimer) clearInterval(lagTimer)
  // orderFetchTimer removed (WS pending_orders handles it)
  // orderBookFetchTimer removed (polling eliminated)
  if (exchangeRateTimer) clearInterval(exchangeRateTimer)
  if (fundingRateTimer) clearInterval(fundingRateTimer)
  if (bybitSwapRateTimer) clearInterval(bybitSwapRateTimer)
  if (marketStatusTimer) clearInterval(marketStatusTimer)
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

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

    // Extract fee data and positions from accounts
    if (data.accounts && data.accounts.length > 0) {
      // Note: bybitLongSwapFee / bybitShortSwapFee are now fetched in real-time
      // via fetchBybitSwapRate() polling — do NOT overwrite them here.

      // 缓存各平台余额 unrealized_pnl，供 totalProfit 计算使用
      // 每个用户只有一个 Binance(1) + 一个 MT5(2)，直接按 platform_id 存
      const newBalances = {}
      data.accounts.forEach(acc => {
        if (acc.balance && acc.platform_id) {
          newBalances[acc.platform_id] = acc.balance
        }
      })
      accountsBalanceByPlatform.value = newBalances

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
          // Bybit swap rate is now fetched in real-time via fetchBybitSwapRate()
          // Binance funding rate is fetched in real-time via fetchBinanceFundingRate()
        }
      })
    }

    // Extract actual positions from positions array for spread calculation
    if (data.positions && data.positions.length > 0) {
      // Reset position arrays
      // Build new arrays atomically — prevents flash-to-zero during reset
      const newBinanceLong = []
      const newBinanceShort = []
      const newBybitLong = []
      const newBybitShort = []

      // Aggregate positions by platform and side
      data.positions.forEach(position => {
        // Find the account for this position to get platform_id
        const account = data.accounts?.find(acc => acc.account_id === position.account_id)
        if (!account) return

        // Backend schema (AccountPosition): side / size / entry_price / mark_price / unrealized_pnl
        const posData = {
          size: Math.abs(position.size || 0),
          entry_price: position.entry_price || 0,
          mark_price: position.mark_price || 0
        }

        if (account.platform_id === 2) {
          if (position.side === 'Buy') newBybitLong.push(posData)
          else if (position.side === 'Sell') newBybitShort.push(posData)
        } else if (account.platform_id === 1) {
          if (position.side === 'Buy') newBinanceLong.push(posData)
          else if (position.side === 'Sell') newBinanceShort.push(posData)
        }
      })

      // Atomic swap
      binanceLongPositions.value = newBinanceLong
      binanceShortPositions.value = newBinanceShort
      bybitLongPositions.value = newBybitLong
      bybitShortPositions.value = newBybitShort
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

    console.log('[fetchPendingOrderCounts] Fetched orders:', orders.length, orders)

    // Count ASK and BID orders (backend returns lowercase 'buy' and 'sell')
    const askCount = orders.filter(order => order.side === 'sell').length
    const bidCount = orders.filter(order => order.side === 'buy').length

    askOrderCount.value = askCount
    bidOrderCount.value = bidCount

    console.log('[fetchPendingOrderCounts] ASK count:', askCount, 'BID count:', bidCount)
  } catch (error) {
    console.error('Failed to fetch pending orders:', error)
  }
}

async function fetchOrderBook() {
  try {
    const response = await api.get('/api/v1/market/orderbook', {
      params: { pair_code: currentPair.value }
    })
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

    // Filter orders by type (backend returns lowercase 'buy' and 'sell')
    if (type === 'ASK') {
      pendingOrders.value = orders.filter(order => order.side === 'sell')
    } else {
      pendingOrders.value = orders.filter(order => order.side === 'buy')
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

    // SSL证书状态
    if (sslCertStatus.value.status === 'healthy') {
      statuses.push(`SSL证书正常(${sslCertStatus.value.days_remaining}天)`)
    } else if (sslCertStatus.value.status === 'warning') {
      statuses.push(`SSL证书即将过期(${sslCertStatus.value.days_remaining}天)`)
    } else if (sslCertStatus.value.status === 'critical' || sslCertStatus.value.status === 'expired') {
      statuses.push('SSL证书异常')
    }

    // 系统运行时间
    if (data.uptime) {
      statuses.push(`运行:${data.uptime}`)
    }

    // 代理健康状态
    if (proxyHealthStatus.value.total > 0) {
      const proxyStatus = `代理:${proxyHealthStatus.value.active}/${proxyHealthStatus.value.total}活跃`
      if (proxyHealthStatus.value.avgHealth < 50) {
        statuses.push(`⚠️${proxyStatus}(健康度:${proxyHealthStatus.value.avgHealth})`)
      } else if (proxyHealthStatus.value.failed > 0) {
        statuses.push(`${proxyStatus}(${proxyHealthStatus.value.failed}失败)`)
      } else {
        statuses.push(proxyStatus)
      }
    }

    systemStatusText.value = statuses.join(' | ') || '系统正常运行'

    // 判断系统健康状态
    const dbUsage = data.dbPool ? (data.dbPool.active / data.dbPool.max) : 0
    const sslHealthy = ['healthy', 'warning'].includes(sslCertStatus.value.status)
    // Proxy: no proxies configured = direct-connect, considered healthy
    const proxyHealthy = proxyHealthStatus.value.total === 0 ||
                         (proxyHealthStatus.value.avgHealth >= 50 && proxyHealthStatus.value.failed === 0)
    systemHealthy.value = data.backend &&
                          marketStore.connected &&
                          dbUsage < 0.8 &&
                          redisStatus.value.healthy &&
                          sslHealthy &&
                          proxyHealthy
  } catch (error) {
    systemStatusText.value = '无法获取系统状态'
    systemHealthy.value = false
  }
}

async function fetchRedisStatus() {
  try {
    // Use Go-native /monitor/status for Redis info (independent of Python backend).
    // The Go handler pings Redis directly via db.Redis().
    const response = await api.get('/api/v1/monitor/status')
    const redis = response.data?.redis
    redisStatus.value = {
      healthy: redis?.connected === true,
      last_error: redis?.error || null
    }
  } catch (error) {
    console.error('Failed to fetch Redis status:', error)
    redisStatus.value = { healthy: false, last_error: 'Failed to fetch status' }
  }
}

async function fetchSSLCertStatus() {
  try {
    const response = await api.get('/api/v1/monitor/ssl/current')
    // Go /monitor/ssl/current returns {most_urgent: {status, days_remaining, ...}, certificates: [...]}
    const cert = response.data?.most_urgent || response.data
    if (cert && cert.is_valid !== undefined) {
      sslCertStatus.value = {
        status: cert.status || 'unknown',
        days_remaining: cert.days_remaining || 0
      }
    }
  } catch (error) {
    console.error('Failed to fetch SSL cert status:', error)
    sslCertStatus.value = { status: 'error', days_remaining: 0 }
  }
}

async function fetchProxyHealthStatus() {
  try {
    // Trailing slash required — nginx 301 redirects /proxies → /proxies/ and drops Authorization header
    const response = await api.get('/api/v1/proxies/')
    const proxies = Array.isArray(response.data) ? response.data : []

    const total = proxies.length
    const active = proxies.filter(p => p.status === 'active').length
    const failed = proxies.filter(p => p.status === 'failed').length

    // Average health score — default to 100 when no proxies (direct-connect = healthy)
    let avgHealth = 100
    if (total > 0) {
      const totalHealth = proxies.reduce((sum, p) => sum + (p.health_score || 0), 0)
      avgHealth = Math.round(totalHealth / total)
    }

    proxyHealthStatus.value = { total, active, failed, avgHealth }
  } catch (error) {
    console.error('Failed to fetch proxy health status:', error)
    // No proxies configured or fetch failed — assume direct-connect (healthy)
    proxyHealthStatus.value = { total: 0, active: 0, failed: 0, avgHealth: 100 }
  }
}

// Fetch USD/USDT exchange rate from Binance API
async function fetchExchangeRate() {
  try {
    // Use Binance public API to get USDT price relative to USD
    // We use USDC/USDT as a proxy since USDC ≈ USD
    const response = await api.get('/api/v1/market/exchange-rate')
    const data = response.data || {}

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

async function fetchBybitSwapRate() {
  try {
    const response = await api.get('/api/v1/market/bybit-swap-rate', {
      params: { pair_code: currentPair.value }
    })
    const data = response.data
    // long_swap_per_lot: <0 long pays, >0 long receives
    // short_swap_per_lot: >0 short receives, <0 short pays
    bybitLongSwapFee.value = data.long_swap_per_lot ?? 0
    bybitShortSwapFee.value = data.short_swap_per_lot ?? 0
  } catch (error) {
    console.error('Failed to fetch Bybit swap rate:', error)
  }
}

async function fetchBinanceFundingRate() {
  try {
    const response = await api.get('/api/v1/market/funding-rate', {
      params: { pair_code: currentPair.value }
    })
    const data = response.data
    // long_cost_per_lot: >0 means long pays, <0 means long receives
    // short_cost_per_lot: opposite sign
    binanceLongFundingRate.value = data.long_cost_per_lot ?? 0
    binanceShortFundingRate.value = data.short_cost_per_lot ?? 0
    binanceFundingRatePct.value = data.funding_rate_pct ?? 0
    binanceNextFundingTime.value = data.next_funding_time ?? 0
  } catch (error) {
    console.error('Failed to fetch Binance funding rate:', error)
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
  binanceShortFundingRate,
  binanceFundingRatePct,
  binanceNextFundingTime,
  binanceLongTotal,
  binanceShortTotal,
  bybitLongTotal,
  bybitShortTotal
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
  width: 100%;
}

.marquee-content {
  display: inline-block;
  white-space: nowrap;
  animation: marquee 20s linear infinite;
  will-change: transform;
  -webkit-transform: translateZ(0);
  transform: translateZ(0);
}

.marquee-content:hover {
  animation-play-state: paused;
}

@keyframes marquee {
  0% {
    transform: translateX(100vw);
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
