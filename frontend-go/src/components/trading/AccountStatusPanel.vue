<template>
  <div class="flex flex-col h-full">
    <div class="flex-1 overflow-y-auto p-2 md:p-3 space-y-1.5 md:space-y-2">
      <!-- Dynamic Account Cards -->
      <div v-for="account in activeAccounts" :key="account.account_id" class="bg-[#252930] rounded-lg border border-[#2b3139]">
        <div class="p-1.5 md:p-2 border-b border-[#2b3139] space-y-1">
          <!-- Row 1: 状态灯 + 账户名 -->
          <div class="flex items-center space-x-1.5">
            <div class="w-1.5 h-1.5 rounded-full" :class="
              account.error ? 'bg-[#f0b90b]' :
              disconnectedAccounts.has(account.account_id) ? 'bg-[#f6465d]' :
              account.is_active ? 'bg-[#0ecb81]' : 'bg-[#f6465d]'
            "></div>
            <span class="text-sm font-bold text-[#D4B106] truncate">{{ account.account_name }}</span>
            <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px]" :class="account.is_mt5_account ? 'bg-purple-900/40 text-purple-300' : 'bg-blue-900/40 text-blue-300'">{{ getPlatformDisplayName(account) }}</span>
          </div>
          <!-- Row 2: 平台名/角色 + 连接状态 + 断开/禁用按钮 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2 min-w-0">
              <!-- 角色标签 + 双击弹出选项菜单 -->
              <div class="relative shrink-0">
                <span
                  class="font-semibold text-sm cursor-pointer select-none"
                  :class="account.account_role ? 'text-text-primary' : 'text-gray-500 italic'"
                  title="双击切换角色"
                  @dblclick="openRoleMenu(account)"
                >{{ getRoleLabel(account) }}</span>
                <!-- 角色选项浮层 -->
                <div
                  v-if="roleMenuAccountId === account.account_id"
                  class="absolute left-0 top-full mt-0.5 z-50 bg-dark-100 border border-[#2b3139] rounded shadow-lg py-0.5 min-w-[96px]"
                  @mouseleave="roleMenuAccountId = null"
                >
                  <button
                    v-for="opt in getRoleOptions(account)"
                    :key="opt.value"
                    class="w-full text-left px-3 py-1 text-xs hover:bg-[#f0b90b]/10 hover:text-[#f0b90b] transition-colors"
                    @click="setAccountRole(account, opt.value)"
                  >{{ opt.label }}</button>
                </div>
              </div>
              <span class="text-xs shrink-0" :class="
                account.error ? 'text-[#f0b90b]' :
                disconnectedAccounts.has(account.account_id) ? 'text-gray-500' :
                account.is_active ? 'text-[#0ecb81]' : 'text-gray-500'
              ">
                {{
                  account.error ? '连接失败' :
                  disconnectedAccounts.has(account.account_id) ? '已断开' :
                  account.is_active ? '已连接' : '未激活'
                }}
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
          <div class="flex items-center space-x-1 text-xs">
            <div class="w-1.5 h-1.5 rounded-full shrink-0" :class="getProxyStatus(account) ? getProxyStatusColor(account) : 'bg-gray-500'"></div>
            <span class="text-gray-400 shrink-0">代理IP:</span>
            <span class="truncate" :class="getProxyStatus(account) ? getProxyStatusTextColor(account) : 'text-gray-400'">{{ getProxyStatus(account) ? getProxyStatusText(account) : '当前直连' }}</span>
          </div>
          <!-- Row 4: 错误提示 -->
          <div v-if="account.error" class="text-[10px] rounded px-1.5 py-0.5" :class="account.error.startsWith('RATE_LIMIT') ? 'text-orange-400 bg-orange-400/10' : 'text-[#f0b90b] bg-[#f0b90b]/10'">
            <div v-if="account.error.startsWith('RATE_LIMIT')">
              <div class="font-semibold">主账号 API限流</div>
              <div class="mt-0.5">{{ getBanInfo(account) || '请稍后重试' }}</div>
              <div class="mt-0.5 text-[9px] opacity-75">系统已自动降低请求频率，请耐心等待</div>
            </div>
            <div v-else>
              错误: {{ account.error }}
            </div>
          </div>
          <!-- 强平价已移至 MarketCards 行情卡片中展示（实时价格左/右侧） -->
        </div>

        <div class="p-1.5 md:p-2 space-y-0.5 md:space-y-1 text-[20px]">
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
          <div v-if="isHedge(account.platform_id)" class="flex justify-between">
            <span class="text-gray-400">手续费(佣金)</span>
            <span class="font-mono" :class="getValueColor(account, 'commission_fee')">
              {{ getDisplayValue(account, 'commission_fee', true) }}
            </span>
          </div>
          <div v-if="isHedge(account.platform_id)" class="flex justify-between">
            <span class="text-gray-400">过夜费/下期</span>
            <span class="font-mono" :class="getValueColor(account, 'funding_fee')">
              {{ getDisplayValue(account, 'funding_fee', true) }}
            </span>
          </div>
          <div v-if="account.platform_id === PlatformId.BINANCE" class="flex justify-between">
            <span class="text-gray-400">BNB持仓</span>
            <span class="font-mono text-[#f0b90b]">{{ getBnbBalance(account) }}</span>
          </div>
          <div v-if="account.platform_id === PlatformId.BINANCE" class="flex justify-between">
            <span class="text-gray-400">手续费率(挂/吃)</span>
            <span class="font-mono text-gray-300">{{ getCommissionRate(account) }}</span>
          </div>
          <div v-if="account.platform_id === PlatformId.BINANCE" class="flex justify-between">
            <span class="text-gray-400">资金费/下期(多)</span>
            <span class="font-mono" :class="getValueColor(account, 'long_funding_rate')">
              {{ getDisplayValue(account, 'long_funding_rate', true) }}
            </span>
          </div>
          <div v-if="account.platform_id === PlatformId.BINANCE" class="flex justify-between">
            <span class="text-gray-400">资金费/下期(空)</span>
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
import { PlatformId, isHedge } from '@/constants/platform'
console.log('[ASP_DEBUG] AccountStatusPanel script setup executing')
import { useStrategyStore } from '@/stores/strategy'

