<template>
  <div class="flex flex-col h-full">
    <div class="flex-1 overflow-y-auto p-2 md:p-3 space-y-1.5 md:space-y-2">
      <!-- Dynamic Account Cards -->
      <div v-for="account in activeAccounts" :key="account.account_id" class="bg-[#252930] rounded-lg border border-[#2b3139]">
        <div class="p-1.5 md:p-2 border-b border-[#2b3139] space-y-1">
          <!-- Row 1: 状态灯 + 账户名 -->
          <div class="flex items-center space-x-1.5">
            <div class="w-1.5 h-1.5 rounded-full" :class="account.error ? 'bg-[#f0b90b]' : (account.is_active ? 'bg-[#0ecb81]' : 'bg-[#f6465d]')"></div>
            <span class="text-sm font-bold text-[#D4B106] truncate">{{ account.account_name }}</span>
          </div>
          <!-- Row 2: 平台名 + 连接状态 + 断开/禁用按钮 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2 min-w-0">
              <span class="font-semibold text-xs shrink-0">{{ getPlatformName(account.platform_id, account.is_mt5_account) }}</span>
              <span class="text-[10px] shrink-0" :class="account.error ? 'text-[#f0b90b]' : (account.is_active ? 'text-[#0ecb81]' : 'text-gray-500')">
                {{ account.error ? '连接失败' : (account.is_active ? '已激活' : '未连接') }}
              </span>
            </div>
            <div class="flex space-x-1 shrink-0 ml-2">
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
          <!-- Row 3: 代理状态 -->
          <div class="flex items-center space-x-1 text-[10px]">
            <div class="w-1 h-1 rounded-full shrink-0" :class="account.proxy_config && account.proxy_config.host ? (aspProxyExpired(account.proxy_config) ? 'bg-red-500' : 'bg-[#0ecb81]') : 'bg-gray-500'"></div>
            <span class="text-gray-400 shrink-0">代理IP:</span>
            <span v-if="account.proxy_config && account.proxy_config.host" class="truncate">
              <span class="text-gray-300 font-mono">{{ account.proxy_config.host }}:{{ account.proxy_config.port }}</span>
              <span v-if="account.proxy_config.expires_at" class="ml-0.5"
                :class="aspProxyDaysLeft(account.proxy_config.expires_at) <= 7 ? 'text-red-400 font-semibold' : 'text-gray-500'">
                到期:{{ account.proxy_config.expires_at }}
                <span v-if="aspProxyDaysLeft(account.proxy_config.expires_at) <= 0" class="text-red-500">(已过期)</span>
                <span v-else-if="aspProxyDaysLeft(account.proxy_config.expires_at) <= 7">({{ aspProxyDaysLeft(account.proxy_config.expires_at) }}天)</span>
              </span>
            </span>
            <span v-else class="text-gray-400">当前直连</span>
          </div>
          <!-- Row 4: 错误提示 -->
          <div v-if="account.error" class="text-[10px] rounded px-1.5 py-0.5" :class="getErrorStyle(account.error)">
            <div v-if="account.error.startsWith('RATE_LIMIT')">
              <div class="font-semibold">主账号 API限流</div>
              <div class="mt-0.5">{{ getBanInfo(account) || '请稍后重试' }}</div>
              <div class="mt-0.5 text-[9px] opacity-75">系统已自动降低请求频率，请耐心等待</div>
            </div>
            <div v-else-if="account.error.startsWith('IP_WHITELIST:')">
              <div class="font-semibold flex items-center space-x-1">
                <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                <span>IP白名单未配置</span>
              </div>
              <div class="mt-0.5">{{ account.error.substring(13) }}</div>
              <div class="mt-1 text-[9px] opacity-90 leading-relaxed">
                请前往交易所API管理页面，将服务器IP添加到API Key的"IP访问限制"白名单中
              </div>
            </div>
            <div v-else>
              错误: {{ account.error }}
            </div>
          </div>
          <!-- Row 5: 强平价 -->
          <div v-if="!account.error && account.is_active" class="space-y-0.5">
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
            <span class="text-gray-400">BNB持仓</span>
            <span class="font-mono text-[#f0b90b]">{{ getBnbBalance(account) }}</span>
          </div>
          <div v-if="account.platform_id === 1" class="flex justify-between">
            <span class="text-gray-400">手续费率(挂/吃)</span>
            <span class="font-mono text-gray-300">{{ getCommissionRate(account) }}</span>
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

  // Initial fetch
  fetchAccountData()

  // Refresh proxy status every 30 seconds
  proxyRefreshTimer = setInterval(() => {
    fetchProxyStatus()
  }, 30000)
})

onUnmounted(() => {
  if (proxyRefreshTimer) {
    clearInterval(proxyRefreshTimer)
  }
})

// Watch for account balance updates via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
}, { deep: false })

