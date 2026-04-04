<template>
  <div class="pb-20 md:pb-6">
    <!-- PC / 平板 顶部导航 -->
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 bg-gradient-to-br from-primary to-primary-hover rounded-lg flex items-center justify-center">
          <span class="text-dark-300 font-bold">H</span>
        </div>
        <span class="font-semibold">HustleXAU · 实时收益</span>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-text-secondary">{{ auth.user?.username }}</span>
        <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse" title="实时更新中"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
        <button @click="auth.logout(); $router.push('/login')" class="text-sm text-text-tertiary hover:text-danger transition-colors">退出</button>
      </div>
    </header>

    <!-- 移动端顶部标题 -->
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3 flex items-center justify-between">
      <span class="font-semibold text-sm">实时收益</span>
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
      </div>
    </div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-6xl mx-auto">

      <!-- 合计汇总条 -->
      <div v-if="accounts.length" class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <div v-for="s in summaryCards" :key="s.label" class="bg-dark-100 rounded-xl p-3.5 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-0.5">{{ s.label }}</div>
          <div class="text-lg font-bold font-mono" :class="s.color">{{ s.value }}</div>
        </div>
      </div>

      <!-- 账户卡片网格 - 响应式列数 -->
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        <div v-if="loading" class="col-span-full flex justify-center py-16">
          <svg class="w-8 h-8 animate-spin text-primary" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        </div>

        <div v-else-if="!accounts.length" class="col-span-full text-center py-16 text-text-tertiary">
          <div class="text-4xl mb-3">📊</div>
          <div>暂无关联账户</div>
          <div class="text-xs mt-1">请联系管理员绑定交易账户</div>
        </div>

        <!-- 账户卡片 -->
        <div v-for="acc in accounts" :key="acc.account_id || acc.id"
          class="bg-dark-100 rounded-2xl border border-border-primary p-5 hover:border-border-focus transition-all">

          <!-- 卡片头部 -->
          <div class="flex items-start justify-between mb-4">
            <div>
              <div class="font-semibold text-text-primary">{{ acc.account_name }}</div>
              <div class="flex items-center gap-1.5 mt-1">
                <span class="px-1.5 py-0.5 rounded text-xs" :class="acc.is_mt5_account ? 'bg-purple-900/40 text-purple-300' : 'bg-blue-900/40 text-blue-300'">
                  {{ acc.is_mt5_account ? 'MT5' : 'Binance' }}
                </span>
                <span v-if="!acc._error" :class="acc.is_active !== false ? 'text-success' : 'text-text-tertiary'" class="text-xs">
                  {{ acc.is_active !== false ? '● 正常' : '○ 未启用' }}
                </span>
                <span v-else class="text-xs text-red-400">● 连接异常</span>
              </div>
            </div>
            <!-- 当日盈亏大字 -->
            <div class="text-right">
              <div class="text-xs text-text-tertiary mb-0.5">当日盈亏</div>
              <div class="text-xl font-bold font-mono" :class="pnlColor(acc.unrealized_pnl ?? acc.daily_pnl)">
                {{ pnlStr(acc.unrealized_pnl ?? acc.daily_pnl) }}
              </div>
            </div>
          </div>

          <!-- IP白名单/API错误提示 -->
          <div v-if="acc._error" class="mb-4 p-3 rounded-xl border" :class="acc._error.startsWith('IP_WHITELIST:') ? 'bg-red-950/40 border-red-800/50 text-red-300' : 'bg-yellow-950/40 border-yellow-800/50 text-yellow-300'">
            <div class="flex items-center gap-1.5 font-semibold text-xs mb-1">
              <svg class="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
              <span>{{ acc._error.startsWith('IP_WHITELIST:') ? 'IP白名单未配置' : '数据获取失败' }}</span>
            </div>
            <div class="text-xs leading-relaxed opacity-90">{{ acc._error.startsWith('IP_WHITELIST:') ? acc._error.substring(13) : acc._error }}</div>
          </div>

          <!-- 资金数据 -->
            <div class="space-y-2.5">
            <div class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">总资产</span>
              <span class="font-mono font-semibold text-text-primary">{{ fmtUSDT(acc.balance?.total_assets ?? acc.total_equity ?? acc.total_assets) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">可用资产</span>
              <span class="font-mono text-text-secondary">{{ fmtUSDT(acc.balance?.available_balance ?? acc.available_balance ?? acc.available_assets) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">净资产</span>
              <span class="font-mono text-text-secondary">{{ fmtUSDT(acc.balance?.net_assets ?? acc.net_equity ?? acc.net_assets) }}</span>
            </div>

            <!-- 风险率进度条（如有） -->
            <div v-if="(acc.balance?.risk_ratio ?? acc.risk_rate) != null" class="pt-1">
              <div class="flex justify-between items-center mb-1">
                <span class="text-xs text-text-tertiary">风险率</span>
                <span class="text-xs font-mono" :class="riskColor(acc.balance?.risk_ratio ?? acc.risk_rate)">{{ (acc.balance?.risk_ratio ?? acc.risk_rate)?.toFixed(1) }}%</span>
              </div>
              <div class="h-1.5 bg-dark-300 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all duration-500"
                  :class="riskBarColor(acc.balance?.risk_ratio ?? acc.risk_rate)"
                  :style="{ width: Math.min(acc.balance?.risk_ratio ?? acc.risk_rate, 100) + '%' }"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 最后更新时间 -->
      <div class="mt-6 text-center text-xs text-text-tertiary">
        数据每 5 秒自动更新 · 最后更新: {{ lastUpdate }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

const auth = useAuthStore()
const loading = ref(true)
const accounts = ref([])
const lastUpdate = ref('--')
let timer = null

const summaryCards = computed(() => {
  // Read from nested balance object first, fall back to top-level fields
  const sum = (field, alt) => accounts.value.reduce((s, a) => {
    const v = parseFloat(a.balance?.[field] ?? a.balance?.[alt] ?? a[field] ?? a[alt] ?? 0) || 0
    return s + v
  }, 0)
  const pnl = sum('unrealized_pnl', 'daily_pnl') || sum('daily_pnl', 'unrealized_pnl')
  return [
    { label: '总资产合计', value: fmtUSDT(sum('total_assets', 'total_equity')), color: 'text-text-primary' },
    { label: '可用资产',   value: fmtUSDT(sum('available_balance', 'available_assets')), color: 'text-text-secondary' },
    { label: '净资产合计', value: fmtUSDT(sum('net_assets', 'net_equity')), color: 'text-text-secondary' },
    { label: '当日总盈亏', value: pnlStr(pnl), color: pnlColor(pnl) },
  ]
})

async function fetchData() {
  try {
    const r = await api.get('/api/v1/accounts/summary')
    const d = r.data
    if (Array.isArray(d)) {
      accounts.value = d
    } else {
      // Merge successful + failed accounts so both are displayed
      const all = []
      if (d.accounts && d.accounts.length > 0) {
        all.push(...d.accounts)
      }
      if (d.failed_accounts && d.failed_accounts.length > 0) {
        all.push(...d.failed_accounts.map(a => ({
          ...a,
          _error: a.error,
          balance: { total_assets: 0, available_balance: 0, net_assets: 0, margin_balance: 0, risk_ratio: null },
        })))
      }
      if (all.length > 0) {
        accounts.value = all
      } else {
        throw new Error('no accounts in response')
      }
    }

    // Enrich MT5 accounts with live bridge data (Python returns balance=0 for MT5)
    const mt5List = accounts.value.filter(a => a.is_mt5_account)
    if (mt5List.length > 0) {
      try {
        const infoR = await api.get('/api/v1/mt5/account/info')
        const info = infoR.data || {}
        mt5List.forEach(acc => {
          if (!acc.balance) acc.balance = {}
          acc.balance.total_assets      = info.equity      ?? info.balance ?? 0
          acc.balance.available_balance = info.margin_free ?? 0
          acc.balance.net_assets        = info.equity      ?? 0
          acc.balance.margin_balance    = info.margin      ?? 0
          acc.balance.unrealized_pnl    = info.profit      ?? 0
          acc.balance.daily_pnl         = info.profit      ?? 0
          acc.balance.risk_ratio        = info.margin_level ?? 0
        })
      } catch (e) {
        console.error('MT5 bridge info failed:', e)
      }
    }

    lastUpdate.value = dayjs().format('HH:mm:ss')
  } catch (e) {
    try {
      const r2 = await api.get('/api/v1/accounts')
      accounts.value = Array.isArray(r2.data) ? r2.data : r2.data?.accounts || []
    } catch (e2) {
      console.error('fetchData error:', e2)
    }
  } finally {
    loading.value = false
    lastUpdate.value = dayjs().format('HH:mm:ss')
  }
}

function fmtUSDT(v) {
  if (v == null || isNaN(v)) return '--'
  return parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' U'
}
function pnlStr(v) {
  if (v == null || isNaN(v)) return '--'
  const n = parseFloat(v)
  return (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' U'
}
function pnlColor(v) { return !v || isNaN(v) ? 'text-text-tertiary' : parseFloat(v) >= 0 ? 'text-success' : 'text-danger' }
function riskColor(v) { return v < 50 ? 'text-success' : v < 80 ? 'text-warning' : 'text-danger' }
function riskBarColor(v) { return v < 50 ? 'bg-success' : v < 80 ? 'bg-warning' : 'bg-danger' }

onMounted(() => { fetchData(); timer = setInterval(fetchData, 5000) })
onUnmounted(() => clearInterval(timer))
</script>
