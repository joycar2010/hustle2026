<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">Strategies</h1>

    <div class="card mb-6">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-bold">Automated Strategies</h2>
        <button class="btn-primary">Create Strategy</button>
      </div>

      <div class="space-y-4">
        <div v-for="strategy in strategies" :key="strategy.id" class="bg-dark-200 rounded p-4">
          <div class="flex justify-between items-center">
            <div>
              <h3 class="font-bold">{{ strategy.name }}</h3>
              <p class="text-sm text-gray-400">{{ strategy.direction }} | Min Spread: ${{ strategy.min_spread }}</p>
            </div>
            <div class="flex items-center space-x-4">
              <span :class="['px-3 py-1 rounded text-sm', strategy.status === 'running' ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400']">
                {{ strategy.status }}
              </span>
              <button
                @click="toggleStrategy(strategy)"
                :class="strategy.status === 'running' ? 'btn-sell' : 'btn-buy'"
              >
                {{ strategy.status === 'running' ? 'Stop' : 'Start' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'

const strategies = ref([])

onMounted(() => {
  fetchStrategies()
})

async function fetchStrategies() {
  try {
    const response = await api.get('/api/v1/strategies')
    strategies.value = response.data
  } catch (error) {
    console.error('Failed to fetch strategies:', error)
  }
}

async function toggleStrategy(strategy) {
  try {
    const endpoint = strategy.status === 'running' ? 'stop' : 'start'
    await api.post(`/api/v1/automation/strategies/${strategy.id}/${endpoint}`)
    await fetchStrategies()
  } catch (error) {
    console.error('Failed to toggle strategy:', error)
  }
}
</script>
