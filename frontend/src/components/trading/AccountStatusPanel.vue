<template>
  <div class="flex flex-col h-full">
    <div class="flex-1 overflow-y-auto p-2 md:p-3 space-y-1.5 md:space-y-2">
      <!-- Dynamic Account Cards -->
      <div v-for="account in activeAccounts" :key="account.account_id" class="bg-[#252930] rounded-lg border border-[#2b3139]">
        <div class="p-1.5 md:p-2 border-b border-[#2b3139]">
          <div class="flex items-center justify-between">
            <div class="flex flex-col items-start space-y-1 md:space-y-1.5">
              <div class="flex items-center space-x-1.5">
                <div class="w-1.5 h-1.5 rounded-full" :class="account.error ? 'bg-[#f0b90b]' : (account.is_active ? 'bg-[#0ecb81]' : 'bg-[#f6465d]')"></div>
                <span class="text-sm font-bold text-[#D4B106]">{{ account.account_name }}</span>
              </div>
              <span class="font-semibold text-xs">{{ getPlatformName(account.platform_id, account.is_mt5_account) }}</span>

              <!-- Proxy Status -->
              <div class="flex items-center space-x-1 text-[10px]">
                <div class="w-1 h-1 rounded-full" :class="getProxyStatus(account) ? getProxyStatusColor(account) : 'bg-gray-500'"></div>
                <span class="text-gray-400">代理IP:</span>
                <span :class="getProxyStatus(account) ? getProxyStatusTextColor(account) : 'text-gray-400'">{{ getProxyStatus(account) ? getProxyStatusText(account) : '当前直连' }}</span>
              </div>

              <span class="text-[10px]" :class="account.error ? 'text-[#f0b90b]' : 'text-gray-500'">
                {{ account.error ? '连接失败' : (account.is_active ? '已激活' : '未连接') }}
              </span>
              <!-- Liquidation Prices -->
              <div v-if="!account.error && account.is_active" class="mt-1 space-y-0.5">
                <div class="flex items-center space-x-1.5 text-[10px]">
                  <span class="text-gray-400">多头强平价:</span>
                  <span class="font-mono text-[#0ecb81]">{{ getLiquidationPrice(account, 'long') }}</span>
                </div>
                <div class="flex items-center space-x-1.5 text-[10px]">
                  <span class="text-gray-400">空头强平价:</span>
                  <span class="font-mono text-[#f6465d]">{{ getLiquidationPrice(account, 'short') }}</span>
                </div>
              </div>
            </div>
            <div class="flex space-x-1 self-center">
              <button
                @click="toggleConnection(account.account_id)"
                class="px-1.5 py-0.5 text-[10px] rounded transition-colors whitespace-nowrap"
                :class="disconnectedAccounts.has(account.account_id) ? 'bg-[#0ecb81] hover:bg-[#0db774]' : 'bg-[#f6465d] hover:bg-[#e03d52]'"
              >
                {{ disconnectedAccounts.has(account.account_id) ? '连接' : '断开' }}
              </button>
              <button
                @click="toggleDisable(account.account_id)"
                class="px-1.5 py-0.5 text-[10px] rounded transition-colors whitespace-nowrap"
                :class="disconnectedAccounts.has(account.account_id) ? 'bg-gray-600 hover:bg-gray-700' : 'bg-gray-500 opacity-50 cursor-not-allowed'"
                :disabled="!disconnectedAccounts.has(account.account_id)"
                :title="!disconnectedAccounts.has(account.account_id) ? '请先断开连接再禁用' : ''"
              >
                禁用
              </button>
            </div>
          </div>
          <!-- Error Message -->
          <div v-if="account.error" class="mt-1 text-[10px] rounded px-1.5 py-0.5" :class="account.error.startsWith('RATE_LIMIT') ? 'text-orange-400 bg-orange-400/10' : 'text-[#f0b90b] bg-[#f0b90b]/10'">
            <div v-if="account.error.startsWith('RATE_LIMIT')">
              <div class="font-semibold">⚠️ Binance API限流</div>
              <div class="mt-0.5">{{ getBanInfo(account) || '请稍后重试' }}</div>
              <div class="mt-0.5 text-[9px] opacity-75">系统已自动降低请求频率，请耐心等待</div>
            </div>
            <div v-else>
              错误: {{ account.error }}
            </div>
          </div>
        </div>

        <div class="p-1.5 md:p-2 space-y-0.5 md:space-y-1 text-[13px]">
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
            <span class="font-mono">{{ getDisplayValue(account, 'total_positions', false, false, true) }}</span>
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
            <span class="font-mono" :class="getRiskColor(account)">
              {{ getDisplayValue(account, 'risk_ratio', false, true) }}
            </span>
          </div>
          <div v-if="account.platform_id === 2" class="flex justify-between">
            <span class="text-gray-400">手续费(佣金)</span>
            <span class="font-mono" :class="getValueColor(account, 'commission_fee')">
              {{ getDisplayValue(account, 'commission_fee', true) }}
            </span>
          </div>
          <div v-if="account.platform_id === 2" class="flex justify-between">
            <span class="text-gray-400">MT5过夜费</span>
            <span class="font-mono" :class="getValueColor(account, 'funding_fee')">
              {{ getDisplayValue(account, 'funding_fee', true) }}
            </span>
          </div>
          <div v-if="account.platform_id === 1" class="flex justify-between">
            <span class="text-gray-400">资金费(多头)</span>
            <span class="font-mono" :class="getValueColor(account, 'long_funding_rate')">
              {{ getDisplayValue(account, 'long_funding_rate', true) }}
            </span>
          </div>
          <div v-if="account.platform_id === 1" class="flex justify-between">
            <span class="text-gray-400">资金费(空头)</span>
            <span class="font-mono" :class="getValueColor(account, 'short_funding_rate')">
              {{ getDisplayValue(account, 'short_funding_rate', true) }}
            </span>
          </div>
        </div>
      </div>

      <!-- No Accounts Message -->
      <div v-if="activeAccounts.length === 0" class="bg-[#252930] rounded-lg border border-[#2b3139] p-6 text-center">
        <div class="text-gray-400 text-sm">暂无启用的账户</div>
        <div class="text-gray-500 text-xs mt-2">请前往账户管理页面添加账户</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'

