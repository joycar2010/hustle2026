<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="p-2 md:p-3 border-b border-[#2b3139] flex-shrink-0">
      <h3 :class="['text-base md:text-lg font-bold', type === 'forward' ? 'text-[#FF2433]' : 'text-[#00C98B]']">
        {{ type === 'forward' ? '正向套利策略' : '反向套利策略' }}
      </h3>
    </div>

    <div class="flex-1 overflow-y-auto p-2 md:p-3 space-y-2 min-h-0">
      <!-- Validation Errors Display -->
      <div v-if="validationErrors.length > 0" class="bg-[#f6465d] bg-opacity-10 border border-[#f6465d] rounded p-3">
        <div class="flex items-start space-x-2">
          <span class="text-[#f6465d] text-lg">⚠</span>
          <div class="flex-1">
            <div class="text-sm font-bold text-[#f6465d] mb-1">配置验证失败</div>
            <ul class="text-xs text-[#f6465d] space-y-1">
              <li v-for="(error, index) in validationErrors" :key="index">• {{ error }}</li>
            </ul>
          </div>
          <button @click="validationErrors = []" class="text-[#f6465d] hover:text-white transition-colors">
            <span class="text-lg">×</span>
          </button>
        </div>
      </div>

      <!-- Position Summary -->
      <div v-if="positionSummary" class="bg-[#252930] rounded p-2 md:p-3">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-bold">持仓统计</span>
          <button
            @click="refreshPositions"
            class="px-2 py-1 text-xs bg-[#2b3139] hover:bg-[#3b4149] rounded transition-colors"
          >
            刷新
          </button>
        </div>
        <div class="grid grid-cols-3 gap-2 md:gap-3 text-xs">
          <div>
            <div class="text-gray-400 mb-1">当前持仓</div>
            <div class="font-mono font-bold text-[#0ecb81]">
              {{ positionSummary.total_current_position.toFixed(2) }}
            </div>
          </div>
          <div>
            <div class="text-gray-400 mb-1">累计开仓</div>
            <div class="font-mono font-bold">
              {{ positionSummary.total_opened.toFixed(2) }}
            </div>
          </div>
          <div>
            <div class="text-gray-400 mb-1">累计平仓</div>
            <div class="font-mono font-bold">
              {{ positionSummary.total_closed.toFixed(2) }}
            </div>
          </div>
        </div>
      </div>

      <!-- Top Info Bar -->
      <div class="bg-[#252930] rounded p-2 md:p-3">
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 md:gap-3">
          <!-- Binance Available Assets -->
          <div>
            <div class="text-xs text-gray-400 mb-1">Binance可用资产</div>
            <div class="text-base font-mono font-bold">
              {{ formatNumber(binanceAssets) }} USDT
            </div>
          </div>

          <!-- Bybit MT5 Available Assets -->
          <div>
            <div class="text-xs text-gray-400 mb-1">Bybit MT5可用资产</div>
            <div class="text-base font-mono font-bold">
              {{ formatNumber(bybitAssets) }} USDT
            </div>
          </div>

          <!-- Spread Display -->
          <div class="text-center">
            <div class="text-xs text-gray-400 mb-1 whitespace-nowrap">
              {{ type === 'reverse' ? '做多Bybit点差' : '做多Binance点差' }}
            </div>
            <div :class="['text-xl font-mono font-bold whitespace-nowrap', type === 'reverse' ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
              {{ currentSpread.toFixed(2) }} / {{ closingSpread.toFixed(2) }}
            </div>
          </div>
        </div>
      </div>

      <!-- Configuration Area -->
      <div class="bg-[#252930] rounded p-3 space-y-3">
        <div class="text-xs font-bold mb-2">策略配置</div>

        <!-- M Coin Settings -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label :for="`openingMCoin-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正向开仓单次下单手数' : '反向开仓单次下单手数' }} (XAU)
              <span class="text-[#0ecb81] ml-1">≈ {{ (config.openingMCoin / 100).toFixed(2) }} Lot</span>
            </label>
            <input
              :id="`openingMCoin-${type}`"
              v-model.number="config.openingMCoin"
              type="number"
              step="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`closingMCoin-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正向平仓单次下单手数' : '反向平仓单次下单手数' }} (XAU)
              <span class="text-[#0ecb81] ml-1">≈ {{ (config.closingMCoin / 100).toFixed(2) }} Lot</span>
            </label>
            <input
              :id="`closingMCoin-${type}`"
              v-model.number="config.closingMCoin"
              type="number"
              step="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>
        </div>

        <!-- Opening/Closing Position Toggles -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-400 mb-1 block">开仓控制</label>
            <button
              @click="toggleOpening"
              :disabled="executing"
              :class="[
                'w-full px-3 py-2 rounded text-xs font-bold transition-all',
                executing ? 'bg-gray-600 text-gray-400 cursor-not-allowed' :
                config.openingEnabled
                  ? 'bg-[#F1C40F] text-white'
                  : 'bg-[#00C98B] text-white'
              ]"
            >
              {{ executing ? '执行中...' : (config.openingEnabled ? '停用开仓' : (type === 'forward' ? '启用正向开仓' : '启用反向开仓')) }}
            </button>
            <!-- Trigger Progress for Opening -->
            <div v-if="config.openingEnabled" class="mt-2 text-xs">
              <div class="flex justify-between text-gray-400 mb-1">
                <span>触发进度</span>
                <span>{{ triggerCount.opening }} / {{ config.openingSyncQty }}</span>
              </div>
              <div class="w-full bg-[#1a1d21] rounded-full h-2">
                <div
                  class="bg-[#0ecb81] h-2 rounded-full transition-all duration-300"
                  :style="{ width: `${Math.min(100, (triggerCount.opening / config.openingSyncQty) * 100)}%` }"
                ></div>
              </div>
            </div>
          </div>

          <div>
            <label class="text-xs text-gray-400 mb-1 block">平仓控制</label>
            <button
              @click="toggleClosing"
              :disabled="executing"
              :class="[
                'w-full px-3 py-2 rounded text-xs font-bold transition-all',
                executing ? 'bg-gray-600 text-gray-400 cursor-not-allowed' :
                config.closingEnabled
                  ? 'bg-[#F1C40F] text-white'
                  : 'bg-[#00C98B] text-white'
              ]"
            >
              {{ executing ? '执行中...' : (config.closingEnabled ? '停用平仓' : (type === 'forward' ? '启用正向平仓' : '启用反向平仓')) }}
            </button>
            <!-- Trigger Progress for Closing -->
            <div v-if="config.closingEnabled" class="mt-2 text-xs">
              <div class="flex justify-between text-gray-400 mb-1">
                <span>触发进度</span>
                <span>{{ triggerCount.closing }} / {{ config.closingSyncQty }}</span>
              </div>
              <div class="w-full bg-[#1a1d21] rounded-full h-2">
                <div
                  class="bg-[#f6465d] h-2 rounded-full transition-all duration-300"
                  :style="{ width: `${Math.min(100, (triggerCount.closing / config.closingSyncQty) * 100)}%` }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Data Sync Quantities -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label :for="`openingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正向开仓触发次数' : '反向开仓触发次数' }}
            </label>
            <input
              :id="`openingSyncQty-${type}`"
              v-model.number="config.openingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`closingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正向平仓触发次数' : '反向平仓触发次数' }}
            </label>
            <input
              :id="`closingSyncQty-${type}`"
              v-model.number="config.closingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveConfig"
          class="w-full px-4 py-2 bg-[#f0b90b] text-[#1a1d21] rounded font-bold hover:bg-[#e0a800] transition-colors"
        >
          保存配置
        </button>
      </div>

      <!-- Ladder Configuration -->
      <div class="bg-[#252930] rounded p-3">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs font-bold">阶梯配置（最多5级）</span>
          <button
            @click="addLadder"
            :disabled="config.ladders.length >= 5"
            :class="[
              'px-3 py-1 rounded text-xs font-bold transition-colors',
              config.ladders.length >= 5
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-[#f0b90b] text-[#1a1d21] hover:bg-[#e0a800]'
            ]"
          >
            + 添加阶梯
          </button>
        </div>

        <div class="space-y-2">
          <div
            v-for="(ladder, index) in config.ladders"
            :key="index"
            class="bg-[#1a1d21] rounded p-2"
          >
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs text-gray-400">阶梯 {{ index + 1 }}</span>
              <div class="flex items-center space-x-2">
                <label :for="`ladder-enabled-${type}-${index}`" class="flex items-center space-x-1 cursor-pointer">
                  <input
                    :id="`ladder-enabled-${type}-${index}`"
                    v-model="ladder.enabled"
                    type="checkbox"
                    class="w-4 h-4 rounded border-[#2b3139] bg-[#252930] text-[#0ecb81] focus:ring-[#0ecb81]"
                  />
                  <span class="text-xs">启用</span>
                </label>
                <button
                  @click="removeLadder(index)"
                  class="px-2 py-1 bg-[#f6465d] text-white rounded text-xs hover:bg-[#e03d52] transition-colors"
                >
                  删除
                </button>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-2">
              <div>
                <label :for="`openPrice-${type}-${index}`" class="text-xs text-gray-400 mb-1 block">
                  {{ type === 'forward' ? '正向开仓点差值' : '反向开仓点差值' }}
                </label>
                <input
                  :id="`openPrice-${type}-${index}`"
                  v-model.number="ladder.openPrice"
                  type="number"
                  step="0.01"
                  :placeholder="(0).toFixed(2)"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label :for="`threshold-${type}-${index}`" class="text-xs text-gray-400 mb-1 block">
                  {{ type === 'forward' ? '正向平仓点差值' : '反向平仓点差值' }}
                </label>
                <input
                  :id="`threshold-${type}-${index}`"
                  v-model.number="ladder.threshold"
                  type="number"
                  step="0.01"
                  :placeholder="(0).toFixed(2)"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label :for="`qtyLimit-${type}-${index}`" class="text-xs text-gray-400 mb-1 block">
                  {{ type === 'forward' ? '正向下单总手数' : '反向下单总手数' }} (XAU)
                  <span class="text-[#0ecb81] ml-1">≈ {{ (ladder.qtyLimit / 100).toFixed(2) }} Lot</span>
                </label>
                <input
                  :id="`qtyLimit-${type}-${index}`"
                  v-model.number="ladder.qtyLimit"
                  type="number"
                  step="1"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Save Strategy Button -->
        <button
          @click="saveStrategy"
          class="w-full mt-3 px-4 py-2 bg-[#f0b90b] text-[#1a1d21] rounded font-bold hover:bg-[#e0a800] transition-colors"
        >
          保存策略
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'
import { calculateAllSpreads } from '@/composables/useSpreadCalculator'

