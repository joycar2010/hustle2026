<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- Header -->
    <div class="px-3 py-3 border-b border-[#2b3139] flex-shrink-0">
      <h1 class="text-lg font-bold">风险控制</h1>
    </div>

    <!-- Scrollable Content -->
    <div class="flex-1 overflow-y-auto px-3 py-3 space-y-3">
      <!-- Emergency Stop -->
      <div class="card p-3">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-bold">紧急停止</h2>
          <button
            @click="toggleEmergencyStop"
            :class="['px-4 py-2 rounded text-sm font-bold', emergencyStopActive ? 'bg-red-500 hover:bg-red-600' : 'bg-gray-600 hover:bg-gray-700']"
          >
            {{ emergencyStopActive ? '停止激活' : '激活紧急停止' }}
          </button>
        </div>
      </div>

      <!-- Risk Metrics -->
      <div class="space-y-2">
        <div class="card p-2">
          <div class="flex items-center justify-between">
            <div class="text-[10px] text-gray-400">账户风险比率</div>
            <div class="flex items-center space-x-2">
              <div class="text-base font-bold">{{ riskMetrics.accountRisk }}%</div>
              <div class="text-[10px]" :class="riskMetrics.accountRisk > 80 ? 'text-red-500' : 'text-green-500'">
                {{ riskMetrics.accountRisk > 80 ? '高风险' : '正常' }}
              </div>
            </div>
          </div>
        </div>

        <div class="card p-2">
          <div class="flex items-center justify-between">
            <div class="text-[10px] text-gray-400">MT5状态</div>
            <div class="flex items-center space-x-2">
              <div class="text-base font-bold">{{ riskMetrics.mt5Status }}</div>
              <div class="text-[10px] text-gray-400">连接状态</div>
            </div>
          </div>
        </div>

        <div class="card p-2">
          <div class="flex items-center justify-between">
            <div class="text-[10px] text-gray-400">活动警报</div>
            <div class="flex items-center space-x-2">
              <div class="text-base font-bold text-red-500">{{ riskMetrics.activeAlerts }}</div>
              <div class="text-[10px] text-gray-400">需要注意</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Alert Settings -->
      <div class="card p-3">
        <!-- Account Net Asset Alerts -->
        <div class="mb-4">
          <h3 class="text-xs font-semibold mb-2 text-primary">净资产提醒</h3>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] mb-1">Binance 净资</label>
              <input
                type="number"
                v-model.number="alertSettings.binanceNetAsset"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">Bybit 净资</label>
              <input
                type="number"
                v-model.number="alertSettings.bybitMT5NetAsset"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div class="col-span-2">
              <label class="block text-[10px] mb-1">总资产</label>
              <input
                type="number"
                v-model.number="alertSettings.totalNetAsset"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
          </div>
        </div>

        <!-- Liquidation Price Alerts -->
        <div class="mb-4 border-t border-gray-700 pt-3">
          <h3 class="text-xs font-semibold mb-2 text-primary">爆仓价位提醒</h3>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] mb-1">Binance 爆仓价</label>
              <input
                type="number"
                v-model.number="alertSettings.binanceLiquidationPrice"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">Bybit 爆仓价</label>
              <input
                type="number"
                v-model.number="alertSettings.bybitMT5LiquidationPrice"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
          </div>
        </div>

        <!-- MT5 Lag Count Setting -->
        <div class="mb-4 border-t border-gray-700 pt-3">
          <h3 class="text-xs font-semibold mb-2 text-primary">MT5卡顿</h3>
          <div>
            <label class="block text-[10px] mb-1">MT5卡</label>
            <input
              type="number"
              v-model.number="alertSettings.mt5LagCount"
              class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入卡顿次数"
            />
          </div>
        </div>

        <!-- Reverse Arbitrage Alerts (Long Bybit) -->
        <div class="mb-4 border-t border-gray-700 pt-3">
          <h3 class="text-xs font-semibold mb-2 text-primary">反向提醒</h3>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] mb-1">反向开仓点差值</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseOpenPrice"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">反向开仓同步</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseOpenSyncCount"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">反向平仓点差值</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseClosePrice"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">反向平仓同步</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseCloseSyncCount"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
          </div>
        </div>

        <!-- Forward Arbitrage Alerts (Long Binance) -->
        <div class="mb-4 border-t border-gray-700 pt-3">
          <h3 class="text-xs font-semibold mb-2 text-primary">正向提醒</h3>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] mb-1">正向开仓点差值</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardOpenPrice"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">正向开仓同步</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardOpenSyncCount"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">正向平仓点差值</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardClosePrice"
                step="0.01"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] mb-1">正向平仓同步</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardCloseSyncCount"
                class="w-full px-2 py-1 text-xs bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveAlertSettings"
          class="w-full px-4 py-2 bg-primary hover:bg-primary-dark rounded text-sm font-semibold"
        >
          保存设置
        </button>
      </div>

      <!-- Risk Alerts -->
      <div class="card p-3">
        <h2 class="text-sm font-bold mb-3">风险警报</h2>
        <div class="space-y-2">
          <div v-for="alert in alerts" :key="alert.id" class="bg-dark-200 rounded p-2">
            <div class="flex justify-between items-start gap-2">
              <div class="flex-1 min-w-0">
                <div class="flex items-center space-x-1 mb-1">
                  <span :class="['px-1.5 py-0.5 rounded text-xs', getAlertClass(alert.level)]">
                    {{ alert.level }}
                  </span>
                  <span class="font-bold text-xs truncate">{{ alert.title }}</span>
                </div>
                <p class="text-xs text-gray-400 break-words">{{ alert.message }}</p>
                <p class="text-xs text-gray-500 mt-1">{{ formatTime(alert.time) }}</p>
              </div>
              <button @click="dismissAlert(alert.id)" class="text-gray-400 hover:text-white flex-shrink-0">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          <div v-if="!alerts.length" class="text-center text-gray-400 py-6 text-xs">
            无活动警报
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import dayjs from 'dayjs'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
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

onMounted(async () => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  await fetchRiskData()
  await fetchAlertSettings()

  // Reduced polling frequency (30s instead of 5s)
  setInterval(fetchRiskData, 30000)
})

// Watch for risk alerts via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'risk_alert') {
    handleRiskAlert(message.data)
  } else if (message && message.type === 'risk_metrics') {
    updateRiskMetrics(message.data)
  }
})

function handleRiskAlert(alertData) {
  // Add new alert to the list
  alerts.value = [
    {
      id: Date.now(),
      level: alertData.level || 'warning',
      message: alertData.message,
      time: alertData.timestamp || new Date().toISOString()
    },
    ...alerts.value
  ].slice(0, 10) // Keep only last 10 alerts
}

function updateRiskMetrics(data) {
  if (data.emergency_stop_active !== undefined) {
    emergencyStopActive.value = data.emergency_stop_active
  }
}

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