function handleAccountBalanceUpdate(data) {
  if (data.accounts && data.accounts.length > 0) {
    data.accounts.forEach(updatedAcc => {
      const index = activeAccounts.value.findIndex(acc => acc.account_id === updatedAcc.account_id)
      if (index !== -1) {
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
            total_assets: 0, available_balance: 0, net_assets: 0,
            margin_balance: 0, frozen_assets: 0, total_positions: 0,
            daily_pnl: 0, funding_fee: 0, risk_ratio: 0
          },
          error: failedAcc.error
        })
      }
    }

    // ★ aggregated API 已包含MT5余额数据，直接渲染
    activeAccounts.value = allAccounts
    notificationStore.updateSystemAlerts(data)

    // 合并 proxy_config 到账户数据（从账户列表获取）
    try {
      const accListRes = await api.get('/api/v1/accounts')
      const accList = Array.isArray(accListRes.data) ? accListRes.data : []
      const pcMap = {}
      accList.forEach(a => { pcMap[a.account_id] = a.proxy_config })
      activeAccounts.value.forEach(acc => {
        if (!acc.proxy_config && pcMap[acc.account_id]) {
          acc.proxy_config = pcMap[acc.account_id]
        }
      })
    } catch (e) { console.debug('proxy_config merge skipped:', e) }

    // 异步加载代理状态（不阻塞渲染）
    fetchProxyStatus()

  } catch (error) {
    console.error('Failed to fetch account data:', error)
    // 降级：用基础账户列表
    try {
      const r2 = await api.get('/api/v1/accounts')
      const list = Array.isArray(r2.data) ? r2.data : (r2.data?.accounts ?? [])
      activeAccounts.value = list.map(acc => ({
        ...acc,
        balance: {
          total_assets: 0, available_balance: 0, net_assets: 0,
          margin_balance: 0, frozen_assets: 0, total_positions: 0,
          daily_pnl: 0, funding_fee: 0, risk_ratio: 0
        },
        error: '实时余额获取失败，请检查API密钥或网络'
      }))
    } catch (e2) {
      console.error('Fallback accounts fetch failed:', e2)
    }
  }
}

/** 并发拉取所有账户的代理状态 */
async function fetchProxyStatus() {
  const accounts = activeAccounts.value
  if (!accounts.length) return

  const promises = accounts.map(async (account) => {
    try {
      const response = await api.get(`/api/v1/accounts/${account.account_id}/proxy/${account.platform_id}`)
      const key = `${account.account_id}_${account.platform_id}`
      if (response.data) {
        accountProxies.value[key] = { ...response.data, platform_id: account.platform_id }
      } else {
        delete accountProxies.value[key]
      }
    } catch (error) {
      if (error.response?.status !== 404) {
        console.error(`Failed to fetch proxy for ${account.account_id}:`, error)
      }
    }
  })
  await Promise.all(promises)
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
    if (!canReconnect()) {
      const lastReconnect = parseInt(localStorage.getItem(RECONNECT_COOLDOWN_KEY))
      const remaining = Math.ceil((RECONNECT_COOLDOWN_MS - (Date.now() - lastReconnect)) / 1000)
      alert(`请等待 ${remaining} 秒后再重新连接，以避免触发API限制`)
      return
    }
    disconnectedAccounts.value.delete(accountId)
    disconnectedAccounts.value = new Set(disconnectedAccounts.value)
    saveDisconnected(disconnectedAccounts.value)
    setReconnectTime()
    marketStore.connect()
    setWsConnectedState(true)
  } else {
    if (hasActiveStrategies()) {
      alert('请先停用所有策略按钮再断开连接')
      return
    }
    disconnectedAccounts.value.add(accountId)
    disconnectedAccounts.value = new Set(disconnectedAccounts.value)
    saveDisconnected(disconnectedAccounts.value)
    if (disconnectedAccounts.value.size >= activeAccounts.value.length) {
      marketStore.disconnect()
      setWsConnectedState(false)
    }
  }
}

