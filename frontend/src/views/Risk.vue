<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- Header -->
    <div class="px-2 py-1.5 border-b border-[#2b3139] flex-shrink-0">
      <h1 class="text-sm font-bold">风险控制</h1>
    </div>

    <!-- Scrollable Content -->
    <div class="flex-1 overflow-y-auto px-2 lg:px-1.5 py-1.5 lg:py-1 space-y-1.5 lg:space-y-1">
      <!-- Emergency Stop -->
      <div class="card p-1.5 lg:p-1">
        <div class="flex items-center justify-between">
          <h2 class="text-xs lg:text-[10px] font-bold">紧急停止</h2>
          <button
            @click="toggleEmergencyStop"
            :class="['px-2 lg:px-1.5 py-1 lg:py-0.5 rounded text-xs lg:text-[10px] font-bold', emergencyStopActive ? 'bg-red-500 hover:bg-red-600' : 'bg-gray-600 hover:bg-gray-700']"
          >
            {{ emergencyStopActive ? '停止激活' : '激活紧急停止' }}
          </button>
        </div>
      </div>

      <!-- Risk Metrics -->
      <div class="card p-1.5 lg:p-1">
        <div class="grid grid-cols-3 gap-2 lg:gap-1">
          <div class="flex flex-col items-center">
            <div class="text-[10px] lg:text-[9px] text-gray-400 mb-0.5">账户风险比率</div>
            <div class="text-base lg:text-sm font-bold">{{ riskMetrics.accountRisk }}%</div>
            <div class="text-[10px] lg:text-[9px]" :class="riskMetrics.accountRisk > 80 ? 'text-red-500' : 'text-green-500'">
              {{ riskMetrics.accountRisk > 80 ? '高风险' : '正常' }}
            </div>
          </div>
          <div class="flex flex-col items-center">
            <div class="text-[10px] lg:text-[9px] text-gray-400 mb-0.5">MT5状态</div>
            <div class="text-base lg:text-sm font-bold">{{ riskMetrics.mt5Status }}</div>
            <div class="text-[10px] lg:text-[9px] text-gray-400">连接状态</div>
          </div>
          <div class="flex flex-col items-center">
            <div class="text-[10px] lg:text-[9px] text-gray-400 mb-0.5">活动警报</div>
            <div class="text-base lg:text-sm font-bold text-red-500">{{ riskMetrics.activeAlerts }}</div>
            <div class="text-[10px] lg:text-[9px] text-gray-400">需要注意</div>
          </div>
        </div>
      </div>

      <!-- Alert Settings -->
      <div class="card p-1.5 lg:p-1">
        <!-- Account Net Asset Alerts -->
        <div class="mb-2 lg:mb-1">
          <h3 class="text-xs lg:text-[10px] font-semibold mb-2 lg:mb-1 text-primary">净资产提醒</h3>
          <div class="grid grid-cols-3 gap-2 lg:gap-1">
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">Binance 净资</label>
              <input
                type="number"
                v-model.number="alertSettings.binanceNetAsset"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">Bybit 净资</label>
              <input
                type="number"
                v-model.number="alertSettings.bybitMT5NetAsset"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">总资产</label>
              <input
                type="number"
                v-model.number="alertSettings.totalNetAsset"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
          </div>
        </div>

        <!-- Liquidation Price and MT5 Lag Alerts -->
        <div class="mb-2 lg:mb-1 border-t border-gray-700 pt-1.5 lg:pt-1">
          <h3 class="text-xs lg:text-[10px] font-semibold mb-2 lg:mb-1 text-primary">爆仓价位提醒</h3>
          <div class="grid grid-cols-3 gap-2 lg:gap-1">
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">安爆价(%)</label>
              <input
                type="number"
                v-model.number="alertSettings.binanceLiquidationDistance"
                step="1"
                min="1"
                max="50"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="默认10%"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">MT5爆价(%)</label>
              <input
                type="number"
                v-model.number="alertSettings.bybitMT5LiquidationDistance"
                step="1"
                min="1"
                max="50"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="默认10%"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">MT5卡顿</label>
              <input
                type="number"
                v-model.number="alertSettings.mt5LagCount"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入卡顿次数"
              />
            </div>
          </div>
        </div>

        <!-- Reverse Arbitrage Alerts (Long Bybit) -->
        <div class="mb-2 lg:mb-1 border-t border-gray-700 pt-1.5 lg:pt-1">
          <h3 class="text-xs lg:text-[10px] font-semibold mb-2 lg:mb-1 text-primary">反向提醒</h3>
          <div class="grid grid-cols-4 gap-2 lg:gap-1">
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">反开差</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseOpenPrice"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">反开步</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseOpenSyncCount"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">反平差</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseClosePrice"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">反平步</label>
              <input
                type="number"
                v-model.number="alertSettings.reverseCloseSyncCount"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
          </div>
        </div>

        <!-- Forward Arbitrage Alerts (Long Binance) -->
        <div class="mb-2 lg:mb-1 border-t border-gray-700 pt-1.5 lg:pt-1">
          <h3 class="text-xs lg:text-[10px] font-semibold mb-2 lg:mb-1 text-primary">正向提醒</h3>
          <div class="grid grid-cols-4 gap-2 lg:gap-1">
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">正开差</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardOpenPrice"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">正开步</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardOpenSyncCount"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">正平差</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardClosePrice"
                step="0.01"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入提醒值"
              />
            </div>
            <div>
              <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">正平步</label>
              <input
                type="number"
                v-model.number="alertSettings.forwardCloseSyncCount"
                class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入条数"
              />
            </div>
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveAlertSettings"
          class="w-full px-4 lg:px-3 py-2 lg:py-1.5 bg-primary hover:bg-primary-dark rounded text-sm lg:text-xs font-semibold"
        >
          保存设置
        </button>
      </div>

      <!-- Emergency Manual Trading -->
      <div class="card p-1.5 lg:p-1">
        <div class="flex items-center justify-between mb-2 lg:mb-1">
          <h2 class="text-xs lg:text-[10px] font-bold">紧急手动交易</h2>
          <div class="flex items-center gap-1">
            <div class="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
            <span class="text-[10px] lg:text-[9px] font-bold text-red-500">紧急模式</span>
          </div>
        </div>

        <div class="space-y-2 lg:space-y-1">
          <!-- Exchange Selection -->
          <div>
            <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">交易平台</label>
            <select v-model="manualTrading.exchange" class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
              <option value="binance">Binance (XAUUSDT)</option>
              <option value="bybit">Bybit MT5 (XAUUSD.s)</option>
            </select>
          </div>

          <!-- Quantity -->
          <div>
            <label class="block text-[10px] lg:text-[9px] mb-1 lg:mb-0.5">下单总手数 (XAU)</label>
            <input
              v-model.number="manualTrading.quantity"
              type="number"
              step="1"
              min="1"
              class="w-full px-2 lg:px-1.5 py-1 lg:py-0.5 text-xs lg:text-[10px] bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="1"
            />
            <div class="text-[9px] lg:text-[8px] text-gray-400 mt-0.5">
              Bybit 实际下单量: {{ xauToLot(manualTrading.quantity).toFixed(2) }} Lot
            </div>
          </div>

          <!-- Action Buttons -->
          <div class="grid grid-cols-2 gap-2 lg:gap-1">
            <button
              @click="executeTrade('buy')"
              :disabled="manualTrading.loading"
              class="px-2 py-1.5 lg:py-1 bg-green-500 hover:bg-green-600 disabled:opacity-50 rounded text-xs lg:text-[10px] font-bold"
            >
              买入开多
            </button>
            <button
              @click="executeTrade('sell')"
              :disabled="manualTrading.loading"
              class="px-2 py-1.5 lg:py-1 bg-red-500 hover:bg-red-600 disabled:opacity-50 rounded text-xs lg:text-[10px] font-bold"
            >
              卖出开空
            </button>
          </div>

          <!-- Status message -->
          <div v-if="manualTrading.statusMsg" :class="['text-[10px] lg:text-[9px] px-2 py-1 rounded', manualTrading.statusOk ? 'text-green-500 bg-green-500/10' : 'text-red-500 bg-red-500/10']">
            {{ manualTrading.statusMsg }}
          </div>

          <!-- Quick Actions -->
          <div class="pt-2 lg:pt-1 border-t border-gray-700 grid grid-cols-2 gap-2 lg:gap-1">
            <button
              @click.stop="closeAllPositions"
              :disabled="manualTrading.loading"
              class="px-2 py-1.5 lg:py-1 bg-red-500 hover:bg-red-600 disabled:opacity-50 rounded text-xs lg:text-[10px] font-bold"
            >
              ⚠️ 平仓所有持仓
            </button>
            <button
              @click.stop="cancelAllOrders"
              :disabled="manualTrading.loading"
              class="px-2 py-1.5 lg:py-1 bg-gray-600 hover:bg-gray-700 disabled:opacity-50 rounded text-xs lg:text-[10px] font-bold"
            >
              取消所有挂单
            </button>
          </div>
        </div>
      </div>

      <!-- Recent Trading Records -->
      <div class="card p-1.5 lg:p-1">
        <div class="flex items-center justify-between mb-2 lg:mb-1">
          <h2 class="text-xs lg:text-[10px] font-bold">最近交易记录</h2>
          <button @click="viewMoreOrders" class="text-[10px] lg:text-[9px] text-primary hover:text-primary-dark">
            查看更多 →
          </button>
        </div>

        <div class="space-y-1">
          <div v-if="recentOrders.length === 0" class="text-center py-4 text-[10px] lg:text-[9px] text-gray-400">
            暂无记录
          </div>

          <div
            v-for="order in recentOrders"
            :key="order.id"
            class="flex items-center justify-between bg-dark-100 rounded px-2 py-1.5 lg:py-1 text-[10px] lg:text-[9px]"
          >
            <div class="flex items-center gap-2 lg:gap-1">
              <span class="text-gray-400">{{ formatOrderTime(order.timestamp) }}</span>
              <span class="text-gray-400">{{ order.exchange }}</span>
              <span :class="['font-bold', order.side === 'buy' ? 'text-green-500' : 'text-red-500']">
                {{ order.side === 'buy' ? '买' : '卖' }}
              </span>
            </div>
            <div class="flex items-center gap-2 lg:gap-1">
              <span class="font-mono">{{ order.quantity }}</span>
              <span :class="['text-[9px] lg:text-[8px] px-1.5 py-0.5 rounded', getOrderStatusClass(order.status)]">
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
import { xauToLot, convertForPlatform } from '@/composables/useQuantityConverter'
import { formatTimeBeijing } from '@/utils/timeUtils'

