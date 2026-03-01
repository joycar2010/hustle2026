<template>
  <div class="h-full flex flex-col">
    <div class="p-3 border-b border-[#2b3139] flex items-center justify-between">
      <h3 class="text-sm font-bold">盈亏曲线图</h3>
      <div class="flex space-x-1">
        <button
          v-for="period in periods"
          :key="period"
          @click="selectedPeriod = period"
          :class="[
            'px-2 py-1 text-xs rounded transition-colors',
            selectedPeriod === period
              ? 'bg-[#f0b90b] text-[#1a1d21]'
              : 'bg-[#252930] text-gray-400 hover:bg-[#2b3139]'
          ]"
        >
          {{ period }}
        </button>
      </div>
    </div>

    <div class="flex-1 p-3">
      <canvas ref="chartCanvas"></canvas>
    </div>

    <div class="p-3 border-t border-[#2b3139] grid grid-cols-2 gap-4">
      <div class="space-y-2">
        <div class="flex items-center space-x-2">
          <div class="w-3 h-3 rounded-full bg-[#0ecb81]"></div>
          <span class="text-xs text-gray-400">Bybit做多</span>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <div class="text-xs text-gray-400">当前</div>
            <div class="text-sm font-bold font-mono" :class="stats.bybit.current >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
              {{ stats.bybit.current >= 0 ? '+' : '' }}{{ stats.bybit.current.toFixed(2) }} USDT
            </div>
          </div>
          <div>
            <div class="text-xs text-gray-400">累计</div>
            <div class="text-sm font-bold font-mono" :class="stats.bybit.total >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
              {{ stats.bybit.total >= 0 ? '+' : '' }}{{ stats.bybit.total.toFixed(2) }} USDT
            </div>
          </div>
        </div>
      </div>
      <div class="space-y-2">
        <div class="flex items-center space-x-2">
          <div class="w-3 h-3 rounded-full bg-[#f6465d]"></div>
          <span class="text-xs text-gray-400">Binance做多</span>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <div class="text-xs text-gray-400">当前</div>
            <div class="text-sm font-bold font-mono" :class="stats.binance.current >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
              {{ stats.binance.current >= 0 ? '+' : '' }}{{ stats.binance.current.toFixed(2) }} USDT
            </div>
          </div>
          <div>
            <div class="text-xs text-gray-400">累计</div>
            <div class="text-sm font-bold font-mono" :class="stats.binance.total >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
              {{ stats.binance.total >= 0 ? '+' : '' }}{{ stats.binance.total.toFixed(2) }} USDT
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { Chart, registerables } from 'chart.js'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

Chart.register(...registerables)

const marketStore = useMarketStore()
const chartCanvas = ref(null)
let chartInstance = null

const selectedPeriod = ref('1m')
const periods = ['1m', '5m', '15m', '1H']

const profitData = ref([])

const stats = computed(() => {
  if (profitData.value.length === 0) {
    return {
      bybit: { current: 0, total: 0 },
      binance: { current: 0, total: 0 }
    }
  }

  const bybitValues = profitData.value.map(d => d.bybit)
  const binanceValues = profitData.value.map(d => d.binance)

  return {
    bybit: {
      current: bybitValues[bybitValues.length - 1] || 0,
      total: bybitValues.reduce((a, b) => a + b, 0)
    },
    binance: {
      current: binanceValues[binanceValues.length - 1] || 0,
      total: binanceValues.reduce((a, b) => a + b, 0)
    }
  }
})

onMounted(() => {
  initChart()
  // 首次加载历史数据
  fetchInitialData()

  // 建立WebSocket连接
  if (!marketStore.connected) {
    marketStore.connect()
  }
})

onUnmounted(() => {
  if (chartInstance) {
    chartInstance.destroy()
  }
})

