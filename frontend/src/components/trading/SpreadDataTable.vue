<template>
  <div class="h-full flex flex-col">
    <div class="p-2 border-b border-[#2b3139]">
      <h3 class="text-xs md:text-sm font-bold">点差数据流</h3>
    </div>
    <div class="flex-1 overflow-y-auto text-xs overflow-x-auto">
      <table class="w-full min-w-[300px]">
        <thead class="sticky top-0 bg-[#1e2329]">
          <tr class="text-left text-gray-400 border-b border-[#2b3139]">
            <th class="p-1 md:p-2 w-20 md:w-24">时间</th>
            <th class="p-1 md:p-2 text-center">做多Bybit</th>
            <th class="p-1 md:p-2 text-center">做多Binance</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in spreadHistory"
            :key="item.id"
            class="border-b border-[#2b3139] hover:bg-[#252930] transition-colors"
            :class="{ 'animate-pulse': item.isNew }"
          >
            <td class="p-1 md:p-2 text-gray-400 font-mono text-[10px] md:text-xs">{{ formatTime(item.timestamp) }}</td>
            <td class="p-1 md:p-2 text-center font-mono font-bold" :class="getBybitClass(item.bybitSpread, index)">
              {{ item.bybitSpread.toFixed(2) }} USDT
            </td>
            <td class="p-1 md:p-2 text-center font-mono font-bold" :class="getBinanceClass(item.binanceSpread, index)">
              {{ item.binanceSpread.toFixed(2) }} USDT
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
const spreadHistory = ref([])

onMounted(() => {
  // 建立WebSocket连接
  if (!marketStore.connected) {
    marketStore.connect()
  }
})

// 监听WebSocket市场数据更新
watch(() => marketStore.marketData, (newData) => {
  if (newData) {
    // 计算点差
    // 新公式：
    // 反向开仓: bybit做多点差 = binance_ask - bybit_ask
    // 正向开仓: binance做多点差 = bybit_bid - binance_bid
    const spreadItem = {
      id: Date.now() + Math.random(),
      timestamp: new Date(newData.timestamp || Date.now()).getTime(),
      bybitSpread: newData.binance_ask - newData.bybit_ask,  // 做多Bybit (反向开仓)
      binanceSpread: newData.bybit_bid - newData.binance_bid,  // 做多Binance (正向开仓)
      isNew: true
    }

    // 添加到历史记录（保持最新10条）
    spreadHistory.value = [spreadItem, ...spreadHistory.value].slice(0, 10)

    // 移除新标记
    setTimeout(() => {
      spreadItem.isNew = false
    }, 1000)
  }
}, { immediate: false })

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