const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const strategyStore = useStrategyStore()

const activeAccounts = ref([])
const accountProxies = ref({})
const roleMenuAccountId = ref(null) // which account's role menu is open

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
    // WS 余额更新后同步强平价到全局 store（MarketCards 实时读取）
    syncLiquidationPricesToStore(activeAccounts.value)
  }
}

async function fetchAccountData() {
  console.log('[ASP_DEBUG] fetchAccountData called')
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    console.log('[ASP_DEBUG] API response accounts:', response.data?.accounts?.length, response.data?.accounts?.map(a => ({name: a.account_name, pair: a.pair_code, pid: a.platform_id, ll: a.balance?.long_liquidation_price, sl: a.balance?.short_liquidation_price})))
    const data = response.data

    const allAccounts = []

    if (data.accounts && data.accounts.length > 0) {
      allAccounts.push(...data.accounts.map(acc => ({
        ...acc,
        is_active: acc.is_active !== undefined ? acc.is_active : true
      })))
    }

    // NOTE: data.failed_accounts is intentionally NOT merged into the active
    // account list. The backend emits it only for admin (include_inactive=true)
    // or for transient fetch errors; either way those accounts must not show up
    // in the regular user sidebar. Errors surface via notificationStore below.

    // ★ aggregated API 已包含MT5余额数据，直接渲染
    activeAccounts.value = allAccounts
    notificationStore.updateSystemAlerts(data)
    // 初始化时同步强平价到全局 store
    syncLiquidationPricesToStore(allAccounts)

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
    const key = `${account.account_id}_${account.platform_id}`
    try {
      const response = await api.get(`/api/v1/accounts/${account.account_id}/proxy/${account.platform_id}`)
      if (response.data) {
        // ProxyPool 绑定记录存在，直接使用（含 health_score / avg_latency_ms）
        accountProxies.value[key] = { ...response.data, platform_id: account.platform_id }
        return
      }
    } catch (error) {
      if (error.response?.status !== 404) {
        console.error(`Failed to fetch proxy for ${account.account_id}:`, error)
      }
    }

    // ── 降级：ProxyPool 无绑定记录，尝试读取账户自带的 proxy_config ──
    // proxy_config 格式示例（IPIPGO 静态IP）:
    //   { "proxy_type": "http", "host": "xxx", "port": 1234, "username": "...", "password": "..." }
    //   或 "http://user:pass@host:port"
    const pc = account.proxy_config
    if (pc) {
      try {
        let host = '', port = 0
        if (typeof pc === 'string') {
          // URL 格式
          const m = pc.match(/[@/]([^:@/]+):(\d+)\/?$/)
          if (m) { host = m[1]; port = parseInt(m[2]) }
        } else if (typeof pc === 'object') {
          host = pc.host || pc.proxy_host || ''
          port = pc.port || pc.proxy_port || 0
        }
        if (host && port) {
          accountProxies.value[key] = {
            platform_id: account.platform_id,
            host,
            port,
            health_score: 100,      // 静态IP视为健康
            avg_latency_ms: null,
            _from_proxy_config: true // 标记来源，区分 ProxyPool 绑定
          }
          return
        }
      } catch (e) {
        console.warn(`Failed to parse proxy_config for ${account.account_id}:`, e)
      }
    }

    // 真正无代理
    delete accountProxies.value[key]
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
  const health = proxy.health_score ?? 100
  if (health >= 80) return 'bg-[#0ecb81]'
  if (health >= 50) return 'bg-[#f0b90b]'
  return 'bg-[#f6465d]'
}

