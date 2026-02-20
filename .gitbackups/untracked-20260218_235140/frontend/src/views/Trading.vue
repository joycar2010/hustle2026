<template>
  <div class="container mx-auto px-4 py-6">
    <!-- Market Header -->
    <div class="card mb-4">
      <div class="flex flex-col md:flex-row md:items-center md:justify-between space-y-4 md:space-y-0">
        <div class="flex items-center space-x-4">
          <h1 class="text-2xl font-bold">XAU/USD</h1>
          <span class="text-sm text-gray-400">Gold Spot</span>
        </div>

        <div v-if="marketData" class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div class="text-xs text-gray-400">Binance</div>
            <div class="text-lg font-bold">{{ formatPrice(marketData.binance_bid) }}</div>
          </div>
          <div>
            <div class="text-xs text-gray-400">Bybit</div>
            <div class="text-lg font-bold">{{ formatPrice(marketData.bybit_ask) }}</div>
          </div>
          <div>
            <div class="text-xs text-gray-400">Spread</div>
            <div class="text-lg font-bold" :class="spreadColor">
              {{ formatPrice(marketData.spread) }}
            </div>
          </div>
          <div>
            <div class="text-xs text-gray-400">Direction</div>
            <div class="text-lg font-bold capitalize">{{ marketData.direction }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Main Trading Layout -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <!-- Order Book (Left) -->
      <div class="lg:col-span-3">
        <OrderBook />
      </div>

      <!-- Chart & Trading Form (Center) -->
      <div class="lg:col-span-6 space-y-4">
        <!-- Chart -->
        <div class="card h-96">
          <TradingChart />
        </div>

        <!-- Trading Form -->
        <div class="card">
          <TradingForm />
        </div>
      </div>

      <!-- Recent Trades (Right) -->
      <div class="lg:col-span-3">
        <RecentTrades />
      </div>
    </div>

    <!-- Open Orders -->
    <div class="mt-4">
      <OpenOrders />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import OrderBook from '@/components/trading/OrderBook.vue'
import TradingChart from '@/components/trading/TradingChart.vue'
import TradingForm from '@/components/trading/TradingForm.vue'
import RecentTrades from '@/components/trading/RecentTrades.vue'
import OpenOrders from '@/components/trading/OpenOrders.vue'

const marketStore = useMarketStore()
const marketData = computed(() => marketStore.marketData)

const spreadColor = computed(() => {
  if (!marketData.value) return ''
  return marketData.value.spread > 0 ? 'text-green-500' : 'text-red-500'
})

let interval

onMounted(() => {
  marketStore.fetchMarketData()
  interval = setInterval(() => {
    marketStore.fetchMarketData()
  }, 1000)
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}
</script>
