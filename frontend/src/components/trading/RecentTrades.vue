<template>
  <div class="card h-full">
    <h3 class="text-lg font-bold mb-4">Recent Trades</h3>

    <div class="space-y-2">
      <div class="flex justify-between text-xs text-gray-400 mb-2">
        <span>Price</span>
        <span>Quantity</span>
        <span>Time</span>
      </div>

      <div v-for="(trade, index) in recentTrades" :key="index" class="flex justify-between text-sm">
        <span :class="trade.side === 'buy' ? 'text-green-500' : 'text-red-500'">
          {{ formatPrice(trade.price) }}
        </span>
        <span class="text-gray-400">{{ formatQuantity(trade.quantity) }}</span>
        <span class="text-gray-400">{{ formatTime(trade.time) }}</span>
      </div>

      <div v-if="!recentTrades.length" class="text-center text-gray-400 py-8">
        No recent trades
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import dayjs from 'dayjs'

const recentTrades = ref([])

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function formatQuantity(qty) {
  return qty ? qty.toFixed(3) : '0.000'
}

function formatTime(time) {
  return dayjs(time).format('HH:mm:ss')
}
</script>
