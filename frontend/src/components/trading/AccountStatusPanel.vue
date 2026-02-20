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
                @click="toggleConnection(account.account_id, account.is_active)"
                class="px-2 py-1 text-xs rounded transition-colors"
                :class="account.is_active ? 'bg-[#f6465d] hover:bg-[#e03d52]' : 'bg-[#0ecb81] hover:bg-[#0db774]'"
              >
                {{ account.is_active ? '断开' : '连接' }}
              </button>
              <button
                @click="toggleDisable(account.account_id, account.is_active)"
                class="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-700 rounded transition-colors"
              >
                {{ account.is_active ? '禁用' : '启用' }}
              </button>
              <button
                @click="deleteAccount(account.account_id, account.account_name)"
                class="px-2 py-1 text-xs bg-[#f6465d] hover:bg-[#e03d52] rounded transition-colors"
              >
                删除
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
            <span class="font-mono">{{ formatNumber(account.balance?.total_assets || 0) }} USDT</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">可用总资产</span>
            <span class="font-mono">{{ formatNumber(account.balance?.available_balance || 0) }} USDT</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">净资产</span>
            <span class="font-mono">{{ formatNumber(account.balance?.net_assets || 0) }} USDT</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">总持仓</span>
            <span class="font-mono">{{ formatNumber(account.balance?.margin_balance || 0) }} USDT</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">冻结资产</span>
            <span class="font-mono">{{ formatNumber(account.balance?.frozen_assets || 0) }} USDT</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">当日盈亏</span>
            <span class="font-mono" :class="account.daily_pnl >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
              {{ account.daily_pnl >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(account.daily_pnl || 0)) }} USDT
            </span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">保证金余额</span>
            <span class="font-mono">{{ formatNumber(account.balance?.margin_balance || 0) }} USDT</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">风险率</span>
            <span class="font-mono" :class="getRiskColor(account.balance?.risk_ratio || 0)">
              {{ (account.balance?.risk_ratio || 0).toFixed(2) }}%
            </span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-400">{{ account.platform_id === 1 ? '掉期费(Binance)' : '资金费(Bybit)' }}</span>
            <span class="font-mono text-gray-400">
              0.00 USDT
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

const totalProfit = ref(0)
const activeAccounts = ref([])
const systemAlerts = ref([])

let updateInterval = null

onMounted(() => {
  fetchAccountData()
  updateInterval = setInterval(fetchAccountData, 5000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

    if (data.summary) {
      // Update total profit (daily P&L)
      totalProfit.value = data.summary.daily_pnl || 0
    }

    // Combine successful and failed accounts
    const allAccounts = []

    // Add successful accounts with balance data
    if (data.accounts && data.accounts.length > 0) {
      allAccounts.push(...data.accounts.map(acc => ({
        ...acc,
        is_active: acc.is_active !== undefined ? acc.is_active : true  // Use backend's is_active value
      })))
    }

    // Add failed accounts with placeholder data
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
            risk_ratio: 0
          },
          daily_pnl: 0,
          error: failedAcc.error
        })
      }
    }

    activeAccounts.value = allAccounts

    // Generate system alerts based on real data
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

async function toggleConnection(accountId, currentStatus) {
  console.log('[toggleConnection] Called with:', { accountId, currentStatus })

  if (!accountId) {
    console.error('[toggleConnection] Account ID is missing')
    alert('错误: 账户ID缺失')
    return
  }

  try {
    const newStatus = !currentStatus
    console.log('[toggleConnection] Sending API request:', {
      url: `/api/v1/accounts/${accountId}`,
      data: { is_active: newStatus }
    })

    const response = await api.put(`/api/v1/accounts/${accountId}`, {
      is_active: newStatus
    })

    console.log('[toggleConnection] API response:', response.data)

    // Refresh account data immediately
    await fetchAccountData()

    console.log(`[toggleConnection] Account ${accountId} ${newStatus ? 'connected' : 'disconnected'}`)
    alert(`账户已${newStatus ? '连接' : '断开'}`)
  } catch (error) {
    console.error('[toggleConnection] Error:', error)
    console.error('[toggleConnection] Error response:', error.response)
    alert(`操作失败: ${error.response?.data?.detail || error.message}`)
  }
}

async function toggleDisable(accountId, currentStatus) {
  try {
    const newStatus = !currentStatus
    await api.put(`/api/v1/accounts/${accountId}`, {
      is_active: newStatus
    })

    // Refresh account data immediately
    await fetchAccountData()

    console.log(`Account ${accountId} ${newStatus ? 'enabled' : 'disabled'}`)
  } catch (error) {
    console.error('Failed to toggle disable:', error)
    alert(`操作失败: ${error.response?.data?.detail || error.message}`)
  }
}

async function deleteAccount(accountId, accountName) {
  if (!confirm(`确定要删除账户 "${accountName}" 吗？此操作不可恢复。`)) {
    return
  }

  try {
    await api.delete(`/api/v1/accounts/${accountId}`)

    // Refresh account data immediately
    await fetchAccountData()

    console.log(`Account ${accountId} deleted`)
    alert('账户已成功删除')
  } catch (error) {
    console.error('Failed to delete account:', error)
    alert(`删除失败: ${error.response?.data?.detail || error.message}`)
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
</script>
