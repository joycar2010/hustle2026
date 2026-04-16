<template>
  <div class="h-full flex flex-col w-full">
    <div class="p-1 border-b border-[#2b3139] w-full">
      <h3 class="text-sm font-bold text-center text-[#f0b90b]">点差数据流</h3>
    </div>
    <div class="flex-1 overflow-y-auto md:overflow-y-auto text-xs overflow-x-hidden max-md:overflow-y-visible max-md:h-auto w-full">
      <table class="w-full">
        <thead class="sticky top-0 bg-[#1e2329]">
          <tr class="text-left border-b border-[#2b3139]">
            <th class="p-0.5 md:p-1 w-20 md:w-24 text-sm text-[#f0b90b]">时间</th>
            <th class="p-0.5 md:p-1 text-center text-sm text-[#f0b90b]">做多对冲</th>
            <th class="p-0.5 md:p-1 text-center text-sm text-[#f0b90b]">做多主账号</th>
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
// Optimized: Only update if spread values actually changed
watch(() => marketStore.marketData, (newData) => {
  if (newData) {
    // 使用统一的点差计算管理组件
    const spreads = calculateAllSpreads(newData)

    // Only add if spread values are different from last entry
    const lastEntry = spreadHistory.value[0]
    const hasChanged = !lastEntry ||
      Math.abs(lastEntry.bybitSpread - spreads.reverseOpening) > 0.01 ||
      Math.abs(lastEntry.binanceSpread - spreads.forwardOpening) > 0.01

    if (hasChanged) {
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
  }
}, { immediate: false, deep: false }) // Shallow watch for better performance

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

<style scoped>
/* Smooth transitions for spread values */
.text-\[\#0ecb81\], .text-\[\#f6465d\] {
  transition: color 0.3s ease-in-out;
}

/* Fade in animation for new rows */
@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(-10px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

tr {
  animation: slideIn 0.3s ease-in-out;
}

/* Smooth font transitions */
.font-mono {
  transition: all 0.2s ease-in-out;
}

/* Highlight new entries */
.bg-green-500\/10, .bg-red-500\/10 {
  transition: background-color 0.5s ease-in-out;
}

/* 移动端优化 - 禁用动画 (统一所有移动设备) */
@media (orientation: portrait) and (max-width: 1500px), (max-width: 767px) {
  * {
    animation: none !important;
    transition: none !important;
  }

  /* 统一表格字体 - 适用于所有移动设备（参考iPhone显示效果）*/
  table {
    font-size: 1.05rem !important;
  }

  th {
    font-size: 1.125rem !important;
    padding: 0.5rem 0.55rem !important;
  }

  td {
    font-size: 1rem !important;
    padding: 0.5rem 0.55rem !important;
  }

  /* 统一标题 */
  h3 {
    font-size: 1.25rem !important;
  }
}

/* ========== 移除单独的2K屏幕媒体查询 ========== */
</style>
