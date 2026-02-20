<template>
  <div class="card h-full">
    <h3 class="text-lg font-bold mb-4">Order Book</h3>

    <!-- Asks (Sell Orders) -->
    <div class="space-y-1 mb-4">
      <div v-for="(ask, index) in displayAsks" :key="`ask-${index}`" class="flex justify-between text-sm">
        <span class="text-red-500">{{ formatPrice(ask.price) }}</span>
        <span class="text-gray-400">{{ formatQuantity(ask.quantity) }}</span>
      </div>
    </div>

    <!-- Spread -->
    <div class="py-2 border-y border-gray-700 text-center">
      <div class="text-xs text-gray-400">Spread</div>
      <div class="text-lg font-bold text-primary">
        {{ spread }}
      </div>
    </div>

    <!-- Bids (Buy Orders) -->
    <div class="space-y-1 mt-4">
      <div v-for="(bid, index) in displayBids" :key="`bid-${index}`" class="flex justify-between text-sm">
        <span class="text-green-500">{{ formatPrice(bid.price) }}</span>
        <span class="text-gray-400">{{ formatQuantity(bid.quantity) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()

const displayAsks = computed(() => {
  return marketStore.orderBook.asks.slice(0, 10).reverse()
})

const displayBids = computed(() => {
  return marketStore.orderBook.bids.slice(0, 10)
})

const spread = computed(() => {
  const asks = marketStore.orderBook.asks
  const bids = marketStore.orderBook.bids
  if (asks.length && bids.length) {
    return (asks[0].price - bids[0].price).toFixed(2)
  }
  return '0.00'
})

onMounted(() => {
  marketStore.fetchOrderBook()
})

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function formatQuantity(qty) {
  return qty ? qty.toFixed(3) : '0.000'
}
</script>