function getProxyStatusTextColor(account) {
  const proxy = getProxyStatus(account)
  if (!proxy) return 'text-gray-400'
  const health = proxy.health_score ?? 100
  if (health >= 80) return 'text-[#0ecb81]'
  if (health >= 50) return 'text-[#f0b90b]'
  return 'text-[#f6465d]'
}

function getProxyStatusText(account) {
  const proxy = getProxyStatus(account)
  if (!proxy) return '当前直连'
  const health = proxy.health_score ?? 100
  const latency = proxy.avg_latency_ms ? `${Math.round(proxy.avg_latency_ms)}ms` : (proxy._from_proxy_config ? '静态IP' : '-')
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

function getPlatformName(platformId, isMt5Account) {
  if (platformId === 1) return '主账号'
  if (platformId === 2) return isMt5Account ? '对冲账户' : '对冲账户'
  if (platformId === 3) return 'IC Markets'
  if (platformId === 4) return 'Gate.io'
  if (platformId === 5) return 'OKX'
  return '无角色'
}

function getPlatformDisplayName(account) {
  // 显示真实平台名（含 MT5 前缀），与 admin 总控保持一致
  const map = { 1: '币安', 2: 'Bybit', 3: 'IC Markets Global', 4: 'Gate.io', 5: 'OKX' }
  const pname = map[account.platform_id] || '未知'
  return account.is_mt5_account ? ('MT5·' + pname) : pname
}

// 角色标签：有角色显示角色名，无角色显示"无配置"
function getRoleLabel(account) {
  if (account.account_role === 'primary') return '主账号'
  if (account.account_role === 'hedge') return '对冲账户'
  return '无配置'
}

// 双击打开角色选项菜单
function openRoleMenu(account) {
  roleMenuAccountId.value = roleMenuAccountId.value === account.account_id ? null : account.account_id
}

// 返回当前账户可切换到的角色选项（排除当前角色）
function getRoleOptions(account) {
  const all = [
    { value: 'primary', label: '主账号' },
    { value: 'hedge',   label: '对冲账户' },
    { value: null,      label: '不配置' },
  ]
  return all.filter(o => o.value !== (account.account_role || null))
}

// 设置账户角色
async function setAccountRole(account, newRole) {
  roleMenuAccountId.value = null
  try {
    await api.put(`/api/v1/accounts/${account.account_id}`, { account_role: newRole })
    const idx = activeAccounts.value.findIndex(a => a.account_id === account.account_id)
    if (idx >= 0) activeAccounts.value[idx] = { ...activeAccounts.value[idx], account_role: newRole }
  } catch (e) {
    alert(`设置角色失败: ${e.response?.data?.detail || e.message}`)
  }
}

function formatNumber(num) {
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function getRiskColor(account) {
  if (account.error || !account.balance) return 'text-gray-400'
  const ratio = account.balance.risk_ratio || 0
  if (account.is_mt5_account) {
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

/**
 * 从账户列表中提取强平价，写入全局 strategy store。
 * MarketCards 订阅该 store，在行情卡片的实时价格两侧展示。
 *
 * 逻辑参考原 getLiquidationPrice，但直接返回数值（null = 暂无）。
 */
function calcFallbackLiq(positions, balance, isMT5) {
  let longEntry = 0, longQty = 0, shortEntry = 0, shortQty = 0
  for (const p of (positions || [])) {
    const size = Math.abs(parseFloat(p.size || p.volume || 0))
    const entry = parseFloat(p.entry_price || p.price_open || 0)
    if (size <= 0 || entry <= 0) continue
    const side = (p.side || '').toLowerCase()
    const pType = p.type  // MT5: 0=buy, 1=sell
    const isLong = side === 'buy' || side === 'long' || pType === 0
    const isShort = side === 'sell' || side === 'short' || pType === 1
    if (isLong) { longEntry += entry * size; longQty += size }
    if (isShort) { shortEntry += entry * size; shortQty += size }
  }

  let longLiq = null, shortLiq = null

  if (isMT5) {
    // MT5 cross-margin: liq = avg_entry +/- safety_buffer / (contract_unit * lots)
    const equity = parseFloat(balance.equity || balance.net_assets || 0)
    const marginUsed = parseFloat(balance.margin_balance || balance.margin_used || 0)
    const convFactor = 100  // default for XAU; ideally from pair config
    const safetyBuffer = equity - marginUsed * 0.5
    if (longQty > 0) {
      const avgEntry = longEntry / longQty
      longLiq = avgEntry - safetyBuffer / (convFactor * longQty)
      if (longLiq <= 0) longLiq = null
    }
    if (shortQty > 0) {
      const avgEntry = shortEntry / shortQty
      shortLiq = avgEntry + safetyBuffer / (convFactor * shortQty)
    }
  } else {
    // Binance: prefer cross-margin formula using wallet balance data
    const wallet = parseFloat(balance.total_wallet_balance || 0)
    const maint = parseFloat(balance.total_maint_margin || 0)
    const lev = parseFloat(balance.leverage || 0)

    if (wallet > 0 && (wallet - maint) > 0) {
      // Cross-margin: liq = avg_entry -/+ (wallet - maint_margin) / qty
      const buffer = wallet - maint
      if (longQty > 0) {
        const avgEntry = longEntry / longQty
        longLiq = avgEntry - buffer / longQty
        if (longLiq <= 0) longLiq = null
      }
      if (shortQty > 0) {
        const avgEntry = shortEntry / shortQty
        shortLiq = avgEntry + buffer / shortQty
      }
    } else if (lev > 0) {
      // Isolated fallback: simplified liq = entry * (1 -/+ 1/lev)
      if (longQty > 0) {
        const avgEntry = longEntry / longQty
        longLiq = avgEntry * (1 - 1 / lev)
      }
      if (shortQty > 0) {
        const avgEntry = shortEntry / shortQty
        shortLiq = avgEntry * (1 + 1 / lev)
      }
    }
  }
  return { longLiq, shortLiq }
}

function syncLiquidationPricesToStore(accounts) {
  console.log('[LIQ_DEBUG] syncLiq called, accounts:', accounts.length, accounts.map(a => ({name: a.account_name, pid: a.platform_id, pair: a.pair_code, mt5: a.is_mt5_account, ll: a.balance?.long_liquidation_price, sl: a.balance?.short_liquidation_price})))
  // Group by pair_code, then aggregate per platform within each pair
  const pairGroups = {}  // { pairCode: { binance: {long, short}, mt5: {long, short} } }

  for (const acc of accounts) {
    if (acc.error || !acc.balance) continue
    const b = acc.balance
    const pairCode = acc.pair_code
    if (!pairCode) continue

    if (!pairGroups[pairCode]) {
      pairGroups[pairCode] = {
        binance: { long: null, short: null },
        mt5:     { long: null, short: null },
      }
    }
    const pg = pairGroups[pairCode]

    const isBinance = acc.platform_id === PlatformId.BINANCE
    const isMT5 = acc.is_mt5_account && isHedge(acc.platform_id)

    if (isBinance || isMT5) {
      let longLiq  = b.long_liquidation_price  > 0 ? b.long_liquidation_price  : null
      let shortLiq = b.short_liquidation_price > 0 ? b.short_liquidation_price : null
      // Tier 2: self-calculated fallback
      if (!longLiq || !shortLiq) {
        const fb = calcFallbackLiq(acc.positions, b, isMT5)
        if (!longLiq && fb.longLiq)   longLiq  = fb.longLiq
        if (!shortLiq && fb.shortLiq) shortLiq = fb.shortLiq
      }
      const slot = isBinance ? pg.binance : pg.mt5
      if (longLiq && (!slot.long || longLiq > slot.long)) slot.long = longLiq
      if (shortLiq && (!slot.short || shortLiq < slot.short)) slot.short = shortLiq
    }
  }

  // Write each pair_code to store
  for (const [pairCode, pg] of Object.entries(pairGroups)) {
    console.log('[LIQ_DEBUG] writing to store:', pairCode, JSON.stringify(pg))
    strategyStore.setLiquidationPrices(pairCode, 'binance', pg.binance.long, pg.binance.short)
    strategyStore.setLiquidationPrices(pairCode, 'mt5', pg.mt5.long, pg.mt5.short)
  }
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