function hasActiveStrategies() {
  try {
    return ['forward_opening', 'forward_closing', 'reverse_opening', 'reverse_closing']
      .some(s => localStorage.getItem(`strategy_${s}_enabled`) === 'true')
  } catch { return false }
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

function getErrorStyle(error) {
  if (!error) return 'text-[#f0b90b] bg-[#f0b90b]/10'
  if (error.startsWith('RATE_LIMIT')) return 'text-orange-400 bg-orange-400/10'
  if (error.startsWith('IP_WHITELIST:')) return 'text-red-400 bg-red-400/10 border border-red-500/30'
  return 'text-[#f0b90b] bg-[#f0b90b]/10'
}
function aspProxyDaysLeft(dateStr) {
  if (!dateStr) return 999
  const exp = new Date(dateStr + 'T00:00:00')
  const now = new Date()
  now.setHours(0,0,0,0)
  return Math.floor((exp - now) / 86400000)
}
function aspProxyExpired(cfg) {
  if (!cfg || !cfg.expires_at) return false
  return aspProxyDaysLeft(cfg.expires_at) < 0
}

function getPlatformName(platformId, isMt5Account) {
  if (platformId === 1) return '主账号'
  if (platformId === 2) return isMt5Account ? '对冲账户' : '对冲账户'
  return 'Unknown'
}

function formatNumber(num) {
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function getRiskColor(account) {
  if (account.error || !account.balance) return 'text-gray-400'
  const ratio = account.balance.risk_ratio || 0
  if (account.platform_id === 2 && account.is_mt5_account) {
    if (ratio === 0) return 'text-gray-400'
    if (ratio < 50) return 'text-[#f6465d]'
    if (ratio < 100) return 'text-[#f0b90b]'
    if (ratio < 150) return 'text-[#f0b90b]'
    return 'text-[#0ecb81]'
  }
  if (ratio < 30) return 'text-[#0ecb81]'
  if (ratio < 60) return 'text-[#f0b90b]'
  return 'text-[#f6465d]'
}

function getBanInfo(account) {
  if (!account.error) return null
  if (account.error.startsWith('RATE_LIMIT:')) {
    const banUntilMs = parseInt(account.error.split(':')[1])
    if (banUntilMs && banUntilMs > 0) {
      const remainingMs = banUntilMs - Date.now()
      if (remainingMs > 0) {
        const banUntilDate = new Date(banUntilMs)
        const beijingOffset = 8 * 60
        const localOffset = banUntilDate.getTimezoneOffset()
        const beijingTime = new Date(banUntilMs + (beijingOffset + localOffset) * 60 * 1000)
        const displayTime = `${String(beijingTime.getHours()).padStart(2,'0')}:${String(beijingTime.getMinutes()).padStart(2,'0')}:${String(beijingTime.getSeconds()).padStart(2,'0')}`
        const remainingSeconds = Math.ceil(remainingMs / 1000)
        const remainingMinutes = Math.floor(remainingSeconds / 60)
        const secs = remainingSeconds % 60
        const remainingText = remainingMinutes > 0 ? `${remainingMinutes}分${secs}秒` : `${secs}秒`
        return `API限流至北京时间 ${displayTime} (剩余 ${remainingText})`
      }
    }
  }
  return null
}

function getDisplayValue(account, field, showSign = false, isPercent = false, isLots = false) {
  const banInfo = getBanInfo(account)
  if (banInfo) return banInfo
  if (account.error) return '暂无'
  const value = account.balance ? account.balance[field] : null
  if (value == null) return '暂无'
  if (isPercent) return value.toFixed(2) + '%'
  if (isLots) return formatNumber(value) + ' 手'
  if (showSign) {
    const sign = value >= 0 ? '+' : ''
    return sign + formatNumber(Math.abs(value)) + ' USDT'
  }
  return formatNumber(value) + ' USDT'
}

function getBnbBalance(account) {
  if (account.error || !account.balance) return '暂无'
  const v = account.balance.bnb_balance
  if (v == null) return '暂无'
  return v.toFixed(4) + ' BNB'
}

function getCommissionRate(account) {
  if (account.error || !account.balance) return '暂无'
  const maker = account.balance.maker_commission_rate
  const taker = account.balance.taker_commission_rate
  if (maker == null || taker == null) return '暂无'
  return (maker * 100).toFixed(4) + '% / ' + (taker * 100).toFixed(4) + '%'
}

function getValueColor(account, field) {
  if (account.error) return 'text-gray-400'
  const value = account.balance ? account.balance[field] : null
  if (value == null) return 'text-gray-400'
  return value >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'
}

function getLiquidationPrice(account, type) {
  if (account.error || !account.balance) return '暂无'
  const balance = account.balance

  if (account.platform_id === 2 && account.is_mt5_account) {
    const hasLong = balance.long_liquidation_price && balance.long_liquidation_price > 0
    const hasShort = balance.short_liquidation_price && balance.short_liquidation_price > 0
    if (hasLong && !hasShort) return type === 'long' ? formatNumber(balance.long_liquidation_price) : '暂无'
    if (hasShort && !hasLong) return type === 'short' ? formatNumber(balance.short_liquidation_price) : '暂无'
    if (type === 'long' && hasLong) return formatNumber(balance.long_liquidation_price)
    if (type === 'short' && hasShort) return formatNumber(balance.short_liquidation_price)
    return '暂无'
  }

  if (account.platform_id === 1) {
    if (type === 'long' && balance.long_liquidation_price > 0) return formatNumber(balance.long_liquidation_price)
    if (type === 'short' && balance.short_liquidation_price > 0) return formatNumber(balance.short_liquidation_price)
    const entryPrice = balance.entryPrice || balance.entry_price || 0
    const leverage = balance.leverage || 0
    if (entryPrice === 0 || leverage === 0) return '暂无'
    const liqPrice = type === 'long' ? entryPrice * (1 - 1 / leverage) : entryPrice * (1 + 1 / leverage)
    return formatNumber(liqPrice)
  }

  return '暂无'
}
</script>

<style scoped>
.bg-\[#252930\] {
  transition: all 0.3s ease-in-out;
}
.font-mono {
  transition: color 0.2s ease-in-out;
}
.w-1\.5 {
  transition: background-color 0.3s ease-in-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}
.bg-\[#252930\] {
  animation: fadeIn 0.3s ease-in-out;
}
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