const props = defineProps({
  type: {
    type: String,
    required: true,
    validator: (value) => ['forward', 'reverse'].includes(value)
  }
})

const marketStore = useMarketStore()
const currentSpread = ref(0)
const closingSpread = ref(0)
const binanceAssets = ref(10000)
const bybitAssets = ref(8500)
const executing = ref(false)
const accountsData = ref(null)
const orderPlaced = ref({ opening: false, closing: false })
const triggerCount = ref({ opening: 0, closing: 0 })

const config = ref({
  openingMCoin: 5,
  closingMCoin: 5,
  openingEnabled: false,
  closingEnabled: false,
  openingSyncQty: 3,
  closingSyncQty: 3,
  ladders: [
    { enabled: true, openPrice: 3.00, threshold: 2.00, qtyLimit: 3 },
    { enabled: true, openPrice: 3.00, threshold: 3.00, qtyLimit: 3 },
    { enabled: false, openPrice: 3.00, threshold: 4.00, qtyLimit: 3 },
  ]
})

const configId = ref(null)
const validationErrors = ref([])
const positionSummary = ref(null)
let positionRefreshInterval = null

// 阶梯执行进度跟踪
const ladderProgress = ref({
  opening: {
    currentLadderIndex: 0,  // 当前执行的阶梯索引
    completedQty: 0         // 当前阶梯已完成数量
  },
  closing: {
    currentLadderIndex: 0,
    completedQty: 0
  }
})

