<template>
  <div>
    <div class="flex space-x-2 mb-4">
      <button
        @click="activeTab = 'forward'"
        :class="['flex-1 py-2 rounded font-medium transition', activeTab === 'forward' ? 'bg-green-500 text-white' : 'bg-dark-200 text-gray-400']"
      >
        Forward Arbitrage
      </button>
      <button
        @click="activeTab = 'reverse'"
        :class="['flex-1 py-2 rounded font-medium transition', activeTab === 'reverse' ? 'bg-red-500 text-white' : 'bg-dark-200 text-gray-400']"
      >
        Reverse Arbitrage
      </button>
    </div>

    <form @submit.prevent="handleSubmit" class="space-y-4">
      <div>
        <label class="block text-sm font-medium mb-2">Quantity</label>
        <input
          v-model.number="quantity"
          type="number"
          step="0.001"
          class="input-field"
          placeholder="0.000"
          required
        />
      </div>

      <div>
        <label class="block text-sm font-medium mb-2">Binance Account</label>
        <select v-model="binanceAccountId" class="input-field" required>
          <option value="">Select Account</option>
          <option v-for="account in binanceAccounts" :key="account.id" :value="account.id">
            {{ account.name }}
          </option>
        </select>
      </div>

      <div>
        <label class="block text-sm font-medium mb-2">Bybit Account</label>
        <select v-model="bybitAccountId" class="input-field" required>
          <option value="">Select Account</option>
          <option v-for="account in bybitAccounts" :key="account.id" :value="account.id">
            {{ account.name }}
          </option>
        </select>
      </div>

      <div class="bg-dark-200 rounded p-3 space-y-2 text-sm">
        <div class="flex justify-between">
          <span class="text-gray-400">Direction:</span>
          <span class="font-medium capitalize">{{ activeTab }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-400">Estimated Spread:</span>
          <span class="font-medium text-primary">{{ estimatedSpread }}</span>
        </div>
      </div>

      <button
        type="submit"
        :class="['w-full py-3 rounded font-medium transition', activeTab === 'forward' ? 'btn-buy' : 'btn-sell']"
        :disabled="loading"
      >
        {{ loading ? 'Executing...' : `Execute ${activeTab} Arbitrage` }}
      </button>

      <div v-if="error" class="text-red-500 text-sm">
        {{ error }}
      </div>

      <div v-if="success" class="text-green-500 text-sm">
        {{ success }}
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const marketStore = useMarketStore()

const activeTab = ref('forward')
const quantity = ref(0.1)
const binanceAccountId = ref('')
const bybitAccountId = ref('')
const binanceAccounts = ref([])
const bybitAccounts = ref([])
const loading = ref(false)
const error = ref('')
const success = ref('')

const estimatedSpread = computed(() => {
  const data = marketStore.marketData
  if (!data) return '0.00'
  return data.spread.toFixed(2)
})

onMounted(async () => {
  await fetchAccounts()
})

async function fetchAccounts() {
  try {
    const response = await api.get('/api/v1/accounts')
    const accounts = response.data
    binanceAccounts.value = accounts.filter(a => a.platform === 'binance')
    bybitAccounts.value = accounts.filter(a => a.platform === 'bybit')
  } catch (err) {
    console.error('Failed to fetch accounts:', err)
  }
}

async function handleSubmit() {
  error.value = ''
  success.value = ''
  loading.value = true

  try {
    const response = await api.post('/api/v1/strategies/execute', {
      symbol: 'XAUUSD',
      direction: activeTab.value,
      quantity: quantity.value,
      binance_account_id: binanceAccountId.value,
      bybit_account_id: bybitAccountId.value
    })

    success.value = `Arbitrage executed successfully! Task ID: ${response.data.task_id}`

    // Reset form
    setTimeout(() => {
      success.value = ''
    }, 5000)
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to execute arbitrage'
  } finally {
    loading.value = false
  }
}
</script>
