<template>
  <div class="h-full flex flex-col">
    <!-- Total Profit and Strategy Positions Header -->
    <div class="p-3 bg-[#252930] border-b border-[#2b3139]">
      <div class="text-xs text-gray-400 mb-1">当前用户总盈利</div>
      <div class="text-xl font-bold font-mono mb-3" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
        {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }} USDT
      </div>

      <!-- Arbitrage Strategy Position Data -->
      <div class="grid grid-cols-2 gap-2">
        <!-- Forward Arbitrage -->
        <div class="bg-[#1e2329] rounded p-2">
          <div class="text-xs text-gray-400 mb-1">正向套利策略</div>
          <div class="flex justify-between text-xs">
            <span class="text-gray-400">开仓持仓:</span>
            <span class="font-mono text-white">{{ forwardOpenPosition }}</span>
          </div>
          <div class="flex justify-between text-xs mt-1">
            <span class="text-gray-400">平仓持仓:</span>
            <span class="font-mono text-white">{{ forwardClosePosition }}</span>
          </div>
        </div>

        <!-- Reverse Arbitrage -->
        <div class="bg-[#1e2329] rounded p-2">
          <div class="text-xs text-gray-400 mb-1">反向套利策略</div>
          <div class="flex justify-between text-xs">
            <span class="text-gray-400">开仓持仓:</span>
            <span class="font-mono text-white">{{ reverseOpenPosition }}</span>
          </div>
          <div class="flex justify-between text-xs mt-1">
            <span class="text-gray-400">平仓持仓:</span>
            <span class="font-mono text-white">{{ reverseClosePosition }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-3">
      <div class="grid grid-cols-1 gap-3 h-full">
      <!-- Bybit MT5 Card -->
      <div class="bg-[#252930] rounded p-3 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <div class="w-7 h-7 bg-[#ff9800] rounded flex items-center justify-center">
              <span class="text-white font-bold text-lg">B</span>
            </div>
            <div>
              <div class="font-medium text-lg">Bybit MT5 <span class="text-sm text-gray-400">XAUUSD.s</span></div>
            </div>
          </div>
          <div :class="['w-3 h-3 rounded-full', bybitConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Compact) -->
        <div class="mb-2 text-center py-1.5 bg-[#1e2329] rounded">
          <div class="text-sm text-gray-400 mb-0.5">实时价格</div>
          <div :class="['text-2xl font-mono font-bold', getPriceClass(bybit.mid, bybit.prevMid)]">
            {{ formatPrice(bybit.mid) }}
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-2 mb-2">
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">ASK</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">BID</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-sm text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 h-3 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-sm font-mono">{{ bybitLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Binance Card -->
      <div class="bg-[#252930] rounded p-3 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <div class="w-7 h-7 bg-[#f0b90b] rounded flex items-center justify-center">
              <span class="text-[#1a1d21] font-bold text-lg">B</span>
            </div>
            <div>
              <div class="font-medium text-lg">Binance <span class="text-sm text-gray-400">XAUUSDT</span></div>
            </div>
          </div>
          <div :class="['w-3 h-3 rounded-full', binanceConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Compact) -->
        <div class="mb-2 text-center py-1.5 bg-[#1e2329] rounded">
          <div class="text-sm text-gray-400 mb-0.5">实时价格</div>
          <div :class="['text-2xl font-mono font-bold', getPriceClass(binance.mid, binance.prevMid)]">
            {{ formatPrice(binance.mid) }}
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-2 mb-2">
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">ASK</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">BID</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-sm text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 h-3 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-sm font-mono">{{ binanceLagCount }}</span>
          </div>
        </div>
      </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

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
const forwardOpenPosition = ref(0)
const forwardClosePosition = ref(0)
const reverseOpenPosition = ref(0)
const reverseClosePosition = ref(0)

let updateInterval = null

const bybitLagLevel = computed(() => Math.min(Math.floor(bybitLagCount.value / 10), 5))
const binanceLagLevel = computed(() => Math.min(Math.floor(binanceLagCount.value / 10), 5))

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
  binance.value.prevMid = binance.value.mid

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

onMounted(() => {
  marketStore.connect()
  lagTimer = setInterval(() => {
    if (Date.now() - lastUpdateTime > 2000) {
      bybitLagCount.value++
      binanceLagCount.value++
    }
  }, 2000)

  // Fetch profit and position data
  fetchAccountData()
  fetchStrategyPositions()
  // Update every 60 seconds
  updateInterval = setInterval(() => {
    fetchAccountData()
    fetchStrategyPositions()
  }, 60000)
})

onUnmounted(() => {
  if (lagTimer) clearInterval(lagTimer)
  if (updateInterval) clearInterval(updateInterval)
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

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data
    if (data.summary) {
      totalProfit.value = data.summary.daily_pnl || 0
    }
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

async function fetchStrategyPositions() {
  try {
    const configsResponse = await api.get('/api/v1/strategies/configs')
    const configs = configsResponse.data

    forwardOpenPosition.value = 0
    forwardClosePosition.value = 0
    reverseOpenPosition.value = 0
    reverseClosePosition.value = 0

    for (const config of configs) {
      try {
        const positionsResponse = await api.get(`/api/v1/strategies/positions/${config.config_id}`)
        const data = positionsResponse.data

        if (data.summary) {
          const isForward = config.strategy_type === 'forward_arbitrage'
          const isReverse = config.strategy_type === 'reverse_arbitrage'

          const openingPositions = data.positions.filter(p => p.strategy_type === 'opening')
          const closingPositions = data.positions.filter(p => p.strategy_type === 'closing')

          const totalOpening = openingPositions.reduce((sum, p) => sum + (p.current_position || 0), 0)
          const totalClosing = closingPositions.reduce((sum, p) => sum + (p.current_position || 0), 0)

          if (isForward) {
            forwardOpenPosition.value += totalOpening
            forwardClosePosition.value += totalClosing
          } else if (isReverse) {
            reverseOpenPosition.value += totalOpening
            reverseClosePosition.value += totalClosing
          }
        }
      } catch (error) {
        console.error(`Failed to fetch positions for strategy ${config.config_id}:`, error)
      }
    }
  } catch (error) {
    console.error('Failed to fetch strategy positions:', error)
  }
}
</script>
