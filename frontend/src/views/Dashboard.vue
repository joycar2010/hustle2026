<template>
  <div class="min-h-screen bg-dark-300">
    <!-- Page Header -->
    <div class="bg-dark-200 border-b border-border-primary">
      <div class="container mx-auto px-4 py-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-3xl font-bold mb-2">Dashboard</h1>
            <p class="text-text-secondary">Real-time arbitrage monitoring and analytics</p>
          </div>
          <div class="flex items-center space-x-4">
            <div class="text-right">
              <div class="text-sm text-text-tertiary">Last Updated</div>
              <div class="text-sm font-medium">{{ lastUpdated }}</div>
            </div>
            <button
              @click="refreshAll"
              class="btn-secondary"
              :disabled="refreshing"
            >
              <svg
                class="w-5 h-5"
                :class="{ 'animate-spin': refreshing }"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="container mx-auto px-4 py-6">
      <div class="space-y-6">
        <!-- Asset Dashboard -->
        <AssetDashboard />

        <!-- Profit/Loss Curve Chart (Double Height) -->
        <div class="card-elevated" style="height: 630px;">
          <SpreadChart />
        </div>

        <!-- Real-Time Market Data and Spread (Single Row) -->
        <div class="grid grid-cols-3 gap-4">
          <!-- Bybit MT5 Real-Time Market (Green) -->
          <div class="card-elevated">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-bold">Bybit MT5 实时行情</h3>
              <div class="flex items-center space-x-2">
                <div class="w-2 h-2 rounded-full bg-success animate-pulse"></div>
                <span class="text-xs text-text-tertiary">Live</span>
              </div>
            </div>
            <div class="bg-dark-300 rounded-lg p-4">
              <div class="space-y-3">
                <div class="flex justify-between items-center">
                  <span class="text-text-secondary text-sm">Bid</span>
                  <div class="text-xl font-mono font-bold text-success">
                    {{ formatPrice(bybitPrice.bid) }} USDT
                  </div>
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-text-secondary text-sm">Ask</span>
                  <div class="text-xl font-mono font-bold text-success">
                    {{ formatPrice(bybitPrice.ask) }} USDT
                  </div>
                </div>
                <div class="pt-2 border-t border-border-secondary">
                  <div class="flex justify-between items-center">
                    <span class="text-text-tertiary text-xs">Spread</span>
                    <span class="text-sm font-mono text-success">{{ formatPrice(bybitPrice.ask - bybitPrice.bid) }} USDT</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Spread Data Stream (Middle) -->
          <div class="card-elevated">
            <h3 class="text-lg font-bold mb-4">点差数据流</h3>
            <div class="space-y-3">
              <div class="bg-dark-300 rounded-lg p-3">
                <div class="text-xs text-text-tertiary mb-1">正向套利点差 (做多Binance)</div>
                <div class="text-2xl font-mono font-bold text-danger">
                  {{ formatPrice(forwardSpread) }} USDT
                </div>
              </div>
              <div class="bg-dark-300 rounded-lg p-3">
                <div class="text-xs text-text-tertiary mb-1">反向套利点差 (做多Bybit)</div>
                <div class="text-2xl font-mono font-bold text-success">
                  {{ formatPrice(reverseSpread) }} USDT
                </div>
              </div>
            </div>
          </div>

          <!-- Binance Real-Time Market (Red) -->
          <div class="card-elevated">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-bold">Binance 实时行情</h3>
              <div class="flex items-center space-x-2">
                <div class="w-2 h-2 rounded-full bg-danger animate-pulse"></div>
                <span class="text-xs text-text-tertiary">Live</span>
              </div>
            </div>
            <div class="bg-dark-300 rounded-lg p-4">
              <div class="space-y-3">
                <div class="flex justify-between items-center">
                  <span class="text-text-secondary text-sm">Bid</span>
                  <div class="text-xl font-mono font-bold text-danger">
                    {{ formatPrice(binancePrice.bid) }} USDT
                  </div>
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-text-secondary text-sm">Ask</span>
                  <div class="text-xl font-mono font-bold text-danger">
                    {{ formatPrice(binancePrice.ask) }} USDT
                  </div>
                </div>
                <div class="pt-2 border-t border-border-secondary">
                  <div class="flex justify-between items-center">
                    <span class="text-text-tertiary text-xs">Spread</span>
                    <span class="text-sm font-mono text-danger">{{ formatPrice(binancePrice.ask - binancePrice.bid) }} USDT</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Historical Spread Data -->
        <SpreadHistory />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import dayjs from 'dayjs'
import AssetDashboard from '@/components/dashboard/AssetDashboard.vue'
import SpreadChart from '@/components/trading/SpreadChart.vue'
import SpreadHistory from '@/components/dashboard/SpreadHistory.vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
const lastUpdated = ref('')
const refreshing = ref(false)

const binancePrice = ref({
  bid: 0,
  ask: 0
})

const bybitPrice = ref({
  bid: 0,
  ask: 0
})

const forwardSpread = computed(() => {
  return bybitPrice.value.bid - binancePrice.value.ask
})

const reverseSpread = computed(() => {
  return binancePrice.value.bid - bybitPrice.value.ask
})

let updateInterval = null

onMounted(() => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Update timestamp every second
  updateLastUpdated()
  updateInterval = setInterval(updateLastUpdated, 1000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

// Watch for WebSocket market data updates
watch(() => marketStore.marketData, (newData) => {
  if (newData) {
    binancePrice.value.bid = newData.binance_bid || 0
    binancePrice.value.ask = newData.binance_ask || 0
    bybitPrice.value.bid = newData.bybit_bid || 0
    bybitPrice.value.ask = newData.bybit_ask || 0
    updateLastUpdated()
  }
})

function updateLastUpdated() {
  lastUpdated.value = dayjs().format('HH:mm:ss')
}

async function fetchPrices() {
  try {
    const data = await marketStore.fetchMarketData()
    if (data) {
      binancePrice.value.bid = data.binance_bid || 0
      binancePrice.value.ask = data.binance_ask || 0
      bybitPrice.value.bid = data.bybit_bid || 0
      bybitPrice.value.ask = data.bybit_ask || 0
    }
  } catch (error) {
    console.error('Failed to fetch prices:', error)
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await fetchPrices()
    await new Promise(resolve => setTimeout(resolve, 1000))
  } finally {
    refreshing.value = false
  }
}

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}
</script>