onMounted(async () => {
  config.value.openingEnabled = false
  config.value.closingEnabled = false

  // Load config from database
  await loadConfigFromDB()

  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Initial account data fetch
  await fetchAccountData()

  // Initial position data fetch
  await refreshPositions()

  // Setup auto-refresh for position data based on system settings
  setupPositionRefresh()
})

async function loadConfigFromDB() {
  try {
    const response = await api.get(`/api/v1/strategies/configs/by-type/${props.type}`)
    const data = response.data
    configId.value = data.config_id
    config.value.openingMCoin = data.opening_m_coin || data.m_coin || 5
    config.value.closingMCoin = data.closing_m_coin || data.m_coin || 5
    config.value.openingSyncQty = data.opening_sync_count
    config.value.closingSyncQty = data.closing_sync_count
    if (data.ladders && data.ladders.length > 0) {
      config.value.ladders = data.ladders
    }
  } catch (error) {
    if (error.response?.status !== 404) {
      console.error('Failed to load config from DB:', error)
    }
    // 404 means no config yet, use defaults
  }
}

onUnmounted(() => {
  // Cleanup position refresh interval
  if (positionRefreshInterval) {
    clearInterval(positionRefreshInterval)
  }
  // No cleanup needed for WebSocket - stays connected for other components
})

// Watch for market data updates via WebSocket
watch(() => marketStore.marketData, (newData) => {
  if (!newData) return

  // 使用统一的点差计算器
  const spreads = calculateAllSpreads(newData)

  // Update spread based on strategy type
  if (props.type === 'forward') {
    currentSpread.value = spreads.forwardOpening  // 正向开仓点差
    closingSpread.value = spreads.forwardClosing  // 正向平仓点差
  } else {
    currentSpread.value = spreads.reverseOpening  // 反向开仓点差
    closingSpread.value = spreads.reverseClosing  // 反向平仓点差
  }

  // binance做多值: forward=binance_bid, reverse=binance_ask
  const binanceLongValue = props.type === 'forward' ? newData.binance_bid : newData.binance_ask

  // Trigger count logic for opening
  if (config.value.openingEnabled && !executing.value && !orderPlaced.value.opening) {
    const enabledLadders = config.value.ladders.filter(l => l.enabled)
    const currentLadderIdx = ladderProgress.value.opening.currentLadderIndex

    // 只检查当前阶梯（严格顺序执行）
    if (currentLadderIdx < enabledLadders.length) {
      const currentLadder = enabledLadders[currentLadderIdx]

      // 检查是否满足触发条件
      if (currentSpread.value >= currentLadder.openPrice) {
        triggerCount.value.opening++
        console.log(`Opening trigger count: ${triggerCount.value.opening}/${config.value.openingSyncQty}, currentSpread=${currentSpread.value}, openPrice=${currentLadder.openPrice}, ladder=${currentLadderIdx + 1}`)

        if (triggerCount.value.opening >= config.value.openingSyncQty) {
          // 执行当前阶梯
          executeLadderOpening(currentLadderIdx, currentLadder)
          triggerCount.value.opening = 0
        }
      } else {
        triggerCount.value.opening = 0
      }
    }
  }

  // Trigger count logic for closing
  if (config.value.closingEnabled && !executing.value && !orderPlaced.value.closing) {
    const enabledLadders = config.value.ladders.filter(l => l.enabled)
    const currentLadderIdx = ladderProgress.value.closing.currentLadderIndex

    // 只检查当前阶梯（严格顺序执行）
    if (currentLadderIdx < enabledLadders.length) {
      const currentLadder = enabledLadders[currentLadderIdx]

      // 检查是否满足触发条件
      if (closingSpread.value <= currentLadder.threshold) {
        triggerCount.value.closing++
        console.log(`Closing trigger count: ${triggerCount.value.closing}/${config.value.closingSyncQty}, closingSpread=${closingSpread.value}, threshold=${currentLadder.threshold}, ladder=${currentLadderIdx + 1}`)

        if (triggerCount.value.closing >= config.value.closingSyncQty) {
          // 执行当前阶梯
          executeLadderClosing(currentLadderIdx, currentLadder)
          triggerCount.value.closing = 0
        }
      } else {
        triggerCount.value.closing = 0
      }
    }
  }
})

