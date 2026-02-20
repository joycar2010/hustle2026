<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">Risk Control</h1>

    <!-- Emergency Stop -->
    <div class="card mb-6">
      <div class="flex justify-between items-center">
        <div>
          <h2 class="text-xl font-bold mb-2">Emergency Stop</h2>
          <p class="text-sm text-gray-400">Immediately halt all trading activities</p>
        </div>
        <button
          @click="toggleEmergencyStop"
          :class="['px-6 py-3 rounded font-bold', emergencyStopActive ? 'bg-red-500 hover:bg-red-600' : 'bg-gray-600 hover:bg-gray-700']"
        >
          {{ emergencyStopActive ? 'STOP ACTIVE' : 'Activate Emergency Stop' }}
        </button>
      </div>
    </div>

    <!-- Risk Metrics -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">Account Risk Ratio</div>
        <div class="text-2xl font-bold">{{ riskMetrics.accountRisk }}%</div>
        <div class="text-xs" :class="riskMetrics.accountRisk > 80 ? 'text-red-500' : 'text-green-500'">
          {{ riskMetrics.accountRisk > 80 ? 'High Risk' : 'Normal' }}
        </div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">MT5 Status</div>
        <div class="text-2xl font-bold">{{ riskMetrics.mt5Status }}</div>
        <div class="text-xs text-gray-400">Connection status</div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">Active Alerts</div>
        <div class="text-2xl font-bold text-red-500">{{ riskMetrics.activeAlerts }}</div>
        <div class="text-xs text-gray-400">Requires attention</div>
      </div>
    </div>

    <!-- Risk Alerts -->
    <div class="card">
      <h2 class="text-xl font-bold mb-4">Risk Alerts</h2>
      <div class="space-y-3">
        <div v-for="alert in alerts" :key="alert.id" class="bg-dark-200 rounded p-4">
          <div class="flex justify-between items-start">
            <div>
              <div class="flex items-center space-x-2 mb-1">
                <span :class="['px-2 py-1 rounded text-xs', getAlertClass(alert.level)]">
                  {{ alert.level }}
                </span>
                <span class="font-bold">{{ alert.title }}</span>
              </div>
              <p class="text-sm text-gray-400">{{ alert.message }}</p>
              <p class="text-xs text-gray-500 mt-1">{{ formatTime(alert.time) }}</p>
            </div>
            <button @click="dismissAlert(alert.id)" class="text-gray-400 hover:text-white">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div v-if="!alerts.length" class="text-center text-gray-400 py-8">
          No active alerts
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import dayjs from 'dayjs'
import api from '@/services/api'

const emergencyStopActive = ref(false)
const riskMetrics = ref({
  accountRisk: 45,
  mt5Status: 'Normal',
  activeAlerts: 0
})
const alerts = ref([])

onMounted(() => {
  fetchRiskData()
  setInterval(fetchRiskData, 5000)
})

async function fetchRiskData() {
  try {
    const response = await api.get('/api/v1/risk/status')
    emergencyStopActive.value = response.data.emergency_stop_active
    // Fetch other risk data
  } catch (error) {
    console.error('Failed to fetch risk data:', error)
  }
}

async function toggleEmergencyStop() {
  try {
    const endpoint = emergencyStopActive.value ? 'deactivate' : 'activate'
    await api.post(`/api/v1/risk/emergency-stop/${endpoint}`)
    await fetchRiskData()
  } catch (error) {
    console.error('Failed to toggle emergency stop:', error)
  }
}

async function dismissAlert(id) {
  alerts.value = alerts.value.filter(a => a.id !== id)
}

function getAlertClass(level) {
  const classes = {
    critical: 'bg-red-500/20 text-red-400',
    warning: 'bg-yellow-500/20 text-yellow-400',
    info: 'bg-blue-500/20 text-blue-400'
  }
  return classes[level] || 'bg-gray-500/20 text-gray-400'
}

function formatTime(time) {
  return dayjs(time).format('MM-DD HH:mm:ss')
}
</script>
