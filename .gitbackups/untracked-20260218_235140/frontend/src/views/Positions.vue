<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">Open Positions</h1>

    <div class="card">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-2">ID</th>
              <th class="pb-2">Symbol</th>
              <th class="pb-2">Direction</th>
              <th class="pb-2">Quantity</th>
              <th class="pb-2">Entry Price</th>
              <th class="pb-2">Current Price</th>
              <th class="pb-2">P&L</th>
              <th class="pb-2">Duration</th>
              <th class="pb-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="position in positions" :key="position.id" class="border-b border-gray-800">
              <td class="py-3">#{{ position.id }}</td>
              <td>{{ position.symbol }}</td>
              <td>
                <span :class="position.direction === 'forward' ? 'text-green-500' : 'text-red-500'">
                  {{ position.direction }}
                </span>
              </td>
              <td>{{ position.quantity }}</td>
              <td>${{ position.entry_price }}</td>
              <td>${{ position.current_price }}</td>
              <td :class="position.pnl >= 0 ? 'text-green-500' : 'text-red-500'">
                ${{ position.pnl.toFixed(2) }}
              </td>
              <td>{{ position.duration }}</td>
              <td>
                <button @click="closePosition(position.id)" class="text-red-500 hover:text-red-400">
                  Close
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'

const positions = ref([])

onMounted(() => {
  fetchPositions()
  setInterval(fetchPositions, 3000)
})

async function fetchPositions() {
  try {
    const response = await api.get('/api/v1/strategies/tasks?status=open')
    positions.value = response.data
  } catch (error) {
    console.error('Failed to fetch positions:', error)
  }
}

async function closePosition(id) {
  try {
    await api.post(`/api/v1/strategies/tasks/${id}/close`)
    await fetchPositions()
  } catch (error) {
    console.error('Failed to close position:', error)
  }
}
</script>
