<template>
  <div class="px-2 py-2">
    <div class="flex items-center justify-between mb-2">
      <h1 class="text-sm font-bold">K线查询</h1>
    </div>

    <!-- Search + Period selector -->
    <div class="card mb-2">
      <div class="flex flex-wrap items-center gap-2">
        <!-- Coin search -->
        <div class="relative" ref="searchWrapRef">
          <input
            v-model="query"
            @input="onSearch"
            @focus="showDropdown = results.length > 0"
            placeholder="搜索币种 (如 BTC, XAU, ETH)"
            class="w-56 px-3 py-1.5 text-xs bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary text-text-primary placeholder-text-tertiary"
          />
          <!-- Dropdown -->
          <div
            v-if="showDropdown && results.length > 0"
            class="absolute z-50 mt-1 w-80 max-h-64 overflow-y-auto bg-dark-100 border border-border-primary rounded-lg shadow-lg"
          >
            <div
              v-for="coin in results"
              :key="coin.coinKey"
              @click="selectCoin(coin)"
              class="px-3 py-2 hover:bg-dark-50 cursor-pointer flex items-center justify-between text-xs"
            >
              <div class="flex items-center gap-2">
                <img v-if="coin.logo" :src="coin.logo" class="w-5 h-5 rounded-full" />
                <div v-else class="w-5 h-5 rounded-full bg-dark-200 flex items-center justify-center text-[10px] text-text-tertiary">{{ (coin.coinShow || '?')[0] }}</div>
                <span class="font-medium text-text-primary">{{ coin.coinShow }}</span>
                <span class="text-text-tertiary">{{ coin.coinName }}</span>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-text-secondary">${{ coin.price }}</span>
                <span :class="parseFloat(coin.degree24H) >= 0 ? 'text-success' : 'text-danger'">
                  {{ parseFloat(coin.degree24H) >= 0 ? '+' : '' }}{{ coin.degree24H }}%
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Selected label -->
        <span v-if="selectedLabel" class="text-xs text-primary font-medium">{{ selectedLabel }}</span>

        <!-- Period buttons -->
        <div class="flex gap-1 ml-auto">
          <button
            v-for="p in PERIODS"
            :key="p.value"
            @click="period = p.value"
            :class="[
              'px-2 py-1 text-xs rounded transition-colors',
              period === p.value
                ? 'bg-primary text-dark-300 font-semibold'
                : 'bg-dark-200 text-text-secondary hover:text-text-primary hover:bg-dark-50'
            ]"
          >{{ p.label }}</button>
        </div>
      </div>
    </div>

    <!-- OHLC display -->
    <div v-if="ohlc" class="card mb-2">
      <div class="flex items-center gap-4 text-xs">
        <span class="text-text-tertiary">O <span class="text-text-primary font-mono">{{ ohlc.o }}</span></span>
        <span class="text-text-tertiary">H <span class="text-success font-mono">{{ ohlc.h }}</span></span>
        <span class="text-text-tertiary">L <span class="text-danger font-mono">{{ ohlc.l }}</span></span>
        <span class="text-text-tertiary">C <span class="text-text-primary font-mono">{{ ohlc.c }}</span></span>
        <span :class="ohlc.change >= 0 ? 'text-success' : 'text-danger'" class="font-mono">
          {{ ohlc.change >= 0 ? '+' : '' }}{{ ohlc.change.toFixed(2) }}%
        </span>
      </div>
    </div>

    <!-- Chart -->
    <div class="card">
      <div ref="chartContainerRef" class="w-full" style="height: 500px;"></div>
      <div v-if="loading" class="absolute inset-0 flex items-center justify-center text-text-tertiary text-sm">加载中...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries } from 'lightweight-charts'
import api from '@/services/api'

const PERIODS = [
  { label: '1分', value: '1' },
  { label: '5分', value: '5' },
  { label: '15分', value: '15' },
  { label: '30分', value: '30' },
  { label: '1时', value: '60' },
  { label: '4时', value: '240' },
  { label: '1天', value: '1440' },
]

