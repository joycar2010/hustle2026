<template>
  <div class="h-full flex flex-col">
    <div class="p-1 border-b border-[#2b3139]">
      <h3 class="text-xs font-bold">点差数据流</h3>
    </div>
    <div class="flex-1 overflow-y-auto md:overflow-y-auto text-xs overflow-x-auto max-md:overflow-y-visible max-md:h-auto">
      <table class="w-full min-w-[300px]">
        <thead class="sticky top-0 bg-[#1e2329]">
          <tr class="text-left text-gray-400 border-b border-[#2b3139]">
            <th class="p-0.5 md:p-1 w-20 md:w-24">时间</th>
            <th class="p-0.5 md:p-1 text-center">做多Bybit</th>
            <th class="p-0.5 md:p-1 text-center">做多Binance</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in spreadHistory"
            :key="item.id"
            class="border-b border-[#2b3139] hover:bg-[#252930] transition-colors"
            :class="{ 'animate-pulse': item.isNew }"
          >
            <td class="p-0.5 md:p-1 text-gray-400 font-mono text-[10px] md:text-xs">{{ formatTime(item.timestamp) }}</td>
            <td class="p-0.5 md:p-1 text-center font-mono font-bold" :class="getBybitClass(item.bybitSpread, index)">
              {{ item.bybitSpread.toFixed(2) }} USDT
            </td>
            <td class="p-0.5 md:p-1 text-center font-mono font-bold" :class="getBinanceClass(item.binanceSpread, index)">
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
import { calculateAllSpreads } from '@/composables/useSpreadCalculator'
import { formatTimeBeijing } from '@/utils/timeUtils'

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
    // 使用统一的点差计算管理组件
    const spreads = calculateAllSpreads(newData)

    const spreadItem = {
      id: Date.now() + Math.random(),
      timestamp: new Date(newData.timestamp || Date.now()).getTime(),
      bybitSpread: spreads.reverseOpening,  // 反向开仓：bybit做多点差 = binance_ask - bybit_ask
      binanceSpread: spreads.forwardOpening,  // 正向开仓：binance做多点差 = bybit_bid - binance_bid
      isNew: true
    }

    // 添加到历史记录（保持最新8条）
    spreadHistory.value = [spreadItem, ...spreadHistory.value].slice(0, 8)

    // 移除新标记
    setTimeout(() => {
      spreadItem.isNew = false
    }, 1000)
  }
}, { immediate: false })

function formatTime(timestamp) {
  return formatTimeBeijing(timestamp)
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
