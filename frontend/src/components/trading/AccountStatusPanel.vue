<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <!-- Total Profit Header -->
    <div class="p-4 bg-[#252930] border-b border-[#2b3139]">
      <div class="text-xs text-gray-400 mb-1">当前用户总盈利</div>
      <div class="text-2xl font-bold font-mono" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
        {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }} USDT
      </div>
    </div>

    <div class="p-4 space-y-4">
      <!-- Dynamic Account Cards -->
      <div v-for="account in activeAccounts" :key="account.account_id" class="bg-[#252930] rounded-lg border border-[#2b3139]">
        <div class="p-3 border-b border-[#2b3139]">
          <div class="flex items-center justify-between">
            <div class="flex flex-col items-start space-y-3">
              <div class="flex items-center space-x-2">
                <div class="w-2 h-2 rounded-full" :class="account.error ? 'bg-[#f0b90b]' : (account.is_active ? 'bg-[#0ecb81]' : 'bg-[#f6465d]')"></div>
                <span class="text-base font-bold text-[#D4B106]">{{ account.account_name }}</span>
              </div>
              <span class="font-semibold text-sm">{{ getPlatformName(account.platform_id, account.is_mt5_account) }}</span>
              <span class="text-xs" :class="account.error ? 'text-[#f0b90b]' : 'text-gray-500'">
                {{ account.error ? '连接失败' : (account.is_active ? '已激活' : '未连接') }}
              </span>
            </div>
            <div class="flex space-x-1 self-center">
              <button
                @click="toggleConnection(account.account_id)"
                class="px-2 py-1 text-xs rounded transition-colors"
                :class="disconnectedAccounts.has(account.account_id) ? 'bg-[#0ecb81] hover:bg-[#0db774]' : 'bg-[#f6465d] hover:bg-[#e03d52]'"
              >
                {{ disconnectedAccounts.has(account.account_id) ? '连接' : '断开' }}
              </button>
              <button
                @click="toggleDisable(account.account_id)"
                class="px-2 py-1 text-xs rounded transition-colors"
                :class="disconnectedAccounts.has(account.account_id) ? 'bg-gray-600 hover:bg-gray-700' : 'bg-gray-500 opacity-50 cursor-not-allowed'"
                :disabled="!disconnectedAccounts.has(account.account_id)"
                :title="!disconnectedAccounts.has(account.account_id) ? '请先断开连接再禁用' : ''"
              >
                禁用
              </button>
            </div>
          </div>
          <!-- Error Message -->
          <div v-if="account.error" class="mt-2 text-xs text-[#f0b90b] bg-[#f0b90b]/10 rounded px-2 py-1">
            错误: {{ account.error }}
          </div>
        </div>

        <div class="p-3 space-y-1.5 text-xs">
          <div class="flex justify-between">
            <span class="text-gray-400">账户总资产</span>
            <span class="font-mono">{{ getDisplayValue(account, 'total_assets') }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">可用总资产</span>
            <span class="font-mono">{{ getDisplayValue(account, 'available_balance') }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">净资产</span>
            <span class="font-mono">{{ getDisplayValue(account, 'net_assets') }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">总持仓</span>
            <span class="font-mono">{{ getDisplayValue(account, 'total_positions') }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">冻结资产</span>
            <span class="font-mono">{{ getDisplayValue(account, 'frozen_assets') }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">当日盈亏</span>
            <span class="font-mono" :class="getValueColor(account, 'daily_pnl')">
              {{ getDisplayValue(account, 'daily_pnl', true) }}
            </span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">保证金余额</span>
            <span class="font-mono">{{ getDisplayValue(account, 'margin_balance') }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">风险率</span>
            <span class="font-mono" :class="getRiskColor(account.balance?.risk_ratio || 0)">
              {{ getDisplayValue(account, 'risk_ratio', false, true) }}
            </span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">{{ account.platform_id === 1 ? '掉期费(Binance)' : '资金费(Bybit)' }}</span>
            <span class="font-mono" :class="getValueColor(account, 'funding_fee')">
              {{ getDisplayValue(account, 'funding_fee', true) }}
            </span>
          </div>
        </div>
      </div>

      <!-- No Accounts Message -->
      <div v-if="activeAccounts.length === 0" class="bg-[#252930] rounded-lg border border-[#2b3139] p-6 text-center">
        <div class="text-gray-400 text-sm">暂无启用的账户</div>
        <div class="text-gray-500 text-xs mt-2">请前往账户管理页面添加账户</div>
      </div>

      <!-- System Alerts -->
      <div class="bg-[#252930] rounded-lg border border-[#2b3139] p-3">
        <div class="text-sm font-semibold mb-3 text-[#f0b90b]">系统提醒</div>
        <div class="space-y-2">
          <div v-for="alert in systemAlerts" :key="alert.id" class="flex items-start space-x-2 text-xs">
            <div class="w-1.5 h-1.5 rounded-full mt-1 flex-shrink-0" :class="getAlertColor(alert.type)"></div>
            <div class="flex-1">
              <div class="text-gray-300">{{ alert.message }}</div>
              <div v-if="alert.value" class="text-gray-500 mt-0.5">{{ alert.value }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()

const totalProfit = ref(0)
const activeAccounts = ref([])
const systemAlerts = ref([])

// Persist disconnected state across page refreshes
const STORAGE_KEY = 'disconnectedAccounts'
const RECONNECT_COOLDOWN_KEY = 'lastReconnectTime'
const RECONNECT_COOLDOWN_MS = 10000 // 10 seconds cooldown to prevent Binance ban

function loadDisconnected() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? new Set(JSON.parse(saved)) : new Set()
  } catch { return new Set() }
}
function saveDisconnected(set) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]))
}
function canReconnect() {
  const lastReconnect = localStorage.getItem(RECONNECT_COOLDOWN_KEY)
  if (!lastReconnect) return true
  const timeSinceLastReconnect = Date.now() - parseInt(lastReconnect)
  return timeSinceLastReconnect >= RECONNECT_COOLDOWN_MS
}
function setReconnectTime() {
  localStorage.setItem(RECONNECT_COOLDOWN_KEY, Date.now().toString())
}
const disconnectedAccounts = ref(loadDisconnected())

let updateInterval = null

onMounted(() => {
  fetchAccountData()
  updateInterval = setInterval(fetchAccountData, 30000)
  // Restore WS state based on persisted disconnected accounts
  // If any accounts were disconnected before, WS may have been stopped —
  // only connect if there are no disconnected accounts saved
  if (disconnectedAccounts.value.size === 0) {
    marketStore.connect()
  }
})

onUnmounted(() => {
  if (updateInterval) clearInterval(updateInterval)
})

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

    if (data.summary) {
      totalProfit.value = data.summary.daily_pnl || 0
    }

    const allAccounts = []

    if (data.accounts && data.accounts.length > 0) {
      allAccounts.push(...data.accounts.map(acc => ({
        ...acc,
        is_active: acc.is_active !== undefined ? acc.is_active : true
      })))
    }

    if (data.failed_accounts && data.failed_accounts.length > 0) {
      for (const failedAcc of data.failed_accounts) {
        allAccounts.push({
          account_id: failedAcc.account_id,
          account_name: failedAcc.account_name,
          platform_id: failedAcc.platform_id || 0,
          is_mt5_account: failedAcc.is_mt5_account || false,
          is_active: failedAcc.is_active !== undefined ? failedAcc.is_active : true,
          balance: {
            total_assets: 0,
            available_balance: 0,
            net_assets: 0,
            margin_balance: 0,
            frozen_assets: 0,
            total_positions: 0,
            daily_pnl: 0,
            funding_fee: 0,
            risk_ratio: 0
          },
          error: failedAcc.error
        })
      }
    }

    // Always update all accounts with fresh data
    activeAccounts.value = allAccounts

    systemAlerts.value = generateSystemAlerts(data)
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

function generateSystemAlerts(data) {
  const alerts = []

  if (data.summary) {
    // Net value alert
    alerts.push({
      id: 1,
      type: 'warning',
      message: '账户净值提醒',
      value: `当前净值: $${formatNumber(data.summary.net_assets || 0)}`
    })

    // Risk status
    const riskRatio = data.summary.risk_ratio || 0
    if (riskRatio > 60) {
      alerts.push({
        id: 2,
        type: 'danger',
        message: '风险率过高',
        value: `当前风险率: ${riskRatio.toFixed(2)}%`
      })
    } else {
      alerts.push({
        id: 2,
        type: 'success',
        message: '风控状态',
        value: '正常运行'
      })
    }

    // Position count
    if (data.summary.position_count > 0) {
      alerts.push({
        id: 3,
        type: 'info',
        message: '持仓提醒',
        value: `当前持仓: ${data.summary.position_count} 个`
      })
    }
  }

  return alerts
}

function toggleConnection(accountId) {
  if (disconnectedAccounts.value.has(accountId)) {
    // Reconnecting - check cooldown to prevent Binance ban
    if (!canReconnect()) {
      const lastReconnect = parseInt(localStorage.getItem(RECONNECT_COOLDOWN_KEY))
      const remaining = Math.ceil((RECONNECT_COOLDOWN_MS - (Date.now() - lastReconnect)) / 1000)
      alert(`请等待 ${remaining} 秒后再重新连接，以避免触发 Binance 限制`)
      return
    }
    disconnectedAccounts.value.delete(accountId)
    disconnectedAccounts.value = new Set(disconnectedAccounts.value)
    saveDisconnected(disconnectedAccounts.value)
    setReconnectTime()
    // Reconnect market WebSocket
    marketStore.connect()
  } else {
    // Disconnecting
    disconnectedAccounts.value.add(accountId)
    disconnectedAccounts.value = new Set(disconnectedAccounts.value)
    saveDisconnected(disconnectedAccounts.value)
    // Disconnect market WebSocket only if all accounts are disconnected
    if (disconnectedAccounts.value.size >= activeAccounts.value.length) {
      marketStore.disconnect()
    }
  }
}

async function toggleDisable(accountId) {
  if (!disconnectedAccounts.value.has(accountId)) return

  try {
    await api.put(`/api/v1/accounts/${accountId}`, { is_active: false })
    disconnectedAccounts.value.delete(accountId)
    disconnectedAccounts.value = new Set(disconnectedAccounts.value)
    saveDisconnected(disconnectedAccounts.value)
    await fetchAccountData()
  } catch (error) {
    console.error('Failed to disable account:', error)
    alert(`操作失败: ${error.response?.data?.detail || error.message}`)
  }
}

function getPlatformName(platformId, isMt5Account) {
  if (platformId === 1) return 'Binance'
  if (platformId === 2) {
    return isMt5Account ? 'Bybit MT5' : 'Bybit'
  }
  return 'Unknown'
}

function formatNumber(num) {
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function getRiskColor(ratio) {
  if (ratio < 30) return 'text-[#0ecb81]'
  if (ratio < 60) return 'text-[#f0b90b]'
  return 'text-[#f6465d]'
}

function getAlertColor(type) {
  const colors = {
    success: 'bg-[#0ecb81]',
    warning: 'bg-[#f0b90b]',
    danger: 'bg-[#f6465d]',
    info: 'bg-[#2196F3]'
  }
  return colors[type] || 'bg-gray-500'
}

function getBanInfo(account) {
  if (!account.error) return null

  // Check if error is a rate limit ban
  if (account.error.startsWith('RATE_LIMIT:')) {
    const banUntilMs = parseInt(account.error.split(':')[1])
    if (banUntilMs && banUntilMs > 0) {
      const banUntilDate = new Date(banUntilMs)
      const now = new Date()
      const minutesLeft = Math.ceil((banUntilDate - now) / 1000 / 60)

      if (minutesLeft > 0) {
        const hours = banUntilDate.getHours()
        const minutes = banUntilDate.getMinutes()
        const ampm = hours >= 12 ? 'PM' : 'AM'
        const displayHours = hours % 12 || 12
        const displayMinutes = minutes.toString().padStart(2, '0')

        return `限制至${displayHours}:${displayMinutes} ${ampm} (${minutesLeft}分钟)`
      }
    }
  }

  return null
}

function getDisplayValue(account, field, showSign = false, isPercent = false) {
  // Check if account has rate limit ban
  const banInfo = getBanInfo(account)
  if (banInfo) {
    return banInfo
  }

  // Check if account has error
  if (account.error) {
    return '暂无'
  }

  // All fields live inside account.balance
  const value = account.balance ? account.balance[field] : null

  // Handle null/undefined values
  if (value == null) {
    return '暂无'
  }

  // Format the value
  if (isPercent) {
    return value.toFixed(2) + '%'
  }

  if (showSign) {
    const sign = value >= 0 ? '+' : ''
    return sign + formatNumber(Math.abs(value)) + ' USDT'
  }

  return formatNumber(value) + ' USDT'
}

function getValueColor(account, field) {
  // Check if account has error
  if (account.error) {
    return 'text-gray-400'
  }

  const value = account.balance ? account.balance[field] : null

  if (value == null) {
    return 'text-gray-400'
  }

  return value >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'
}
</script>