// Watch for account balance updates via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
})

function handleAccountBalanceUpdate(data) {
  // Update available assets from WebSocket data
  if (data.accounts && data.accounts.length > 0) {
    const binanceAccounts = data.accounts.filter(acc => acc.platform_id === 1) || []
    const bybitAccounts = data.accounts.filter(acc => acc.platform_id === 2) || []

    binanceAssets.value = binanceAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
    bybitAssets.value = bybitAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
  }
}

async function fetchAccountData() {
  try {
    const accountResponse = await api.get('/api/v1/accounts/dashboard/aggregated')
    const accountData = accountResponse.data

    accountsData.value = accountData

    const binanceAccounts = accountData.accounts?.filter(acc => acc.platform_id === 1) || []
    const bybitAccounts = accountData.accounts?.filter(acc => acc.platform_id === 2) || []

    binanceAssets.value = binanceAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
    bybitAssets.value = bybitAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

async function refreshPositions() {
  if (!configId.value) return

  try {
    const response = await api.get(`/api/v1/strategies/positions/${configId.value}`)
    positionSummary.value = response.data.summary
  } catch (error) {
    console.error('Failed to fetch positions:', error)
    // Don't show error to user, just log it
  }
}

function addLadder() {
  if (config.value.ladders.length < 5) {
    config.value.ladders.push({
      enabled: true,
      openPrice: 3.00,
      threshold: 0.00,
      qtyLimit: 3
    })
  }
}

function removeLadder(index) {
  config.value.ladders.splice(index, 1)
}

async function saveConfig() {
  try {
    const configData = {
      strategy_type: props.type,
      target_spread: 1.0,
      order_qty: 1.0,
      retry_times: 3,
      mt5_stuck_threshold: 5,
      opening_sync_count: Math.floor(config.value.openingSyncQty),
      closing_sync_count: Math.floor(config.value.closingSyncQty),
      opening_m_coin: Number(config.value.openingMCoin),
      closing_m_coin: Number(config.value.closingMCoin),
      ladders: config.value.ladders.map(l => ({
        enabled: l.enabled,
        openPrice: Number(Number(l.openPrice).toFixed(2)),
        threshold: Number(Number(l.threshold).toFixed(2)),
        qtyLimit: Number(l.qtyLimit)
      })),
      is_enabled: config.value.openingEnabled || config.value.closingEnabled
    }

    const response = await api.post('/api/v1/strategies/configs/upsert', configData)
    configId.value = response.data.config_id
    alert('配置保存成功！')
  } catch (error) {
    console.error('Failed to save config:', error)
    let errorMessage = '未知错误'
    if (error.response?.data?.detail) {
      if (Array.isArray(error.response.data.detail)) {
        errorMessage = error.response.data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ')
      } else if (typeof error.response.data.detail === 'string') {
        errorMessage = error.response.data.detail
      } else {
        errorMessage = JSON.stringify(error.response.data.detail)
      }
    } else if (error.message) {
      errorMessage = error.message
    }
    alert(`配置保存失败: ${errorMessage}`)
  }
}

async function saveStrategy() {
  await saveConfig()
}

function validateAccountsForExecution() {
  console.log('validateAccountsForExecution called')
  console.log('accountsData.value:', accountsData.value)

  if (!accountsData.value) {
    console.log('Account data not loaded')
    return { valid: false, message: '账户数据未加载，请稍后再试' }
  }

  const accounts = accountsData.value.accounts || []
  console.log('accounts:', accounts)

  // Find Binance and Bybit MT5 accounts
  const binanceAccount = accounts.find(acc => acc.platform_id === 1)
  const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)
  console.log('binanceAccount:', binanceAccount)
  console.log('bybitMT5Account:', bybitMT5Account)

  // Check if accounts exist
  if (!binanceAccount) {
    return { valid: false, message: 'Binance账户不存在，请先添加账户' }
  }

  if (!bybitMT5Account) {
    return { valid: false, message: 'Bybit MT5账户不存在，请先添加账户' }
  }

  // Check disconnected state from localStorage
  const STORAGE_KEY = 'disconnectedAccounts'
  let disconnectedAccounts = new Set()
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      disconnectedAccounts = new Set(JSON.parse(saved))
    }
  } catch (e) {
    console.error('Failed to load disconnected accounts:', e)
  }

  // Check if accounts are disconnected
  if (disconnectedAccounts.has(binanceAccount.account_id)) {
    return { valid: false, message: 'Binance账户已断开连接，请先连接账户' }
  }

  if (disconnectedAccounts.has(bybitMT5Account.account_id)) {
    return { valid: false, message: 'Bybit MT5账户已断开连接，请先连接账户' }
  }

  // Check if both accounts are active
  if (!binanceAccount.is_active) {
    return { valid: false, message: 'Binance账户未激活，请先激活账户' }
  }

  if (!bybitMT5Account.is_active) {
    return { valid: false, message: 'Bybit MT5账户未激活，请先激活账户' }
  }

  // Check if accounts have errors
  if (binanceAccount.error) {
    return { valid: false, message: `Binance账户连接失败: ${binanceAccount.error}` }
  }

  if (bybitMT5Account.error) {
    return { valid: false, message: `Bybit MT5账户连接失败: ${bybitMT5Account.error}` }
  }

  // Check if balances are not zero
  const binanceBalance = binanceAccount.balance?.available_balance || 0
  const bybitBalance = bybitMT5Account.balance?.available_balance || 0

  if (binanceBalance <= 0) {
    return { valid: false, message: 'Binance合约账户余额为0，无法启用策略' }
  }

  if (bybitBalance <= 0) {
    return { valid: false, message: 'Bybit MT5账户余额为0，无法启用策略' }
  }

  // Check for single-leg mode (if the field exists)
  if (binanceAccount.single_leg_mode) {
    return { valid: false, message: 'Binance账户处于单腿模式，无法启用策略' }
  }

  if (bybitMT5Account.single_leg_mode) {
    return { valid: false, message: 'Bybit MT5账户处于单腿模式，无法启用策略' }
  }

  return { valid: true }
}

