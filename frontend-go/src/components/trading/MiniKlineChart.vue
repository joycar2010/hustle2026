<template>
  <div class="space-y-2 p-2">
    <!-- Toolbar: search + periods + symbol + loading + refresh -->
    <div class="flex items-center gap-2 flex-wrap">
      <div class="relative">
        <input
          class="w-44 bg-[#1a1a22] border border-[#2d2d3d] rounded px-2 py-1 text-xs text-[#e5e7eb] placeholder:text-[#6b7280] focus:outline-none focus:border-[#fcd535]"
          placeholder="搜索币种 (BTC, ETH...)"
          :value="query"
          @input="handleSearch($event.target.value)"
          @focus="showSearch = results.length > 0"
          @blur="hideSearch"
        />
        <div
          v-if="showSearch && results.length > 0"
          class="absolute z-50 mt-1 w-72 max-h-60 overflow-y-auto rounded border border-[#2d2d3d] bg-[#141420] shadow-lg"
        >
          <button
            v-for="(c, i) in results"
            :key="(c.coinKey || '') + i"
            class="flex w-full items-center justify-between px-3 py-1.5 text-xs hover:bg-[#1e1e2e] text-left"
            @mousedown="selectCoin(c)"
          >
            <div class="flex items-center gap-2">
              <span class="font-medium text-[#e5e7eb]">{{ c.coinShow || c.coinName }}</span>
              <span
                v-if="c.degree24H && c.degree24H !== '-'"
                :class="parseFloat(c.degree24H) >= 0 ? 'text-[#22c55e]' : 'text-[#ef4444]'"
                class="text-[10px]"
              >
                {{ parseFloat(c.degree24H) >= 0 ? '+' : '' }}{{ c.degree24H }}%
              </span>
            </div>
            <span class="text-[10px] text-[#6b7280]">${{ c.price || '—' }}</span>
          </button>
        </div>
      </div>

      <div class="flex rounded border border-[#2d2d3d]">
        <button
          v-for="p in PERIODS"
          :key="p.value"
          @click="period = p.value; loadKline()"
          :class="[
            'px-2 py-1 text-[10px] border-r border-[#2d2d3d] last:border-0 transition-colors',
            period === p.value
              ? 'bg-[#fcd535] text-black font-medium'
              : 'text-[#6b7280] hover:bg-[#1e1e2e] hover:text-[#e5e7eb]'
          ]"
        >
          {{ p.label }}
        </button>
      </div>

      <span class="text-xs font-medium text-[#fcd535]">{{ selectedLabel }}</span>
      <span v-if="loading" class="text-[10px] text-[#6b7280]">加载中...</span>
      <button @click="loadKline" class="text-[#6b7280] hover:text-[#e5e7eb] text-xs px-1">⟳</button>
    </div>

    <!-- OHLC bar -->
    <div class="flex items-center gap-3 text-[10px] font-mono">
      <span class="text-[#6b7280]">开 <span class="text-[#e5e7eb]">{{ ohlc.o.toFixed(4) }}</span></span>
      <span class="text-[#6b7280]">高 <span class="text-[#22c55e]">{{ ohlc.h.toFixed(4) }}</span></span>
      <span class="text-[#6b7280]">低 <span class="text-[#ef4444]">{{ ohlc.l.toFixed(4) }}</span></span>
      <span class="text-[#6b7280]">收 <span class="text-[#e5e7eb]">{{ ohlc.c.toFixed(4) }}</span></span>
      <span :class="ohlc.change >= 0 ? 'text-[#22c55e]' : 'text-[#ef4444]'">
        {{ ohlc.change >= 0 ? '+' : '' }}{{ ohlc.change.toFixed(2) }}%
      </span>
    </div>

    <!-- Chart container -->
    <div class="rounded border border-[#2d2d3d] overflow-hidden">
      <div ref="chartContainer" class="w-full" :style="{ height: chartHeight + 'px' }"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, ColorType } from 'lightweight-charts'

const props = defineProps({
  visible: { type: Boolean, default: true }
})

const PERIODS = [
  { label: '1分', value: '1' },
  { label: '5分', value: '5' },
  { label: '15分', value: '15' },
  { label: '30分', value: '30' },
  { label: '1时', value: '60' },
  { label: '4时', value: '240' },
  { label: '1天', value: '1440' },
]

const isMobile = ref(window.innerWidth < 768)
const chartHeight = ref(isMobile.value ? 260 : 340)

