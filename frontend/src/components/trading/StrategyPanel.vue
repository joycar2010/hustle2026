<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="p-3 border-b border-[#2b3139]">
      <h3 :class="['text-lg font-bold', type === 'forward' ? 'text-[#FF2433]' : 'text-[#00C98B]']">
        {{ type === 'forward' ? '正向套利策略' : '反向套利策略' }}
      </h3>
    </div>

    <div class="flex-1 overflow-y-auto p-3 space-y-3">
      <!-- Top Info Bar -->
      <div class="bg-[#252930] rounded p-3">
        <div class="grid grid-cols-3 gap-3">
          <!-- Spread Display -->
          <div class="text-center">
            <div class="text-xs text-gray-400 mb-1">
              {{ type === 'reverse' ? '做多Bybit点差' : '做多Binance点差' }}
            </div>
            <div :class="['text-2xl font-mono font-bold', type === 'reverse' ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
              {{ currentSpread.toFixed(2) }} USDT
            </div>
          </div>

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
        </div>
      </div>

      <!-- Configuration Area -->
      <div class="bg-[#252930] rounded p-3 space-y-3">
        <div class="text-xs font-bold mb-2">策略配置</div>

        <!-- M Coin Setting -->
        <div>
          <label class="text-xs text-gray-400 mb-1 block">M币设置</label>
          <input
            v-model.number="config.mCoin"
            type="number"
            step="1"
            class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
          />
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
          </div>
        </div>

        <!-- Data Sync Quantities -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-400 mb-1 block">开仓数据同步数量</label>
            <input
              v-model.number="config.openingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label class="text-xs text-gray-400 mb-1 block">平仓数据同步数量</label>
            <input
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
                <label class="flex items-center space-x-1 cursor-pointer">
                  <input
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
                <label class="text-xs text-gray-400 mb-1 block">开仓价</label>
                <input
                  v-model.number="ladder.openPrice"
                  type="number"
                  step="1"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label class="text-xs text-gray-400 mb-1 block">阈值</label>
                <input
                  v-model.number="ladder.threshold"
                  type="number"
                  step="0.1"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label class="text-xs text-gray-400 mb-1 block">下单数量限制</label>
                <input
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
import { ref, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const props = defineProps({
  type: {
    type: String,
    required: true,
    validator: (value) => ['forward', 'reverse'].includes(value)
  }
})

const marketStore = useMarketStore()
const currentSpread = ref(0)
const binanceAssets = ref(10000)
const bybitAssets = ref(8500)
const executing = ref(false)
const accountsData = ref(null)

const config = ref({
  mCoin: 100,
  openingEnabled: false,
  closingEnabled: false,
  openingSyncQty: 3,
  closingSyncQty: 3,
  ladders: [
    { enabled: true, openPrice: 3, threshold: 2.0, qtyLimit: 3 },
    { enabled: true, openPrice: 3, threshold: 3.0, qtyLimit: 3 },
    { enabled: false, openPrice: 3, threshold: 4.0, qtyLimit: 3 },
  ]
})

let updateInterval = null

onMounted(() => {
  // Explicitly reset enabled states to false on mount
  config.value.openingEnabled = false
  config.value.closingEnabled = false

  // Load saved strategy from localStorage
  const savedStrategy = localStorage.getItem(`strategy_${props.type}`)
  if (savedStrategy) {
    try {
      const strategyData = JSON.parse(savedStrategy)
      if (strategyData.ladders) {
        config.value.ladders = strategyData.ladders
      }
      if (strategyData.opening_sync_count) {
        config.value.openingSyncQty = strategyData.opening_sync_count
      }
      if (strategyData.closing_sync_count) {
        config.value.closingSyncQty = strategyData.closing_sync_count
      }
    } catch (error) {
      console.error('Failed to load saved strategy:', error)
    }
  }

  fetchStrategyData()
  updateInterval = setInterval(fetchStrategyData, 5000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchStrategyData() {
  try {
    // Fetch market data for spread calculation
    const data = await marketStore.fetchMarketData()

    if (data) {
      // Calculate spread based on strategy type
      // 做多Binance点差 (Forward, Green) = Bybit ASK - Binance BID
      // 做多Bybit点差 (Reverse, Red) = Binance ASK - Bybit BID
      if (props.type === 'forward') {
        // Forward strategy: 做多Binance
        currentSpread.value = data.bybit_ask - data.binance_bid
      } else {
        // Reverse strategy: 做多Bybit
        currentSpread.value = data.binance_ask - data.bybit_bid
      }
    }

    // Fetch real account asset data
    const accountResponse = await api.get('/api/v1/accounts/dashboard/aggregated')
    const accountData = accountResponse.data

    // Store account data for validation
    accountsData.value = accountData

    // Calculate available assets for each platform
    const binanceAccounts = accountData.accounts?.filter(acc => acc.platform_id === 1) || []
    const bybitAccounts = accountData.accounts?.filter(acc => acc.platform_id === 2) || []

    binanceAssets.value = binanceAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
    bybitAssets.value = bybitAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
  } catch (error) {
    console.error('Failed to fetch strategy data:', error)
  }
}

function addLadder() {
  if (config.value.ladders.length < 5) {
    config.value.ladders.push({
      enabled: true,
      openPrice: 3,
      threshold: 0,
      qtyLimit: 3
    })
  }
}

function removeLadder(index) {
  config.value.ladders.splice(index, 1)
}

async function saveConfig() {
  try {
    // Ensure sync quantities are integers
    const configData = {
      strategy_type: props.type,
      target_spread: 1.0, // Default value for ladder strategy
      order_qty: 1.0, // Default value for ladder strategy
      retry_times: 3,
      mt5_stuck_threshold: 5,
      opening_sync_count: Math.floor(config.value.openingSyncQty),
      closing_sync_count: Math.floor(config.value.closingSyncQty),
      is_enabled: config.value.openingEnabled || config.value.closingEnabled
    }

    const response = await api.post('/api/v1/strategies/configs', configData)
    alert('配置保存成功！')
  } catch (error) {
    console.error('Failed to save config:', error)
    let errorMessage = '未知错误'
    if (error.response?.data?.detail) {
      // Handle FastAPI validation errors
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

function saveStrategy() {
  try {
    // Ensure all ladder values are integers where needed
    const ladderData = config.value.ladders.map(ladder => ({
      enabled: ladder.enabled,
      openPrice: Math.floor(ladder.openPrice),
      threshold: ladder.threshold,
      qtyLimit: Math.floor(ladder.qtyLimit)
    }))

    const strategyData = {
      strategy_type: props.type,
      ladders: ladderData,
      opening_sync_count: Math.floor(config.value.openingSyncQty),
      closing_sync_count: Math.floor(config.value.closingSyncQty)
    }

    // Save to localStorage
    localStorage.setItem(`strategy_${props.type}`, JSON.stringify(strategyData))
    alert('策略保存成功！')
  } catch (error) {
    console.error('Failed to save strategy:', error)
    alert(`策略保存失败: ${error.message}`)
  }
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

async function toggleOpening() {
  console.log('toggleOpening called, current state:', config.value.openingEnabled)

  if (config.value.openingEnabled) {
    // If already enabled, just disable
    console.log('Disabling opening')
    config.value.openingEnabled = false
  } else {
    // If disabled, validate accounts first
    console.log('Validating accounts before enabling')
    const validation = validateAccountsForExecution()
    console.log('Validation result:', validation)

    if (!validation.valid) {
      alert(validation.message)
      return
    }
    // Then execute the opening strategy
    await executeOpening()
  }
}

async function toggleClosing() {
  console.log('toggleClosing called, current state:', config.value.closingEnabled)

  if (config.value.closingEnabled) {
    // If already enabled, just disable
    console.log('Disabling closing')
    config.value.closingEnabled = false
  } else {
    // If disabled, validate accounts first
    console.log('Validating accounts before enabling')
    const validation = validateAccountsForExecution()
    console.log('Validation result:', validation)

    if (!validation.valid) {
      alert(validation.message)
      return
    }
    // Then execute the closing strategy
    await executeClosing()
  }
}

async function executeOpening() {
  if (executing.value) return

  try {
    executing.value = true

    // Get enabled ladders
    const enabledLadders = config.value.ladders.filter(l => l.enabled)

    if (enabledLadders.length === 0) {
      alert('请至少启用一个阶梯配置')
      return
    }

    // Get account IDs from accountsData
    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      alert('无法找到账户信息，请刷新页面重试')
      return
    }

    // Use the first enabled ladder's values for the execution
    const firstLadder = enabledLadders[0]

    // Execute opening strategy
    const executionData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      quantity: firstLadder.qtyLimit,
      target_spread: firstLadder.threshold
    }

    const response = await api.post(`/api/v1/strategies/execute/${props.type}`, executionData)

    if (response.data.success) {
      config.value.openingEnabled = true
      alert(`${props.type === 'forward' ? '正向' : '反向'}开仓执行成功！`)
    } else {
      alert(`执行失败: ${response.data.error || '未知错误'}`)
    }
  } catch (error) {
    console.error('Failed to execute opening:', error)
    let errorMessage = '未知错误'
    if (error.response?.data?.detail) {
      if (typeof error.response.data.detail === 'string') {
        errorMessage = error.response.data.detail
      } else if (Array.isArray(error.response.data.detail)) {
        errorMessage = error.response.data.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ')
      } else {
        errorMessage = JSON.stringify(error.response.data.detail)
      }
    } else if (error.message) {
      errorMessage = error.message
    }
    alert(`执行失败: ${errorMessage}`)
  } finally {
    executing.value = false
  }
}

async function executeClosing() {
  if (executing.value) return

  try {
    executing.value = true

    // Get enabled ladders
    const enabledLadders = config.value.ladders.filter(l => l.enabled)

    if (enabledLadders.length === 0) {
      alert('请至少启用一个阶梯配置')
      return
    }

    // Get account IDs from accountsData
    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      alert('无法找到账户信息，请刷新页面重试')
      return
    }

    // Use the first enabled ladder's values for the execution
    const firstLadder = enabledLadders[0]

    // Execute closing strategy
    const executionData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      quantity: firstLadder.qtyLimit
    }

    const response = await api.post(`/api/v1/strategies/close/${props.type}`, executionData)

    if (response.data.success) {
      config.value.closingEnabled = true
      alert(`${props.type === 'forward' ? '正向' : '反向'}平仓执行成功！`)
    } else {
      alert(`执行失败: ${response.data.error || '未知错误'}`)
    }
  } catch (error) {
    console.error('Failed to execute closing:', error)
    let errorMessage = '未知错误'
    if (error.response?.data?.detail) {
      if (typeof error.response.data.detail === 'string') {
        errorMessage = error.response.data.detail
      } else if (Array.isArray(error.response.data.detail)) {
        errorMessage = error.response.data.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ')
      } else {
        errorMessage = JSON.stringify(error.response.data.detail)
      }
    } else if (error.message) {
      errorMessage = error.message
    }
    alert(`执行失败: ${errorMessage}`)
  } finally {
    executing.value = false
  }
}

function formatNumber(num) {
  return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
</script>