const query = ref('')
const results = ref([])
const showDropdown = ref(false)
const selectedSymbol = ref('btcswapusdt:binance')
const selectedLabel = ref('BTC/USDT (Binance)')
const period = ref('60')
const loading = ref(false)
const ohlc = ref(null)

const chartContainerRef = ref(null)
const searchWrapRef = ref(null)

let chart = null
let candleSeries = null
let volumeSeries = null
let searchTimer = null
let resizeObserver = null

function onSearch() {
  clearTimeout(searchTimer)
  const q = query.value.trim()
  if (!q) {
    results.value = []
    showDropdown.value = false
    return
  }
  searchTimer = setTimeout(async () => {
    try {
      const { data } = await api.get('/api/v1/aicoin/coin-search', { params: { q } })
      results.value = Array.isArray(data) ? data : []
      showDropdown.value = results.value.length > 0
    } catch {
      results.value = []
    }
  }, 300)
}

function selectCoin(coin) {
  const dbKeys = (coin.dbKeys || '').split(',')[0].trim()
  if (!dbKeys) return
  selectedSymbol.value = dbKeys
  const exchange = dbKeys.includes(':') ? dbKeys.split(':')[1] : ''
  const exchangeMap = { binance: 'Binance', okex: 'OKX', gate: 'Gate', bybit: 'Bybit', bitget: 'Bitget' }
  const exLabel = exchangeMap[exchange] || exchange
  selectedLabel.value = coin.coinShow + '/USDT (' + exLabel + ')'
  query.value = coin.coinShow
  showDropdown.value = false
  loadKline()
}

function initChart() {
  if (!chartContainerRef.value || chart) return
  chart = createChart(chartContainerRef.value, {
    layout: { background: { color: '#181A20' }, textColor: '#848E9C' },
    grid: { vertLines: { color: '#2B3139' }, horzLines: { color: '#2B3139' } },
    crosshair: { mode: 0 },
    rightPriceScale: { borderColor: '#2B3139' },
    timeScale: { borderColor: '#2B3139', timeVisible: true, secondsVisible: false },
  })
  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#0ECB81',
    downColor: '#F6465D',
    borderUpColor: '#0ECB81',
    borderDownColor: '#F6465D',
    wickUpColor: '#0ECB81',
    wickDownColor: '#F6465D',
  })
  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'vol',
  })
  chart.priceScale('vol').applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  })

  resizeObserver = new ResizeObserver(() => {
    if (chart && chartContainerRef.value) {
      chart.applyOptions({ width: chartContainerRef.value.clientWidth })
    }
  })
  resizeObserver.observe(chartContainerRef.value)
}

async function loadKline() {
  if (!candleSeries) return
  loading.value = true
  try {
    const { data } = await api.get('/api/v1/aicoin/kline', {
      params: { symbol: selectedSymbol.value, period: period.value, size: 300 }
    })
    const raw = data?.data || []
    if (!raw.length) {
      loading.value = false
      return
    }
    const candles = raw.map(d => ({
      time: d[0],
      open: d[1],
      high: d[2],
      low: d[3],
      close: d[4],
    }))
    const volumes = raw.map(d => ({
      time: d[0],
      value: d[5] || 0,
      color: d[4] >= d[1] ? 'rgba(14,203,129,0.3)' : 'rgba(246,70,93,0.3)',
    }))
    candleSeries.setData(candles)
    volumeSeries.setData(volumes)
    chart.timeScale().fitContent()

    const last = raw[raw.length - 1]
    const first = raw[0]
    const change = first[1] > 0 ? ((last[4] - first[1]) / first[1]) * 100 : 0
    ohlc.value = {
      o: last[1].toLocaleString(),
      h: last[2].toLocaleString(),
      l: last[3].toLocaleString(),
      c: last[4].toLocaleString(),
      change,
    }
  } catch (err) {
    console.error('K-line load error:', err)
  }
  loading.value = false
}

function handleClickOutside(e) {
  if (searchWrapRef.value && !searchWrapRef.value.contains(e.target)) {
    showDropdown.value = false
  }
}

watch(period, () => loadKline())

onMounted(async () => {
  document.addEventListener('click', handleClickOutside)
  await nextTick()
  initChart()
  loadKline()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) { chart.remove(); chart = null }
})
</script>