const router = useRouter()
const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const emergencyStopActive = ref(false)
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

// Manual Trading
const manualTrading = ref({
  exchange: 'binance',
  quantity: 1,
  loading: false,
  statusMsg: '',
  statusOk: true
})

// Recent Orders
const recentOrders = ref([])

onMounted(async () => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  await fetchRiskData()
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
  } else if (message && message.type === 'risk_metrics') {
    updateRiskMetrics(message.data)
  } else if (message && message.type === 'order_update') {
    handleOrderUpdate(message.data)
  }
})

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

// Manual Trading Functions
function showTradeStatus(msg, ok = true) {
  manualTrading.value.statusMsg = msg
  manualTrading.value.statusOk = ok
  setTimeout(() => { manualTrading.value.statusMsg = '' }, 4000)
}

async function executeTrade(side) {
  if (manualTrading.value.loading) return
  manualTrading.value.loading = true
  try {
    const actualQuantity = convertForPlatform(manualTrading.value.quantity, manualTrading.value.exchange)

    await api.post('/api/v1/trading/manual/order', {
      exchange: manualTrading.value.exchange,
      side,
      quantity: actualQuantity,
    })
    showTradeStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送`, true)
    await fetchRecentOrders()
  } catch (e) {
    showTradeStatus(e.response?.data?.detail || '下单失败', false)
  } finally {
    manualTrading.value.loading = false
  }
}

async function closeAllPositions() {
  console.log('[DEBUG] closeAllPositions called')
  console.log('[DEBUG] manualTrading.loading:', manualTrading.value.loading)

  if (!confirm('确定要平仓所有持仓吗？')) {
    console.log('[DEBUG] User cancelled confirmation')
    return
  }

  if (manualTrading.value.loading) {
    console.log('[DEBUG] Already loading, skipping')
    return
  }

  manualTrading.value.loading = true
  console.log('[DEBUG] Starting close all positions request')

  try {
    const res = await api.post('/api/v1/trading/manual/close-all')
    console.log('[DEBUG] Close all positions response:', res.data)
    showTradeStatus(`平仓指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    await fetchRecentOrders()
  } catch (e) {
    console.error('[DEBUG] Close all positions error:', e)
    showTradeStatus(e.response?.data?.detail || '平仓失败', false)
  } finally {
    manualTrading.value.loading = false
    console.log('[DEBUG] Close all positions completed')
  }
}

async function cancelAllOrders() {
  if (!confirm('确定要取消所有挂单吗？')) return
  if (manualTrading.value.loading) return
  manualTrading.value.loading = true
  try {
    const res = await api.post('/api/v1/trading/manual/cancel-all')
    showTradeStatus(`撤单指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    await fetchRecentOrders()
  } catch (e) {
    showTradeStatus(e.response?.data?.detail || '撤单失败', false)
  } finally {
    manualTrading.value.loading = false
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