const query = ref('')
const results = ref([])
const showSearch = ref(false)
const selectedSymbol = ref('xauswapusdt:binance')
const selectedLabel = ref('XAU/USDT (Binance)')
const period = ref('60')
const loading = ref(false)
const ohlc = ref({ o: 0, h: 0, l: 0, c: 0, change: 0 })

const chartContainer = ref(null)
let chart = null
let candleSeries = null
let volumeSeries = null
let searchTimer = null

function initChart() {
  if (!chartContainer.value || chart) return
  chart = createChart(chartContainer.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#0a0a12' },
      textColor: '#9ca3af',
    },
    grid: {
      vertLines: { color: '#1e1e2e' },
      horzLines: { color: '#1e1e2e' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: { borderColor: '#2d2d3d' },
    timeScale: { borderColor: '#2d2d3d', timeVisible: true, secondsVisible: false },
    width: chartContainer.value.clientWidth,
    height: chartHeight.value,
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#22c55e',
    downColor: '#ef4444',
    borderDownColor: '#ef4444',
    borderUpColor: '#22c55e',
    wickDownColor: '#ef4444',
    wickUpColor: '#22c55e',
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })
  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  })

  nextTick(() => {
    if (chartContainer.value) {
      const links = chartContainer.value.querySelectorAll('a[href*="tradingview"]')
      links.forEach(a => a.style.display = 'none')
    }
  })
}

function destroyChart() {
  if (chart) { chart.remove(); chart = null; candleSeries = null; volumeSeries = null }
}

async function loadKline() {
  if (!selectedSymbol.value) return
  loading.value = true
  try {
    const token = localStorage.getItem('token')
    const params = new URLSearchParams({
      symbol: selectedSymbol.value,
      period: period.value,
      size: '300',
    })
    const resp = await fetch(`/api/v1/aicoin/kline?${params}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const json = await resp.json()
    const raw = json.data || []
    if (!raw.length) return

    if (!chart) { await nextTick(); initChart() }

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
      color: d[4] >= d[1] ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
    }))

    candleSeries.setData(candles)
    volumeSeries.setData(volumes)
    chart.timeScale().fitContent()

    const last = candles[candles.length - 1]
    const first = candles[0]
    if (last && first) {
      const change = ((last.close - first.open) / first.open) * 100
      ohlc.value = { o: last.open, h: last.high, l: last.low, c: last.close, change }
    }
  } catch (e) {
    console.error('K-line load failed:', e)
  } finally {
    loading.value = false
  }
}

function handleSearch(val) {
  query.value = val
  if (searchTimer) clearTimeout(searchTimer)
  if (val.length < 1) { results.value = []; showSearch.value = false; return }
  searchTimer = setTimeout(async () => {
    try {
      const token = localStorage.getItem('token')
      const resp = await fetch(`/api/v1/aicoin/coin-search?q=${encodeURIComponent(val)}`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      })
      if (!resp.ok) return
      const data = await resp.json()
      results.value = Array.isArray(data) ? data : []
      showSearch.value = results.value.length > 0
    } catch { results.value = [] }
  }, 300)
}

function selectCoin(coin) {
  const dbKey = coin.dbKeys ? coin.dbKeys.split(',')[0] : coin.coinKey
  selectedSymbol.value = dbKey
  selectedLabel.value = coin.coinShow || coin.coinName
  query.value = ''
  showSearch.value = false
  loadKline()
}

function hideSearch() {
  setTimeout(() => { showSearch.value = false }, 200)
}

function onResize() {
  isMobile.value = window.innerWidth < 768
  chartHeight.value = isMobile.value ? 260 : 340
  if (chart && chartContainer.value) {
    chart.applyOptions({ width: chartContainer.value.clientWidth, height: chartHeight.value })
  }
}

watch(() => props.visible, (v) => {
  if (v && chart && chartContainer.value) {
    nextTick(() => {
      chart.applyOptions({ width: chartContainer.value.clientWidth })
      chart.timeScale().fitContent()
    })
  }
})

let resizeObs = null
onMounted(() => {
  window.addEventListener('resize', onResize)
  nextTick(() => { initChart(); loadKline() })
  if (window.ResizeObserver && chartContainer.value) {
    resizeObs = new ResizeObserver(() => {
      if (chart && chartContainer.value) {
        chart.applyOptions({ width: chartContainer.value.clientWidth, height: chartHeight.value })
      }
    })
    resizeObs.observe(chartContainer.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (resizeObs) resizeObs.disconnect()
  destroyChart()
})
</script>

<style scoped>
:deep(a[href*="tradingview"]) {
  display: none !important;
}
</style>