async function waitForOrderFill(orderIds, maxWaitTime = 10000) {
  if (!orderIds || orderIds.length === 0) {
    console.log('No order IDs to monitor')
    return
  }

  const startTime = Date.now()
  const pollInterval = 2000 // Poll every 2 seconds

  console.log(`Monitoring orders: ${orderIds.join(', ')}`)

  while (Date.now() - startTime < maxWaitTime) {
    try {
      // Fetch current orders
      const response = await api.get('/api/v1/orders')
      const orders = response.data.orders || []

      // Check if all orders are filled
      const allFilled = orderIds.every(orderId => {
        const order = orders.find(o => o.order_id === orderId)
        if (!order) return false
        return order.status === 'filled'
      })

      if (allFilled) {
        console.log('All orders filled')
        return
      }

      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, pollInterval))
    } catch (error) {
      console.error('Error monitoring orders:', error)
      // Continue polling even if there's an error
      await new Promise(resolve => setTimeout(resolve, pollInterval))
    }
  }

  console.warn('Order monitoring timeout - proceeding anyway')
}

function toggleOpening() {
  if (config.value.openingEnabled) {
    config.value.openingEnabled = false
    triggerCount.value.opening = 0
    validationErrors.value = []
  } else {
    // Clear previous errors
    validationErrors.value = []

    // Validate accounts
    const accountValidation = validateAccountsForExecution()
    if (!accountValidation.valid) {
      validationErrors.value = [accountValidation.message]
      return
    }

    // Validate ladder configuration
    const configValidation = validateLadderConfig('opening')
    if (!configValidation.valid) {
      validationErrors.value = configValidation.errors
      return
    }

    config.value.openingEnabled = true
    orderPlaced.value.opening = false
    triggerCount.value.opening = 0
    // closingEnabled is NOT touched — independent control
  }
}

async function toggleClosing() {
  if (config.value.closingEnabled) {
    config.value.closingEnabled = false
    triggerCount.value.closing = 0
    validationErrors.value = []
  } else {
    // Clear previous errors
    validationErrors.value = []

    // Validate accounts
    const accountValidation = validateAccountsForExecution()
    if (!accountValidation.valid) {
      validationErrors.value = [accountValidation.message]
      return
    }

    // Validate ladder configuration
    const configValidation = validateLadderConfig('closing')
    if (!configValidation.valid) {
      validationErrors.value = configValidation.errors
      return
    }

    // Check position sufficiency
    const positionCheck = await checkPositionForClosing()
    if (!positionCheck.valid) {
      validationErrors.value = [positionCheck.message]
      return
    }

    config.value.closingEnabled = true
    orderPlaced.value.closing = false
    triggerCount.value.closing = 0
    // openingEnabled is NOT touched — independent control
  }
}

