<template>
  <div class="card-elevated">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xl font-bold">Spread Curve</h2>
      <div class="flex space-x-2">
        <button
          v-for="period in periods"
          :key="period.value"
          @click="selectedPeriod = period.value"
          :class="[
            'px-3 py-1 rounded text-sm transition-colors',
            selectedPeriod === period.value
              ? 'bg-primary text-dark-300 font-medium'
              : 'bg-dark-300 text-text-secondary hover:bg-dark-50'
          ]"
        >
          {{ period.label }}
        </button>
      </div>
    </div>

    <div class="relative h-80">
      <canvas ref="chartCanvas"></canvas>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t border-border-secondary">
      <div>
        <div class="text-xs text-text-tertiary mb-1">Current Spread</div>
        <div class="text-lg font-bold font-mono text-primary">
          {{ formatPrice(stats.current) }} USDT
        </div>
      </div>
      <div>
        <div class="text-xs text-text-tertiary mb-1">Average</div>
        <div class="text-lg font-bold font-mono">
          {{ formatPrice(stats.average) }} USDT
        </div>
      </div>
      <div>
        <div class="text-xs text-text-tertiary mb-1">Max</div>
        <div class="text-lg font-bold font-mono text-success">
          {{ formatPrice(stats.max) }} USDT
        </div>
      </div>
      <div>
        <div class="text-xs text-text-tertiary mb-1">Min</div>
        <div class="text-lg font-bold font-mono text-danger">
          {{ formatPrice(stats.min) }} USDT
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { Chart, registerables } from 'chart.js'
import api from '@/services/api'

Chart.register(...registerables)

const chartCanvas = ref(null)
let chartInstance = null

const selectedPeriod = ref('1h')
const periods = [
  { label: '15m', value: '15m' },
  { label: '1H', value: '1h' },
  { label: '4H', value: '4h' },
  { label: '24H', value: '24h' },
]

const spreadData = ref([])

const stats = computed(() => {
  if (spreadData.value.length === 0) {
    return { current: 0, average: 0, max: 0, min: 0 }
  }

  const values = spreadData.value.map(d => d.spread)
  return {
    current: values[values.length - 1] || 0,
    average: values.reduce((a, b) => a + b, 0) / values.length,
    max: Math.max(...values),
    min: Math.min(...values),
  }
})

let updateInterval = null

onMounted(() => {
  initChart()
  fetchSpreadData()
  updateInterval = setInterval(fetchSpreadData, 5000)
})

onUnmounted(() => {
  if (chartInstance) {
    chartInstance.destroy()
  }
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

watch(selectedPeriod, () => {
  fetchSpreadData()
})

function initChart() {
  if (!chartCanvas.value) return

  const ctx = chartCanvas.value.getContext('2d')

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Spread',
          data: [],
          borderColor: '#F0B90B',
          backgroundColor: 'rgba(240, 185, 11, 0.1)',
          borderWidth: 2,
          fill: true,
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
          backgroundColor: '#1E2329',
          titleColor: '#B7BDC6',
          bodyColor: '#FFFFFF',
          borderColor: '#2B3139',
          borderWidth: 1,
          padding: 12,
          displayColors: false,
          callbacks: {
            label: (context) => `Spread: $${context.parsed.y.toFixed(2)}`,
          },
        },
      },
      scales: {
        x: {
          grid: {
            color: '#2B3139',
            drawBorder: false,
          },
          ticks: {
            color: '#848E9C',
            maxRotation: 0,
          },
        },
        y: {
          grid: {
            color: '#2B3139',
            drawBorder: false,
          },
          ticks: {
            color: '#848E9C',
            callback: (value) => `$${value.toFixed(2)}`,
          },
        },
      },
    },
  })
}

async function fetchSpreadData() {
  try {
    const dataPoints = getDataPointsForPeriod(selectedPeriod.value)

    const response = await api.get('/api/v1/market/spread/history', {
      params: {
        limit: dataPoints,
        binance_symbol: 'XAUUSDT',
        bybit_symbol: 'XAUUSDT'
      }
    })

    const data = response.data

    // Transform backend data to chart format
    const newData = data.map(item => {
      const forwardSpread = item.bybit_quote.ask - item.binance_quote.bid
      const reverseSpread = item.binance_quote.bid - item.bybit_quote.ask
      const spread = Math.max(Math.abs(forwardSpread), Math.abs(reverseSpread))

      return {
        timestamp: item.timestamp,
        spread: spread,
      }
    }).reverse() // Reverse to show oldest to newest

    spreadData.value = newData
    updateChart()
  } catch (error) {
    console.error('Failed to fetch spread data:', error)
  }
}

function updateChart() {
  if (!chartInstance) return

  chartInstance.data.labels = spreadData.value.map(d => formatTime(d.timestamp))
  chartInstance.data.datasets[0].data = spreadData.value.map(d => d.spread)
  chartInstance.update('none')
}

function getDataPointsForPeriod(period) {
  const points = {
    '15m': 30,
    '1h': 60,
    '4h': 48,
    '24h': 96,
  }
  return points[period] || 60
}

function getPeriodInterval(period) {
  const intervals = {
    '15m': 30 * 1000, // 30 seconds
    '1h': 60 * 1000, // 1 minute
    '4h': 5 * 60 * 1000, // 5 minutes
    '24h': 15 * 60 * 1000, // 15 minutes
  }
  return intervals[period] || 60 * 1000
}

function formatTime(timestamp) {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}
</script>