const marketStore = useMarketStore()
const notificationStore = useNotificationStore()

const activeAccounts = ref([])
const accountProxies = ref({}) // 存储账户代理信息 { account_id: { proxy_data, platform_id } }

// Persist disconnected state across page refreshes
const STORAGE_KEY = 'disconnectedAccounts'
const RECONNECT_COOLDOWN_KEY = 'lastReconnectTime'
const WS_CONNECTED_KEY = 'wsConnectedState'
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
function getWsConnectedState() {
  try {
    const saved = localStorage.getItem(WS_CONNECTED_KEY)
    return saved === 'true'
  } catch { return false }
}
function setWsConnectedState(connected) {
  localStorage.setItem(WS_CONNECTED_KEY, connected.toString())
}
const disconnectedAccounts = ref(loadDisconnected())
let proxyRefreshTimer = null

onMounted(() => {
  // Ensure WebSocket connection
  if (!marketStore.connected) {
    const wasConnected = getWsConnectedState()
    if (wasConnected && disconnectedAccounts.value.size === 0) {
      marketStore.connect()
    }
  }

  // Initial fetch only
  fetchAccountData()

  // Refresh proxy status every 30 seconds
  proxyRefreshTimer = setInterval(() => {
    fetchProxyStatus()
  }, 30000)
})

onUnmounted(() => {
  // Cleanup
  if (proxyRefreshTimer) {
    clearInterval(proxyRefreshTimer)
  }
})

// Watch for account balance updates via WebSocket (when backend implements it)
// Optimized: Only trigger when message type is account_balance
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
}, { deep: false }) // Shallow watch for better performance

function handleAccountBalanceUpdate(data) {
  if (data.accounts && data.accounts.length > 0) {
    // Update existing accounts with new balance data
    // Use Object.assign for better performance
    data.accounts.forEach(updatedAcc => {
      const index = activeAccounts.value.findIndex(acc => acc.account_id === updatedAcc.account_id)
      if (index !== -1) {
        // Only update if data actually changed
        const currentAcc = activeAccounts.value[index]
        const hasChanges = JSON.stringify(currentAcc.balance) !== JSON.stringify(updatedAcc.balance)

        if (hasChanges) {
          activeAccounts.value[index] = {
            ...currentAcc,
            ...updatedAcc,
            balance: { ...currentAcc.balance, ...updatedAcc.balance }
          }
        }
      }
    })

    // Update system alerts via notification store
    notificationStore.updateSystemAlerts(data)
  }
}

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

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

    notificationStore.updateSystemAlerts(data)

    // Fetch proxy status for each account
    await fetchProxyStatus()
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