async function executeLadderOpening(ladderIndex, ladder) {
  if (executing.value) return

  try {
    executing.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      alert('无法找到账户信息，请刷新页面重试')
      config.value.openingEnabled = false
      return
    }

    const remainingQty = ladder.qtyLimit - ladderProgress.value.opening.completedQty
    const mCoin = config.value.openingMCoin
    const batchQty = Math.min(mCoin, remainingQty)

    console.log(`Executing ladder ${ladderIndex + 1} opening: batch=${batchQty}, remaining=${remainingQty}, total=${ladder.qtyLimit}`)

    const executionData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      quantity: batchQty,
      ladder_index: ladderIndex,
      target_spread: ladder.threshold
    }

    try {
      const response = await api.post(`/api/v1/strategies/execute/${props.type}`, executionData)

      if (response.data.success) {
        console.log(`Ladder ${ladderIndex + 1} batch executed successfully`)

        // 更新阶梯进度
        ladderProgress.value.opening.completedQty += batchQty

        // 检查当前阶梯是否完成
        if (ladderProgress.value.opening.completedQty >= ladder.qtyLimit) {
          console.log(`Ladder ${ladderIndex + 1} completed, moving to next ladder`)

          // 移动到下一个阶梯
          ladderProgress.value.opening.currentLadderIndex++
          ladderProgress.value.opening.completedQty = 0

          // 检查是否所有阶梯都完成
          const enabledLadders = config.value.ladders.filter(l => l.enabled)
          if (ladderProgress.value.opening.currentLadderIndex >= enabledLadders.length) {
            // 所有阶梯完成，停止策略
            console.log('All ladders completed, stopping opening strategy')
            config.value.openingEnabled = false
            ladderProgress.value.opening.currentLadderIndex = 0
            alert('所有阶梯开仓完成')
          }
        }

        // 刷新持仓数据
        await refreshPositions()
      } else {
        const errorMsg = response.data.error || response.data.detail || response.data.message || '未知错误'
        console.error(`Ladder ${ladderIndex + 1} execution failed:`, errorMsg)
        alert(`阶梯 ${ladderIndex + 1} 执行失败: ${errorMsg}`)
        config.value.openingEnabled = false
      }
    } catch (error) {
      console.error(`Ladder ${ladderIndex + 1} execution error:`, error)
      const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
      alert(`阶梯 ${ladderIndex + 1} 执行异常: ${errorMsg}`)
      config.value.openingEnabled = false
    }
  } finally {
    executing.value = false
  }
}

async function executeLadderClosing(ladderIndex, ladder) {
  if (executing.value) return

  try {
    executing.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      alert('无法找到账户信息，请刷新页面重试')
      config.value.closingEnabled = false
      return
    }

    const remainingQty = ladder.qtyLimit - ladderProgress.value.closing.completedQty
    const mCoin = config.value.closingMCoin
    const batchQty = Math.min(mCoin, remainingQty)

    console.log(`Executing ladder ${ladderIndex + 1} closing: batch=${batchQty}, remaining=${remainingQty}, total=${ladder.qtyLimit}`)

    const executionData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      quantity: batchQty,
      ladder_index: ladderIndex
    }

    try {
      const response = await api.post(`/api/v1/strategies/close/${props.type}`, executionData)

      if (response.data.success) {
        console.log(`Ladder ${ladderIndex + 1} batch closed successfully`)

        // 更新阶梯进度
        ladderProgress.value.closing.completedQty += batchQty

        // 检查当前阶梯是否完成
        if (ladderProgress.value.closing.completedQty >= ladder.qtyLimit) {
          console.log(`Ladder ${ladderIndex + 1} closing completed, moving to next ladder`)

          // 移动到下一个阶梯
          ladderProgress.value.closing.currentLadderIndex++
          ladderProgress.value.closing.completedQty = 0

          // 检查是否所有阶梯都完成
          const enabledLadders = config.value.ladders.filter(l => l.enabled)
          if (ladderProgress.value.closing.currentLadderIndex >= enabledLadders.length) {
            // 所有阶梯完成，停止策略
            console.log('All ladders closing completed, stopping closing strategy')
            config.value.closingEnabled = false
            ladderProgress.value.closing.currentLadderIndex = 0
            alert('所有阶梯平仓完成')
          }
        }

        // 刷新持仓数据
        await refreshPositions()
      } else {
        const errorMsg = response.data.error || response.data.detail || response.data.message || '未知错误'
        console.error(`Ladder ${ladderIndex + 1} closing failed:`, errorMsg)
        alert(`阶梯 ${ladderIndex + 1} 平仓失败: ${errorMsg}`)
        config.value.closingEnabled = false
      }
    } catch (error) {
      console.error(`Ladder ${ladderIndex + 1} closing error:`, error)
      const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
      alert(`阶梯 ${ladderIndex + 1} 平仓异常: ${errorMsg}`)
      config.value.closingEnabled = false
    }
  } finally {
    executing.value = false
  }
}

