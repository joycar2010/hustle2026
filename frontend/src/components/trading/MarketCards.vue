<template>
  <div class="h-full flex flex-col">
    <div class="p-3 border-b border-[#2b3139]">
      <h3 class="text-sm font-bold">实时行情</h3>
    </div>

    <div class="flex-1 overflow-y-auto p-3 space-y-3">
      <!-- Bybit MT5 Card -->
      <div class="bg-[#252930] rounded p-3">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <div class="w-6 h-6 bg-[#ff9800] rounded flex items-center justify-center">
              <span class="text-white font-bold text-xs">B</span>
            </div>
            <div>
              <div class="font-medium text-sm">Bybit MT5</div>
              <div class="text-xs text-gray-400">XAUUSD.s</div>
            </div>
          </div>
          <div :class="['w-2 h-2 rounded-full', bybitConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Large) -->
        <div class="mb-3 text-center py-2 bg-[#1e2329] rounded">
          <div class="text-xs text-gray-400 mb-1">实时价格</div>
          <div :class="['text-3xl font-mono font-bold', getPriceClass(bybit.mid, bybit.prevMid)]">
            {{ formatPrice(bybit.mid) }} USDT
          </div>
        </div>

        <!-- ASK and BID -->
        <div class="space-y-2 mb-3">
          <div class="flex justify-between items-center">
            <span class="text-xs text-gray-400">ASK (卖价)</span>
            <div :class="['text-base font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }} USDT
            </div>
          </div>

          <div class="flex justify-between items-center">
            <span class="text-xs text-gray-400">BID (买价)</span>
            <div :class="['text-base font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }} USDT
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-2 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-xs text-gray-400">卡顿心跳线</span>
          <div class="flex items-center space-x-2">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 h-3 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-xs font-mono">{{ bybitLagCount }}次</span>
          </div>
        </div>
      </div>

      <!-- Binance Card -->
      <div class="bg-[#252930] rounded p-3">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <div class="w-6 h-6 bg-[#f0b90b] rounded flex items-center justify-center">
              <span class="text-[#1a1d21] font-bold text-xs">B</span>
            </div>
            <div>
              <div class="font-medium text-sm">Binance</div>
              <div class="text-xs text-gray-400">XAUUSDT</div>
            </div>
          </div>
          <div :class="['w-2 h-2 rounded-full', binanceConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Large) -->
        <div class="mb-3 text-center py-2 bg-[#1e2329] rounded">
          <div class="text-xs text-gray-400 mb-1">实时价格</div>
          <div :class="['text-3xl font-mono font-bold', getPriceClass(binance.mid, binance.prevMid)]">
            {{ formatPrice(binance.mid) }} USDT
          </div>
        </div>

        <!-- ASK and BID -->
        <div class="space-y-2 mb-3">
          <div class="flex justify-between items-center">
            <span class="text-xs text-gray-400">ASK (卖价)</span>
            <div :class="['text-base font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }} USDT
            </div>
          </div>

          <div class="flex justify-between items-center">
            <span class="text-xs text-gray-400">BID (买价)</span>
            <div :class="['text-base font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }} USDT
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-2 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-xs text-gray-400">卡顿心跳线</span>
          <div class="flex items-center space-x-2">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 h-3 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-xs font-mono">{{ binanceLagCount }}次</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({
  bid: 0,
  ask: 0,
  mid: 0,
  prevBid: 0,
  prevAsk: 0,
  prevMid: 0,
})

const binance = ref({
  bid: 0,
  ask: 0,
  mid: 0,
  prevBid: 0,
  prevAsk: 0,
  prevMid: 0,
})

const bybitLagCount = ref(0)
const binanceLagCount = ref(0)
const lastUpdateTime = ref(Date.now())

const bybitLagLevel = computed(() => Math.min(Math.floor(bybitLagCount.value / 10), 5))
const binanceLagLevel = computed(() => Math.min(Math.floor(binanceLagCount.value / 10), 5))

let updateInterval = null

onMounted(() => {
  fetchPrices()
  updateInterval = setInterval(fetchPrices, 1000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchPrices() {
  try {
    const data = await marketStore.fetchMarketData()

    if (data) {
      const now = Date.now()
      const timeSinceLastUpdate = now - lastUpdateTime.value

      // Check for lag (if update takes more than 2 seconds)
      if (timeSinceLastUpdate > 2000) {
        bybitLagCount.value++
        binanceLagCount.value++
      }
      lastUpdateTime.value = now

      // Store previous values
      bybit.value.prevBid = bybit.value.bid
      bybit.value.prevAsk = bybit.value.ask
      bybit.value.prevMid = bybit.value.mid
      binance.value.prevBid = binance.value.bid
      binance.value.prevAsk = binance.value.ask
      binance.value.prevMid = binance.value.mid

      // Update Bybit values
      bybit.value.bid = data.bybit_bid || 0
      bybit.value.ask = data.bybit_ask || 0
      bybit.value.mid = data.bybit_mid || ((bybit.value.bid + bybit.value.ask) / 2)

      // Update Binance values
      binance.value.bid = data.binance_bid || 0
      binance.value.ask = data.binance_ask || 0
      binance.value.mid = data.binance_mid || ((binance.value.bid + binance.value.ask) / 2)

      bybitConnected.value = true
      binanceConnected.value = true
    }
  } catch (error) {
    console.error('Failed to fetch prices:', error)
    bybitConnected.value = false
    binanceConnected.value = false
    bybitLagCount.value++
    binanceLagCount.value++
  }
}

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function getPriceClass(current, previous) {
  if (!previous || current === previous) return 'text-white'
  return current > previous ? 'text-[#0ecb81]' : 'text-[#f6465d]'
}
</script>
