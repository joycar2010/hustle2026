<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- Header -->
    <div class="px-2 py-1 border-b border-[#2b3139] flex-shrink-0">
      <h1 class="text-xs font-bold">风险控制</h1>
    </div>

    <!-- Content without scroll -->
    <div class="flex-1 overflow-hidden px-2 py-1 space-y-1">
      <!-- Risk Metrics -->
      <div class="card p-1">
        <div class="grid grid-cols-3 gap-1">
          <div class="flex flex-col items-center">
            <div class="text-[9px] text-gray-400 mb-0.5">账户风险比率</div>
            <div class="text-sm font-bold">{{ riskMetrics.accountRisk }}%</div>
            <div class="text-[9px]" :class="riskMetrics.accountRisk > 80 ? 'text-red-500' : 'text-green-500'">
              {{ riskMetrics.accountRisk > 80 ? '高风险' : '正常' }}
            </div>
          </div>
          <div class="flex flex-col items-center">
            <div class="text-[9px] text-gray-400 mb-0.5">MT5状态</div>
            <div class="text-sm font-bold">{{ riskMetrics.mt5Status }}</div>
            <div class="text-[9px] text-gray-400">连接状态</div>
          </div>
          <div class="flex flex-col items-center">
            <div class="text-[9px] text-gray-400 mb-0.5">活动警报</div>
            <div class="text-sm font-bold text-red-500">{{ riskMetrics.activeAlerts }}</div>
            <div class="text-[9px] text-gray-400">需要注意</div>
          </div>
        </div>
      </div>

      <!-- Emergency Manual Trading -->
      <EmergencyManualTrading />

      <!-- Alert Settings -->
      <div class="card p-1">
        <h2 class="text-[10px] font-bold mb-1">提醒设置</h2>

        <!-- Reverse Arbitrage Alerts -->
        <div class="mb-1">
          <h3 class="text-[10px] font-semibold mb-1 text-primary">反向提醒</h3>
          <div class="grid grid-cols-4 gap-1">
            <div>
              <label class="block text-[9px] mb-0.5">反开差</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseOpenPrice"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">反开步</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseOpenSyncCount"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="条数"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">反平差</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseClosePrice"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">反平步</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseCloseSyncCount"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="条数"
              />
            </div>
          </div>
        </div>

        <!-- Forward Arbitrage Alerts -->
        <div class="mb-1 border-t border-gray-700 pt-1">
          <h3 class="text-[10px] font-semibold mb-1 text-primary">正向提醒</h3>
          <div class="grid grid-cols-4 gap-1">
            <div>
              <label class="block text-[9px] mb-0.5">正开差</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardOpenPrice"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">正开步</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardOpenSyncCount"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="条数"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">正平差</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardClosePrice"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">正平步</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardCloseSyncCount"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="条数"
              />
            </div>
          </div>
        </div>

        <!-- Account Net Asset Alerts -->
        <div class="mb-1 border-t border-gray-700 pt-1">
          <h3 class="text-[10px] font-semibold mb-1 text-primary">净资产提醒</h3>
          <div class="grid grid-cols-3 gap-1">
            <div>
              <label class="block text-[9px] mb-0.5">Binance 净资</label>
              <input
                type="number"
                v-model.number="alertSettings.binanceNetAsset"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">Bybit 净资</label>
              <input
                type="number"
                v-model.number="alertSettings.bybitMT5NetAsset"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">总资产</label>
              <input
                type="number"
                v-model.number="alertSettings.totalNetAsset"
                step="0.01"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="提醒值"
              />
            </div>
          </div>
        </div>

        <!-- Liquidation Price and MT5 Lag Alerts -->
        <div class="mb-1 border-t border-gray-700 pt-1">
          <h3 class="text-[10px] font-semibold mb-1 text-primary">爆仓价位提醒</h3>
          <div class="grid grid-cols-3 gap-1">
            <div>
              <label class="block text-[9px] mb-0.5">安爆价(%)</label>
              <input
                type="number"
                v-model.number="alertSettings.binanceLiquidationDistance"
                step="1"
                min="1"
                max="50"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="默认10%"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">MT5爆价(%)</label>
              <input
                type="number"
                v-model.number="alertSettings.bybitMT5LiquidationDistance"
                step="1"
                min="1"
                max="50"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="默认10%"
              />
            </div>
            <div>
              <label class="block text-[9px] mb-0.5">MT5卡顿</label>
              <input
                type="number"
                v-model.number="alertSettings.mt5LagCount"
                class="w-full px-1.5 py-0.5 text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="卡顿次数"
              />
            </div>
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveAlertSettings"
          class="w-full px-3 py-1 bg-primary hover:bg-primary-dark rounded text-xs font-semibold mt-1"
        >
          保存设置
        </button>
      </div>

      <!-- Recent Trading Records -->
      <div class="card p-1">
        <div class="flex items-center justify-between mb-1">
          <h2 class="text-[10px] font-bold">最近交易记录</h2>
          <button @click="viewMoreOrders" class="text-[9px] text-primary hover:text-primary-dark">
            查看更多 →
          </button>
        </div>

        <div class="space-y-0.5">
          <div v-if="recentOrders.length === 0" class="text-center py-2 text-[9px] text-gray-400">
            暂无记录
          </div>

          <div
            v-for="order in recentOrders"
            :key="order.id"
            class="flex items-center justify-between bg-dark-100 rounded px-1.5 py-1 text-[9px]"
          >
            <div class="flex items-center gap-1">
              <span class="text-gray-400">{{ formatOrderTime(order.timestamp) }}</span>
              <span class="text-gray-400">{{ order.exchange }}</span>
              <span :class="['font-bold', order.side === 'buy' ? 'text-green-500' : 'text-red-500']">
                {{ order.side === 'buy' ? '买' : '卖' }}
              </span>
            </div>
            <div class="flex items-center gap-1">
              <span class="font-mono">{{ order.quantity }}</span>
              <span :class="['text-[8px] px-1 py-0.5 rounded', getOrderStatusClass(order.status)]">
                {{ getOrderStatusText(order.status) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'
import { formatTimeBeijing } from '@/utils/timeUtils'
import EmergencyManualTrading from '@/components/trading/EmergencyManualTrading.vue'

const router = useRouter()
const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const riskMetrics = ref({
  accountRisk: 45,
  mt5Status: '正常',
  activeAlerts: 0
})

// Alert Settings
const alertSettings = ref({
  // Account Net Asset Alerts
  binanceNetAsset: 10000,
  bybitMT5NetAsset: 10000,
  totalNetAsset: 20000,
  // Liquidation Price Distance Alerts (percentage)
  binanceLiquidationDistance: 10,
  bybitMT5LiquidationDistance: 10,
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

// Recent Orders
const recentOrders = ref([])

onMounted(async () => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  await fetchAlertSettings()
  await fetchRecentOrders()

  // Update active alerts count from notification store
  riskMetrics.value.activeAlerts = notificationStore.riskAlerts.length

  // Note: Removed 30s polling - now using WebSocket risk_metrics messages
  // Backend broadcasts risk_metrics every 30s via WebSocket
})

// Watch for risk alerts and metrics via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'risk_alert') {
    // Delegate to notification store
    notificationStore.handleRiskAlert(message.data)
    // Update active alerts count
    riskMetrics.value.activeAlerts = notificationStore.riskAlerts.length
  } else if (message && message.type === 'order_update') {
    handleOrderUpdate(message.data)
  }
})

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
    // Convert empty strings and undefined to null for all numeric fields
    const settingsToSave = {}
    for (const [key, value] of Object.entries(alertSettings.value)) {
      // If value is empty string, undefined, or NaN, set to null
      if (value === '' || value === undefined || (typeof value === 'number' && isNaN(value))) {
        settingsToSave[key] = null
      } else {
        settingsToSave[key] = value
      }
    }

    await api.post('/api/v1/risk/alert-settings', settingsToSave)
    alert('警报设置保存成功！空值字段将停止提醒。')
  } catch (error) {
    console.error('Failed to save alert settings:', error)
    alert('警报设置保存失败')
  }
}

