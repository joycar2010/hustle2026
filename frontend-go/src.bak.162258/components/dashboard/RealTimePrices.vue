<template>
  <div class="card-elevated">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xl font-bold">Real-Time Prices</h2>
      <div class="flex items-center space-x-2">
        <div :class="['w-2 h-2 rounded-full', isConnected ? 'bg-success animate-pulse' : 'bg-danger']"></div>
        <span class="text-xs text-text-tertiary">{{ isConnected ? 'Live' : 'Disconnected' }}</span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <!-- Binance Prices -->
      <div class="bg-dark-300 rounded-lg p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center space-x-2">
            <div class="w-8 h-8 bg-primary rounded-full flex items-center justify-center">
              <span class="text-dark-300 font-bold text-sm">B</span>
            </div>
            <span class="font-semibold">Binance</span>
          </div>
          <span class="text-xs text-text-tertiary">XAUUSDT</span>
        </div>

        <div class="space-y-2">
          <div class="flex justify-between items-center">
            <span class="text-text-secondary text-sm">Bid</span>
            <div class="text-right">
              <div :class="['text-lg font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
                {{ formatPrice(binance.bid) }} USDT
              </div>
              <div class="text-xs text-text-tertiary">
                {{ formatChange(binance.bid, binance.prevBid) }}
              </div>
            </div>
          </div>

          <div class="flex justify-between items-center">
            <span class="text-text-secondary text-sm">Ask</span>
            <div class="text-right">
              <div :class="['text-lg font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
                {{ formatPrice(binance.ask) }} USDT
              </div>
              <div class="text-xs text-text-tertiary">
                {{ formatChange(binance.ask, binance.prevAsk) }}
              </div>
            </div>
          </div>

          <div class="pt-2 border-t border-border-secondary">
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary text-xs">Spread</span>
              <span class="text-sm font-mono">{{ formatPrice(binance.ask - binance.bid) }} USDT</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Bybit Prices -->
      <div class="bg-dark-300 rounded-lg p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center space-x-2">
            <div class="w-8 h-8 bg-warning rounded-full flex items-center justify-center">
              <span class="text-white font-bold text-sm">B</span>
            </div>
            <span class="font-semibold">Bybit</span>
          </div>
          <span class="text-xs text-text-tertiary">XAUUSDT</span>
        </div>

        <div class="space-y-2">
          <div class="flex justify-between items-center">
            <span class="text-text-secondary text-sm">Bid</span>
            <div class="text-right">
              <div :class="['text-lg font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
                {{ formatPrice(bybit.bid) }} USDT
              </div>
              <div class="text-xs text-text-tertiary">
                {{ formatChange(bybit.bid, bybit.prevBid) }}
              </div>
            </div>
          </div>

          <div class="flex justify-between items-center">
            <span class="text-text-secondary text-sm">Ask</span>
            <div class="text-right">
              <div :class="['text-lg font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
                {{ formatPrice(bybit.ask) }} USDT
              </div>
              <div class="text-xs text-text-tertiary">
                {{ formatChange(bybit.ask, bybit.prevAsk) }}
              </div>
            </div>
          </div>

          <div class="pt-2 border-t border-border-secondary">
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary text-xs">Spread</span>
              <span class="text-sm font-mono">{{ formatPrice(bybit.ask - bybit.bid) }} USDT</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Arbitrage Opportunity -->
    <div v-if="arbitrageOpportunity" class="mt-4 bg-primary/10 border border-primary rounded-lg p-4">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm text-text-secondary mb-1">Arbitrage Spread</div>
          <div class="text-2xl font-bold font-mono text-primary">
            {{ formatPrice(arbitrageOpportunity.spread) }} USDT
          </div>
          <div class="text-xs text-text-tertiary mt-1">
            {{ arbitrageOpportunity.direction === 'forward' ? 'Buy Binance → Sell Bybit' : 'Buy Bybit → Sell Binance' }}
          </div>
        </div>
        <div class="text-right">
          <div class="text-sm text-text-secondary mb-1">Profit Potential</div>
          <div class="text-xl font-bold text-success">
            {{ arbitrageOpportunity.profitPercent }}%
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import { calculateAllSpreads, calculateBidAskSpread } from '@/composables/useSpreadCalculator'

const marketStore = useMarketStore()
const isConnected = computed(() => marketStore.connected)

const binance = ref({ bid: 0, ask: 0, prevBid: 0, prevAsk: 0 })
const bybit = ref({ bid: 0, ask: 0, prevBid: 0, prevAsk: 0 })

const arbitrageOpportunity = computed(() => {
  // 使用统一的点差计算管理组件
  const spreads = calculateAllSpreads({
    binance_bid: binance.value.bid,
    binance_ask: binance.value.ask,
    bybit_bid: bybit.value.bid,
    bybit_ask: bybit.value.ask
  })

  // 正向开仓：binance做多点差 = bybit_bid - binance_bid
  if (spreads.forwardOpening > 0.5) {
    return {
      spread: spreads.forwardOpening,
      direction: 'forward',
      profitPercent: ((spreads.forwardOpening / binance.value.ask) * 100).toFixed(3)
    }
  }
  // 反向开仓：bybit做多点差 = binance_ask - bybit_ask
  else if (spreads.reverseOpening > 0.5) {
    return {
      spread: spreads.reverseOpening,
      direction: 'reverse',
      profitPercent: ((spreads.reverseOpening / bybit.value.ask) * 100).toFixed(3)
    }
  }
  return null
})

watch(() => marketStore.marketData, (data) => {
  if (!data) return

  binance.value.prevBid = binance.value.bid
  binance.value.prevAsk = binance.value.ask
  bybit.value.prevBid = bybit.value.bid
  bybit.value.prevAsk = bybit.value.ask

  binance.value.bid = data.binance_bid || 0
  binance.value.ask = data.binance_ask || 0
  bybit.value.bid = data.bybit_bid || 0
  bybit.value.ask = data.bybit_ask || 0
})

onMounted(() => {
  marketStore.connect()
})

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function formatChange(current, previous) {
  if (!previous || current === previous) return ''
  const change = current - previous
  const sign = change > 0 ? '+' : ''
  return `${sign}${change.toFixed(2)}`
}

function getPriceClass(current, previous) {
  if (!previous || current === previous) return 'price-neutral'
  return current > previous ? 'price-up' : 'price-down'
}
</script>