async function fetchProxyStatus() {
  try {
    for (const account of activeAccounts.value) {
      // 为每个平台获取代理状态
      const platforms = [account.platform_id]

      for (const platformId of platforms) {
        try {
          const response = await api.get(`/api/v1/accounts/${account.account_id}/proxy/${platformId}`)
          const key = `${account.account_id}_${platformId}`
          if (response.data) {
            accountProxies.value[key] = {
              ...response.data,
              platform_id: platformId
            }
          } else {
            // null means no proxy bound (direct connection) — remove any stale entry
            delete accountProxies.value[key]
          }
        } catch (error) {
          // 如果没有绑定代理，忽略错误
          if (error.response?.status !== 404) {
            console.error(`Failed to fetch proxy for account ${account.account_id} platform ${platformId}:`, error)
          }
        }
      }
    }
  } catch (error) {
    console.error('Failed to fetch proxy status:', error)
  }
}

function getProxyStatus(account) {
  const key = `${account.account_id}_${account.platform_id}`
  return accountProxies.value[key]
}

function getProxyStatusColor(account) {
  const proxy = getProxyStatus(account)
  if (!proxy) return 'bg-gray-500'

  const health = proxy.health_score || 0
  if (health >= 80) return 'bg-[#0ecb81]'
  if (health >= 50) return 'bg-[#f0b90b]'
  return 'bg-[#f6465d]'
}

function getProxyStatusTextColor(account) {
  const proxy = getProxyStatus(account)
  if (!proxy) return 'text-gray-400'

  const health = proxy.health_score || 0
  if (health >= 80) return 'text-[#0ecb81]'
  if (health >= 50) return 'text-[#f0b90b]'
  return 'text-[#f6465d]'
}

function getProxyStatusText(account) {
  const proxy = getProxyStatus(account)
  if (!proxy) return '直连 (0/100, -)'

  const health = proxy.health_score || 0
  const latency = proxy.avg_latency_ms ? `${Math.round(proxy.avg_latency_ms)}ms` : '-'

  return `${proxy.host}:${proxy.port} (${health}/100, ${latency})`
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
    // Reconnect market WebSocket and save state
    marketStore.connect()
    setWsConnectedState(true)
  } else {
    // Disconnecting - check if any strategies are enabled
    if (hasActiveStrategies()) {
      alert('请先停用所有策略按钮再断开连接')
      return
    }

    disconnectedAccounts.value.add(accountId)
    disconnectedAccounts.value = new Set(disconnectedAccounts.value)
    saveDisconnected(disconnectedAccounts.value)
    // Disconnect market WebSocket only if all accounts are disconnected
    if (disconnectedAccounts.value.size >= activeAccounts.value.length) {
      marketStore.disconnect()
      setWsConnectedState(false)
    }
  }
}

