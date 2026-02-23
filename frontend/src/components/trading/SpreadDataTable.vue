<template>
  <div class="h-full flex flex-col">
    <div class="p-2 border-b border-[#2b3139]">
      <h3 class="text-xs font-bold">点差数据流</h3>
    </div>
    <div class="flex-1 overflow-y-auto text-xs">
      <table class="w-full">
        <thead class="sticky top-0 bg-[#1e2329]">
          <tr class="text-left text-gray-400 border-b border-[#2b3139]">
            <th class="p-2 w-24">时间</th>
            <th class="p-2 text-center">做多Bybit</th>
            <th class="p-2 text-center">做多Binance</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in spreadHistory"
            :key="item.id"
            class="border-b border-[#2b3139] hover:bg-[#252930] transition-colors"
            :class="{ 'animate-pulse': item.isNew }"
          >
            <td class="p-2 text-gray-400 font-mono">{{ formatTime(item.timestamp) }}</td>
            <td class="p-2 text-center font-mono font-bold" :class="getBybitClass(item.bybitSpread, index)">
              {{ item.bybitSpread.toFixed(2) }} USDT
            </td>
            <td class="p-2 text-center font-mono font-bold" :class="getBinanceClass(item.binanceSpread, index)">
              {{ item.binanceSpread.toFixed(2) }} USDT
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import api from '@/services/api'

const spreadHistory = ref([])
let updateInterval = null

onMounted(() => {
  fetchSpreadData()
  updateInterval = setInterval(fetchSpreadData, 1000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchSpreadData() {
  try {
    const response = await api.get('/api/v1/market/spread/history', {
      params: {
        limit: 10,
        binance_symbol: 'XAUUSDT',
        bybit_symbol: 'XAUUSDT'
      }
    })

    const data = response.data

    // Transform API data to component format
    // 做多Bybit点差 (Reverse spread, Red) = Binance ASK - Bybit BID
    // 做多Binance点差 (Forward spread, Green) = Bybit ASK - Binance BID
    const newData = data.map(item => ({
      id: item.id || Date.now() + Math.random(),
      timestamp: new Date(item.timestamp).getTime(),
      bybitSpread: item.binance_quote.ask - item.bybit_quote.bid, // 做多Bybit (Reverse)
      binanceSpread: item.bybit_quote.ask - item.binance_quote.bid, // 做多Binance (Forward)
      isNew: false
    }))

    // Mark the first item as new if it's different from current first item
    if (newData.length > 0 && spreadHistory.value.length > 0) {
      if (newData[0].timestamp !== spreadHistory.value[0].timestamp) {
        newData[0].isNew = true
        setTimeout(() => {
          newData[0].isNew = false
        }, 1000)
      }
    }

    spreadHistory.value = newData
  } catch (error) {
    console.error('Failed to fetch spread data:', error)
  }
}

function formatTime(timestamp) {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

function getBybitClass(spread, index) {
  if (index === 0) return 'text-[#0ecb81]'
  const prevSpread = spreadHistory.value[index - 1]?.bybitSpread
  if (!prevSpread) return 'text-[#0ecb81]'
  if (spread > prevSpread) return 'text-[#0ecb81]'
  if (spread < prevSpread) return 'text-[#f6465d]'
  return 'text-[#0ecb81]'
}

function getBinanceClass(spread, index) {
  if (index === 0) return 'text-[#f6465d]'
  const prevSpread = spreadHistory.value[index - 1]?.binanceSpread
  if (!prevSpread) return 'text-[#f6465d]'
  if (spread > prevSpread) return 'text-[#0ecb81]'
  if (spread < prevSpread) return 'text-[#f6465d]'
  return 'text-[#f6465d]'
}
</script>
