<template>
  <div class="h-full flex flex-col">
    <div class="p-2 border-b border-[#2b3139]">
      <h3 class="text-xs font-bold text-center">实时行情</h3>
    </div>

    <div class="flex-1 overflow-hidden p-2 space-y-2">
      <!-- Bybit MT5 Card -->
      <div class="bg-[#252930] rounded p-2">
        <div class="flex items-center justify-between mb-1.5">
          <div class="flex items-center space-x-1.5">
            <div class="w-5 h-5 bg-[#ff9800] rounded flex items-center justify-center">
              <span class="text-white font-bold text-xs">B</span>
            </div>
            <div>
              <div class="font-medium text-xs">Bybit MT5</div>
              <div class="text-[10px] text-gray-400">XAUUSD.s</div>
            </div>
          </div>
          <div :class="['w-1.5 h-1.5 rounded-full', bybitConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Large) -->
        <div class="mb-2 text-center py-1.5 bg-[#1e2329] rounded">
          <div class="text-[10px] text-gray-400 mb-0.5">实时价格</div>
          <div :class="['text-xl font-mono font-bold', getPriceClass(bybit.mid, bybit.prevMid)]">
            {{ formatPrice(bybit.mid) }}
          </div>
        </div>

        <!-- ASK and BID -->
        <div class="space-y-1 mb-2">
          <div class="flex justify-between items-center">
            <span class="text-[10px] text-gray-400">ASK</span>
            <div :class="['text-xs font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }}
            </div>
          </div>

          <div class="flex justify-between items-center">
            <span class="text-[10px] text-gray-400">BID</span>
            <div :class="['text-xs font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-[10px] text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-0.5 h-2 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-[10px] font-mono">{{ bybitLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Binance Card -->
      <div class="bg-[#252930] rounded p-2">
        <div class="flex items-center justify-between mb-1.5">
          <div class="flex items-center space-x-1.5">
            <div class="w-5 h-5 bg-[#f0b90b] rounded flex items-center justify-center">
              <span class="text-[#1a1d21] font-bold text-xs">B</span>
            </div>
            <div>
              <div class="font-medium text-xs">Binance</div>
              <div class="text-[10px] text-gray-400">XAUUSDT</div>
            </div>
          </div>
          <div :class="['w-1.5 h-1.5 rounded-full', binanceConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Large) -->
        <div class="mb-2 text-center py-1.5 bg-[#1e2329] rounded">
          <div class="text-[10px] text-gray-400 mb-0.5">实时价格</div>
          <div :class="['text-xl font-mono font-bold', getPriceClass(binance.mid, binance.prevMid)]">
            {{ formatPrice(binance.mid) }}
          </div>
        </div>

        <!-- ASK and BID -->
        <div class="space-y-1 mb-2">
          <div class="flex justify-between items-center">
            <span class="text-[10px] text-gray-400">ASK</span>
            <div :class="['text-xs font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }}
            </div>
          </div>

          <div class="flex justify-between items-center">
            <span class="text-[10px] text-gray-400">BID</span>
            <div :class="['text-xs font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-[10px] text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-0.5 h-2 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-[10px] font-mono">{{ binanceLagCount }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })
const binance = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })

const bybitLagCount = ref(0)
const binanceLagCount = ref(0)
let lastUpdateTime = Date.now()
let lagTimer = null

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
</script>