// Check if any strategies are currently enabled
function hasActiveStrategies() {
  try {
    // Check forward opening
    const forwardOpeningEnabled = localStorage.getItem('strategy_forward_opening_enabled')
    if (forwardOpeningEnabled === 'true') return true

    // Check forward closing
    const forwardClosingEnabled = localStorage.getItem('strategy_forward_closing_enabled')
    if (forwardClosingEnabled === 'true') return true

    // Check reverse opening
    const reverseOpeningEnabled = localStorage.getItem('strategy_reverse_opening_enabled')
    if (reverseOpeningEnabled === 'true') return true

    // Check reverse closing
    const reverseClosingEnabled = localStorage.getItem('strategy_reverse_closing_enabled')
    if (reverseClosingEnabled === 'true') return true

    return false
  } catch (error) {
    console.error('Error checking strategy status:', error)
    return false
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

function getRiskColor(account) {
  // Check if account has error
  if (account.error || !account.balance) {
    return 'text-gray-400'
  }

  const ratio = account.balance.risk_ratio || 0

  // For Bybit MT5: risk_ratio is margin_level (equity/margin × 100)
  // Lower is more dangerous (opposite of other platforms)
  if (account.platform_id === 2 && account.is_mt5_account) {
    if (ratio === 0) return 'text-gray-400'  // No position
    if (ratio < 50) return 'text-[#f6465d]'   // Critical: will be liquidated
    if (ratio < 100) return 'text-[#f0b90b]'  // Warning: margin call
    if (ratio < 150) return 'text-[#f0b90b]'  // Caution
    return 'text-[#0ecb81]'                   // Safe
  }

  // For other platforms (higher ratio = more risk)
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

  console.log('[getBanInfo] account.error:', account.error)

  // Check if error is a rate limit ban
  if (account.error.startsWith('RATE_LIMIT:')) {
    const banUntilMs = parseInt(account.error.split(':')[1])
    console.log('[getBanInfo] banUntilMs:', banUntilMs)

    if (banUntilMs && banUntilMs > 0) {
      const now = Date.now()
      const remainingMs = banUntilMs - now
      console.log('[getBanInfo] now:', now, 'remainingMs:', remainingMs)

      if (remainingMs > 0) {
        // Convert to Beijing time (UTC+8)
        const banUntilDate = new Date(banUntilMs)
        const beijingOffset = 8 * 60 // Beijing is UTC+8
        const localOffset = banUntilDate.getTimezoneOffset() // Local timezone offset in minutes
        const beijingTime = new Date(banUntilMs + (beijingOffset + localOffset) * 60 * 1000)

        // Format as Beijing time (24-hour format)
        const hours = beijingTime.getHours()
        const minutes = beijingTime.getMinutes()
        const seconds = beijingTime.getSeconds()
        const displayTime = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`

        // Calculate remaining time
        const remainingSeconds = Math.ceil(remainingMs / 1000)
        const remainingMinutes = Math.floor(remainingSeconds / 60)
        const remainingSecondsOnly = remainingSeconds % 60

        let remainingText = ''
        if (remainingMinutes > 0) {
          remainingText = `${remainingMinutes}分${remainingSecondsOnly}秒`
        } else {
          remainingText = `${remainingSecondsOnly}秒`
        }

        const result = `API限流至北京时间 ${displayTime} (剩余 ${remainingText})`
        console.log('[getBanInfo] result:', result)
        return result
      }
    }
  }

  return null
}

function getDisplayValue(account, field, showSign = false, isPercent = false, isLots = false) {
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

  if (isLots) {
    return formatNumber(value) + ' 手'
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

function getLiquidationPrice(account, type) {
  // Return placeholder if account has error or no balance data
  if (account.error || !account.balance) {
    return '暂无'
  }

  const balance = account.balance

  // Bybit MT5 calculation
  if (account.platform_id === 2 && account.is_mt5_account) {
    // Check which position type exists based on liquidation prices from backend
    const hasLongPosition = balance.long_liquidation_price && balance.long_liquidation_price > 0
    const hasShortPosition = balance.short_liquidation_price && balance.short_liquidation_price > 0

    // If we have a long position, only show long liquidation price
    if (hasLongPosition && !hasShortPosition) {
      if (type === 'long') {
        return formatNumber(balance.long_liquidation_price)
      } else {
        return '暂无'
      }
    }

    // If we have a short position, only show short liquidation price
    if (hasShortPosition && !hasLongPosition) {
      if (type === 'long') {
        return '暂无'
      } else {
        return formatNumber(balance.short_liquidation_price)
      }
    }

    // If we have both (shouldn't happen in normal cases) or neither, show what we have
    if (type === 'long' && hasLongPosition) {
      return formatNumber(balance.long_liquidation_price)
    }
    if (type === 'short' && hasShortPosition) {
      return formatNumber(balance.short_liquidation_price)
    }

    return '暂无'
  }

  // Binance calculation
  if (account.platform_id === 1) {
    // Prefer API-provided liquidation prices from /fapi/v1/positionRisk
    if (type === 'long' && balance.long_liquidation_price > 0) {
      return formatNumber(balance.long_liquidation_price)
    }
    if (type === 'short' && balance.short_liquidation_price > 0) {
      return formatNumber(balance.short_liquidation_price)
    }

    // Fallback: simplified formula (entryPrice × (1 ± 1/leverage))
    const entryPrice = balance.entryPrice || balance.entry_price || 0
    const leverage = balance.leverage || 0

    if (entryPrice === 0 || leverage === 0) {
      return '暂无'
    }

    if (type === 'long') {
      const liquidationPrice = entryPrice * (1 - 1 / leverage)
      return formatNumber(liquidationPrice)
    } else {
      const liquidationPrice = entryPrice * (1 + 1 / leverage)
      return formatNumber(liquidationPrice)
    }
  }

  return '暂无'
}
</script>

<style scoped>
/* Smooth transitions for data updates */
.bg-\[#252930\] {
  transition: all 0.3s ease-in-out;
}

/* Smooth number transitions */
.font-mono {
  transition: color 0.2s ease-in-out;
}

/* Smooth status indicator transitions */
.w-1\.5 {
  transition: background-color 0.3s ease-in-out;
}

/* Fade in animation for account cards */
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.bg-\[#252930\] {
  animation: fadeIn 0.3s ease-in-out;
}

/* Smooth hover effects */
button {
  transition: all 0.2s ease-in-out;
}

button:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

button:active {
  transform: translateY(0);
}
</style>