async function executeBatchOpening(ladder) {
  if (executing.value) return

  try {
    executing.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      alert('无法找到账户信息，请刷新页面重试')
      config.value.openingEnabled = false
      return
    }

    const totalQuantity = ladder.qtyLimit
    const mCoin = config.value.openingMCoin
    const numBatches = Math.ceil(totalQuantity / mCoin)
    let remainingQuantity = totalQuantity

    console.log(`Starting batch opening: total=${totalQuantity}, mCoin=${mCoin}, batches=${numBatches}`)

    for (let i = 0; i < numBatches; i++) {
      const batchQuantity = Math.min(mCoin, remainingQuantity)
      console.log(`Batch ${i + 1}/${numBatches}: executing ${batchQuantity} units`)

      const executionData = {
        binance_account_id: binanceAccount.account_id,
        bybit_account_id: bybitMT5Account.account_id,
        quantity: batchQuantity,
        target_spread: ladder.threshold
      }

      try {
        const response = await api.post(`/api/v1/strategies/execute/${props.type}`, executionData)

        if (response.data.success) {
          console.log(`Batch ${i + 1} executed successfully`)
          remainingQuantity -= batchQuantity

          // Wait for order to be filled before next batch
          if (i < numBatches - 1) {
            await waitForOrderFill(response.data.order_ids)
          }
        } else {
          // Extract error message from various possible fields
          const executionResult = response.data.execution_result || {}
          // binance_result and bybit_result are nested inside execution_result
          const binanceResult = executionResult.binance_result || response.data.binance_result || {}
          const bybitResult = executionResult.bybit_result || response.data.bybit_result || {}

          const errorMsg = response.data.error
            || response.data.detail
            || response.data.message
            || executionResult.error
            || executionResult.message
            || JSON.stringify(executionResult)
            || '未知错误'

          console.error(`Batch ${i + 1} failed:`, errorMsg)
          console.error('Full response:', response.data)
          console.error('Execution result:', executionResult)
          console.error('Binance result:', binanceResult)
          console.error('Bybit result:', bybitResult)

          // Build detailed error message
          let detailedError = errorMsg
          if (binanceResult.error || bybitResult.error) {
            detailedError += '\n详细信息:'
            if (binanceResult.error) detailedError += `\nBinance: ${binanceResult.error}`
            if (bybitResult.error) detailedError += `\nBybit: ${bybitResult.error}`
          }

          alert(`批次 ${i + 1} 执行失败: ${detailedError}`)
          break
        }
      } catch (error) {
        console.error(`Batch ${i + 1} error:`, error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
        console.error('Full error:', error.response?.data)
        alert(`批次 ${i + 1} 执行异常: ${errorMsg}`)
        break
      }
    }

    // Mark as completed and disable
    orderPlaced.value.opening = true
    config.value.openingEnabled = false
    console.log('Batch opening completed')
  } catch (error) {
    console.error('Failed to execute batch opening:', error)
  } finally {
    executing.value = false
  }
}

async function executeBatchClosing(ladder) {
  if (executing.value) return

  try {
    executing.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      alert('无法找到账户信息，请刷新页面重试')
      config.value.closingEnabled = false
      return
    }

    const totalQuantity = ladder.qtyLimit
    const mCoin = config.value.closingMCoin
    const numBatches = Math.ceil(totalQuantity / mCoin)
    let remainingQuantity = totalQuantity

    console.log(`Starting batch closing: total=${totalQuantity}, mCoin=${mCoin}, batches=${numBatches}`)

    for (let i = 0; i < numBatches; i++) {
      const batchQuantity = Math.min(mCoin, remainingQuantity)
      console.log(`Batch ${i + 1}/${numBatches}: executing ${batchQuantity} units`)

      const executionData = {
        binance_account_id: binanceAccount.account_id,
        bybit_account_id: bybitMT5Account.account_id,
        quantity: batchQuantity
      }

      try {
        const response = await api.post(`/api/v1/strategies/close/${props.type}`, executionData)

        if (response.data.success) {
          console.log(`Batch ${i + 1} executed successfully`)
          remainingQuantity -= batchQuantity

          // Wait for order to be filled before next batch
          if (i < numBatches - 1) {
            await waitForOrderFill(response.data.order_ids)
          }
        } else {
          // Extract error message from various possible fields
          const executionResult = response.data.execution_result || {}
          // binance_result and bybit_result are nested inside execution_result
          const binanceResult = executionResult.binance_result || response.data.binance_result || {}
          const bybitResult = executionResult.bybit_result || response.data.bybit_result || {}

          const errorMsg = response.data.error
            || response.data.detail
            || response.data.message
            || executionResult.error
            || executionResult.message
            || JSON.stringify(executionResult)
            || '未知错误'

          console.error(`Batch ${i + 1} failed:`, errorMsg)
          console.error('Full response:', response.data)
          console.error('Execution result:', executionResult)
          console.error('Binance result:', binanceResult)
          console.error('Bybit result:', bybitResult)

          // Build detailed error message
          let detailedError = errorMsg
          if (binanceResult.error || bybitResult.error) {
            detailedError += '\n详细信息:'
            if (binanceResult.error) detailedError += `\nBinance: ${binanceResult.error}`
            if (bybitResult.error) detailedError += `\nBybit: ${bybitResult.error}`
          }

          alert(`批次 ${i + 1} 执行失败: ${detailedError}`)
          break
        }
      } catch (error) {
        console.error(`Batch ${i + 1} error:`, error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
        console.error('Full error:', error.response?.data)
        alert(`批次 ${i + 1} 执行异常: ${errorMsg}`)
        break
      }
    }

    // Mark as completed and disable
    orderPlaced.value.closing = true
    config.value.closingEnabled = false
    console.log('Batch closing completed')
  } catch (error) {
    console.error('Failed to execute batch closing:', error)
  } finally {
    executing.value = false
  }
}