// Recent Orders Functions
async function fetchRecentOrders() {
  try {
    const response = await api.get('/api/v1/trading/orders', {
      params: { limit: 3, source: 'manual' }
    })
    recentOrders.value = response.data
  } catch (e) {
    console.error('Failed to fetch recent orders:', e)
  }
}

function handleOrderUpdate(orderData) {
  // If it's a manual order, update the recent orders list
  if (orderData.source === 'manual') {
    const index = recentOrders.value.findIndex(o => o.id === orderData.id)
    if (index !== -1) {
      recentOrders.value[index] = { ...recentOrders.value[index], ...orderData }
    } else {
      // New order, add to top and keep only 3
      recentOrders.value = [orderData, ...recentOrders.value].slice(0, 3)
    }
  }
}

function viewMoreOrders() {
  router.push('/trading')
}

function formatOrderTime(timestamp) {
  return formatTimeBeijing(timestamp)
}

function getOrderStatusClass(status) {
  const classes = {
    new: 'text-yellow-500 bg-yellow-500/10',
    pending: 'text-yellow-500 bg-yellow-500/10',
    filled: 'text-green-500 bg-green-500/10',
    canceled: 'text-red-500 bg-red-500/10',
    cancelled: 'text-red-500 bg-red-500/10',
    manually_processed: 'text-blue-500 bg-blue-500/10',
  }
  return classes[status] || 'text-gray-400 bg-gray-400/10'
}

function getOrderStatusText(status) {
  const texts = {
    new: '挂单',
    pending: '挂单',
    filled: '成交',
    canceled: '取消',
    cancelled: '取消',
    manually_processed: '人工处理',
  }
  return texts[status] || status
}
</script>
