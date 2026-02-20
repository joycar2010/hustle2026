<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">风险控制</h1>

    <!-- Emergency Stop -->
    <div class="card mb-6">
      <div class="flex justify-between items-center">
        <div>
          <h2 class="text-xl font-bold mb-2">紧急停止</h2>
          <p class="text-sm text-gray-400">立即停止所有交易活动</p>
        </div>
        <button
          @click="toggleEmergencyStop"
          :class="['px-6 py-3 rounded font-bold', emergencyStopActive ? 'bg-red-500 hover:bg-red-600' : 'bg-gray-600 hover:bg-gray-700']"
        >
          {{ emergencyStopActive ? '停止激活' : '激活紧急停止' }}
        </button>
      </div>
    </div>

    <!-- Risk Metrics -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="card">
        <div class="text-sm text-gray-400 mb-1">账户风险比率</div>
        <div class="text-2xl font-bold">{{ riskMetrics.accountRisk }}%</div>
        <div class="text-xs" :class="riskMetrics.accountRisk > 80 ? 'text-red-500' : 'text-green-500'">
          {{ riskMetrics.accountRisk > 80 ? '高风险' : '正常' }}
        </div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">MT5状态</div>
        <div class="text-2xl font-bold">{{ riskMetrics.mt5Status }}</div>
        <div class="text-xs text-gray-400">连接状态</div>
      </div>

      <div class="card">
        <div class="text-sm text-gray-400 mb-1">活动警报</div>
        <div class="text-2xl font-bold text-red-500">{{ riskMetrics.activeAlerts }}</div>
        <div class="text-xs text-gray-400">需要注意</div>
      </div>
    </div>

    <!-- Alert Settings -->
    <div class="card mb-6">
      <h2 class="text-xl font-bold mb-4">警报设置</h2>

      <!-- Account Net Asset Alerts -->
      <div class="mb-6">
        <h3 class="text-lg font-semibold mb-3 text-primary">账户净资产提醒设置</h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label class="block text-sm mb-2">Binance 净资产提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.binanceNetAsset"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">Bybit MT5 净资产提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.bybitMT5NetAsset"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">总资产提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.totalNetAsset"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
        </div>
      </div>

      <!-- Liquidation Price Alerts -->
      <div class="mb-6 border-t border-gray-700 pt-6">
        <h3 class="text-lg font-semibold mb-3 text-primary">爆仓价位提醒设置</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm mb-2">Binance 爆仓价位提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.binanceLiquidationPrice"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">Bybit MT5 爆仓价位提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.bybitMT5LiquidationPrice"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
        </div>
      </div>

      <!-- MT5 Lag Count Setting -->
      <div class="mb-6 border-t border-gray-700 pt-6">
        <h3 class="text-lg font-semibold mb-3 text-primary">MT5卡顿次数设置</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm mb-2">MT5卡顿次数提醒值</label>
            <input
              type="number"
              v-model.number="alertSettings.mt5LagCount"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入卡顿次数"
            />
          </div>
        </div>
      </div>

      <!-- Reverse Arbitrage Alerts (Long Bybit) -->
      <div class="mb-6 border-t border-gray-700 pt-6">
        <h3 class="text-lg font-semibold mb-3 text-primary">反向套利（做多Bybit）提醒</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm mb-2">开仓价提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.reverseOpenPrice"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">持续开仓点差记录数据同步条数</label>
            <input
              type="number"
              v-model.number="alertSettings.reverseOpenSyncCount"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入条数"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">平仓价提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.reverseClosePrice"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">持续平仓点差记录数据同步条数</label>
            <input
              type="number"
              v-model.number="alertSettings.reverseCloseSyncCount"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入条数"
            />
          </div>
        </div>
      </div>

      <!-- Forward Arbitrage Alerts (Long Binance) -->
      <div class="mb-6 border-t border-gray-700 pt-6">
        <h3 class="text-lg font-semibold mb-3 text-primary">正向套利（做多Binance）提醒</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm mb-2">开仓价提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.forwardOpenPrice"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">持续开仓点差记录数据同步条数</label>
            <input
              type="number"
              v-model.number="alertSettings.forwardOpenSyncCount"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入条数"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">平仓价提醒值 (USDT)</label>
            <input
              type="number"
              v-model.number="alertSettings.forwardClosePrice"
              step="0.01"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入提醒值"
            />
          </div>
          <div>
            <label class="block text-sm mb-2">持续平仓点差记录数据同步条数</label>
            <input
              type="number"
              v-model.number="alertSettings.forwardCloseSyncCount"
              class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入条数"
            />
          </div>
        </div>
      </div>

      <!-- Save Button -->
      <div class="flex justify-end">
        <button
          @click="saveAlertSettings"
          class="px-6 py-2 bg-primary hover:bg-primary-dark rounded font-semibold"
        >
          保存设置
        </button>
      </div>
    </div>

    <!-- Risk Alerts -->
    <div class="card">
      <h2 class="text-xl font-bold mb-4">风险警报</h2>
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
          无活动警报
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
  mt5Status: '正常',
  activeAlerts: 0
})
const alerts = ref([])

// Alert Settings
const alertSettings = ref({
  // Account Net Asset Alerts
  binanceNetAsset: 10000,
  bybitMT5NetAsset: 10000,
  totalNetAsset: 20000,
  // Liquidation Price Alerts
  binanceLiquidationPrice: 2000,
  bybitMT5LiquidationPrice: 2000,
  // MT5 Lag Count
  mt5LagCount: 5,
  // Reverse Arbitrage (Long Bybit)
  reverseOpenPrice: 0.5,
  reverseOpenSyncCount: 3,
  reverseClosePrice: 0.2,
  reverseCloseSyncCount: 3,
  // Forward Arbitrage (Long Binance)
  forwardOpenPrice: 0.5,
  forwardOpenSyncCount: 3,
  forwardClosePrice: 0.2,
  forwardCloseSyncCount: 3
})

onMounted(() => {
  fetchRiskData()
  fetchAlertSettings()
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

async function fetchAlertSettings() {
  try {
    const response = await api.get('/api/v1/risk/alert-settings')
    if (response.data) {
      alertSettings.value = { ...alertSettings.value, ...response.data }
    }
  } catch (error) {
    console.error('Failed to fetch alert settings:', error)
  }
}

async function saveAlertSettings() {
  try {
    await api.post('/api/v1/risk/alert-settings', alertSettings.value)
    alert('警报设置保存成功！')
  } catch (error) {
    console.error('Failed to save alert settings:', error)
    alert('警报设置保存失败')
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