async function checkPositionForClosing() {
  try {
    // Get current positions
    const response = await api.get('/api/v1/positions')
    const positions = response.data.positions || []

    // Calculate total required quantity from enabled ladders
    const enabledLadders = config.value.ladders.filter(l => l.enabled)
    const totalRequiredQty = enabledLadders.reduce((sum, ladder) => sum + (ladder.qtyLimit || 0), 0)

    // Find positions for the current strategy type
    // For reverse: Bybit long position (platform_id=2, side='BUY')
    // For forward: Binance long position (platform_id=1, side='BUY')
    const platformId = props.type === 'reverse' ? 2 : 1
    const relevantPositions = positions.filter(p =>
      p.platform_id === platformId &&
      p.symbol === 'XAUUSD' &&
      p.quantity > 0
    )

    const currentPosition = relevantPositions.reduce((sum, p) => sum + (p.quantity || 0), 0)

    if (currentPosition < totalRequiredQty) {
      return {
        valid: false,
        message: `持仓不足:\n当前持仓: ${currentPosition.toFixed(2)}\n需要平仓: ${totalRequiredQty.toFixed(2)}\n差额: ${(totalRequiredQty - currentPosition).toFixed(2)}\n\n请调整阶梯配置或等待持仓增加`
      }
    }

    return { valid: true }
  } catch (error) {
    console.error('Failed to check position:', error)
    return {
      valid: false,
      message: '无法获取持仓信息，请稍后再试'
    }
  }
}

function validateLadderConfig(action) {
  const errors = []

  // Check if there are enabled ladders
  const enabledLadders = config.value.ladders.filter(l => l.enabled)
  if (enabledLadders.length === 0) {
    errors.push('至少需要启用一个阶梯')
    return { valid: false, errors }
  }

  // Check each enabled ladder
  enabledLadders.forEach((ladder) => {
    const ladderNum = config.value.ladders.indexOf(ladder) + 1

    if (action === 'opening') {
      // Check opening spread value
      if (!ladder.openPrice || ladder.openPrice <= 0) {
        errors.push(`阶梯${ladderNum}: 开仓点差值必须大于0`)
      }

      // Check opening trigger count (config level)
      if (!config.value.openingSyncQty || config.value.openingSyncQty < 1) {
        errors.push(`开仓触发次数必须至少为1`)
      }

      // Check opening m_coin
      if (!config.value.openingMCoin || config.value.openingMCoin <= 0) {
        errors.push(`开仓单次下单手数必须大于0`)
      }

      // Check m_coin doesn't exceed total quantity
      if (config.value.openingMCoin > ladder.qtyLimit) {
        errors.push(`阶梯${ladderNum}: 开仓单次下单手数(${config.value.openingMCoin})不能超过总手数(${ladder.qtyLimit})`)
      }
    } else if (action === 'closing') {
      // Check closing spread value
      if (ladder.threshold === undefined || ladder.threshold === null) {
        errors.push(`阶梯${ladderNum}: 平仓点差值未配置`)
      }

      // Check closing trigger count (config level)
      if (!config.value.closingSyncQty || config.value.closingSyncQty < 1) {
        errors.push(`平仓触发次数必须至少为1`)
      }

      // Check closing m_coin
      if (!config.value.closingMCoin || config.value.closingMCoin <= 0) {
        errors.push(`平仓单次下单手数必须大于0`)
      }

      // Check m_coin doesn't exceed total quantity
      if (config.value.closingMCoin > ladder.qtyLimit) {
        errors.push(`阶梯${ladderNum}: 平仓单次下单手数(${config.value.closingMCoin})不能超过总手数(${ladder.qtyLimit})`)
      }
    }

    // Check total quantity
    if (!ladder.qtyLimit || ladder.qtyLimit <= 0) {
      errors.push(`阶梯${ladderNum}: 总手数必须大于0`)
    }
  })

  return {
    valid: errors.length === 0,
    errors
  }
}

function formatNumber(num) {
  return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

function setupPositionRefresh() {
  // 从系统设置获取刷新间隔（默认30秒）
  const refreshInterval = 30000

  positionRefreshInterval = setInterval(async () => {
    await refreshPositions()
  }, refreshInterval)
}
</script>
