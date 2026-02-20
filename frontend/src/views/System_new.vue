<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">Accounts</h1>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Binance Accounts -->
      <div class="card">
        <h2 class="text-xl font-bold mb-4">Binance Accounts</h2>
        <div class="space-y-4">
          <div v-for="account in binanceAccounts" :key="account.id" class="bg-dark-200 rounded p-4">
            <div class="flex justify-between items-center mb-2">
              <h3 class="font-bold">{{ account.name }}</h3>
              <span :class="['px-2 py-1 rounded text-xs', account.is_active ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400']">
                {{ account.is_active ? 'Active' : 'Inactive' }}
              </span>
            </div>
            <div class="text-sm text-gray-400">
              Balance: {{ account.balance?.toFixed(2) || '0.00' }} USDT
            </div>
          </div>
        </div>
      </div>

      <!-- Bybit Accounts -->
      <div class="card">
        <h2 class="text-xl font-bold mb-4">Bybit MT5 Accounts</h2>
        <div class="space-y-4">
          <div v-for="account in bybitAccounts" :key="account.id" class="bg-dark-200 rounded p-4">
            <div class="flex justify-between items-center mb-2">
              <h3 class="font-bold">{{ account.name }}</h3>
              <span :class="['px-2 py-1 rounded text-xs', account.is_active ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400']">
                {{ account.is_active ? 'Active' : 'Inactive' }}
              </span>
            </div>
            <div class="text-sm text-gray-400">
              MT5 ID: {{ account.mt5_id }}<br>
              Balance: {{ account.balance?.toFixed(2) || '0.00' }} USDT
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

const binanceAccounts = ref([])
const bybitAccounts = ref([])

onMounted(() => {
  fetchAccounts()
})

async function fetchAccounts() {
  try {
    const response = await api.get('/api/v1/accounts')
    const accounts = response.data
    binanceAccounts.value = accounts.filter(a => a.platform === 'binance')
    bybitAccounts.value = accounts.filter(a => a.platform === 'bybit')
  } catch (error) {
    console.error('Failed to fetch accounts:', error)
  }
}
</script>