// 监听WebSocket实时数据更新
watch(() => marketStore.marketData, (newData) => {
  if (newData && profitData.value.length > 0) {
    // 计算新的点差数据
    // 新公式：
    // 正向开仓: binance做多点差 = bybit_bid - binance_bid
    // 反向开仓: bybit做多点差 = binance_ask - bybit_ask
    const forwardSpread = newData.bybit_bid - newData.binance_bid  // 做多Binance (正向开仓)
    const reverseSpread = newData.binance_ask - newData.bybit_ask  // 做多Bybit (反向开仓)

    const newPoint = {
      timestamp: newData.timestamp || new Date().toISOString(),
      bybit: reverseSpread,
      binance: forwardSpread
    }

    // 添加新数据点并保持数据点数量
    const maxPoints = getPeriodDataPoints(selectedPeriod.value)
    profitData.value = [...profitData.value, newPoint].slice(-maxPoints)

    updateChart()
  }
}, { immediate: false })

watch(selectedPeriod, () => {
  fetchInitialData()
})

// 首次加载历史数据
async function fetchInitialData() {
  try {
    const dataPoints = getPeriodDataPoints(selectedPeriod.value)

    const response = await api.get('/api/v1/market/spread/history', {
      params: {
        limit: dataPoints,
        binance_symbol: 'XAUUSDT',
        bybit_symbol: 'XAUUSDT'
      }
    })

    const data = response.data

    // Transform spread data to profit/loss format
    const newData = data.map(item => {
      const forwardSpread = item.bybit_quote.ask - item.binance_quote.bid  // 做多Binance
      const reverseSpread = item.binance_quote.ask - item.bybit_quote.bid  // 做多Bybit

      return {
        timestamp: item.timestamp,
        bybit: reverseSpread,
        binance: forwardSpread,
      }
    }).reverse() // Reverse to show oldest to newest

    profitData.value = newData
    updateChart()
  } catch (error) {
    console.error('Failed to fetch initial data:', error)
  }
}

function initChart() {
  if (!chartCanvas.value) return

  const ctx = chartCanvas.value.getContext('2d')

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Bybit做多',
          data: [],
          borderColor: '#0ecb81',
          backgroundColor: 'rgba(14, 203, 129, 0.1)',
          borderWidth: 2,
          fill: false,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
        {
          label: 'Binance做多',
          data: [],
          borderColor: '#f6465d',
          backgroundColor: 'rgba(246, 70, 93, 0.1)',
          borderWidth: 2,
          fill: false,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index',
      },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          backgroundColor: '#1e2329',
          titleColor: '#848E9C',
          bodyColor: '#FFFFFF',
          borderColor: '#2b3139',
          borderWidth: 1,
          padding: 12,
          displayColors: true,
          callbacks: {
            label: (context) => {
              const value = context.parsed.y
              const prefix = value >= 0 ? '+' : ''
              return `${context.dataset.label}: ${prefix}${value.toFixed(2)} USDT`
            },
          },
        },
      },
      scales: {
        x: {
          grid: {
            color: '#2b3139',
            drawBorder: false,
          },
          ticks: {
            color: '#848E9C',
            maxRotation: 0,
          },
        },
        y: {
          grid: {
            color: '#2b3139',
            drawBorder: false,
          },
          ticks: {
            color: '#848E9C',
            callback: (value) => {
              const prefix = value >= 0 ? '+' : ''
              return `${prefix}${value.toFixed(2)} USDT`
            },
          },
        },
      },
    },
  })
}

function getPeriodDataPoints(period) {
  const points = {
    '1m': 60,
    '5m': 60,
    '15m': 60,
    '1H': 60,
  }
  return points[period] || 60
}

function updateChart() {
  if (!chartInstance) return

  chartInstance.data.labels = profitData.value.map(d => formatTime(d.timestamp))
  chartInstance.data.datasets[0].data = profitData.value.map(d => d.bybit)
  chartInstance.data.datasets[1].data = profitData.value.map(d => d.binance)
  chartInstance.update('none')
}

function formatTime(timestamp) {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}
</script>