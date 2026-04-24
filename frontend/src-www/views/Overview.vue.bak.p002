<template>
  <div class="pb-20 md:pb-6">
    <!-- PC 顶部导航 -->
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 bg-gradient-to-br from-primary to-primary-hover rounded-lg flex items-center justify-center">
          <span class="text-dark-300 font-bold">H</span>
        </div>
        <span class="font-semibold">HustleXAU · 实时收益</span>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-text-secondary">{{ auth.user?.username }}</span>
        <div class="w-2 h-2 rounded-full animate-pulse" :class="connected ? 'bg-green-500' : 'bg-red-500'" :title="connected ? '实时更新中' : '连接断开'"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
        <button @click="auth.logout(); $router.push('/login')" class="text-sm text-text-tertiary hover:text-danger transition-colors">退出</button>
      </div>
    </header>

    <!-- 移动端顶部 -->
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3 flex items-center justify-between">
      <span class="font-semibold text-sm">实时收益</span>
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="connected ? 'bg-green-500' : 'bg-red-500'"></div>
        <span class="text-xs text-text-tertiary">{{ lastUpdate }}</span>
      </div>
    </div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-6xl mx-auto">

      <!-- 合计汇总 -->
      <div v-if="accounts.length" class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <div v-for="s in summaryCards" :key="s.label" class="bg-dark-100 rounded-xl p-3.5 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-0.5">{{ s.label }}</div>
          <div class="text-lg font-bold font-mono" :class="s.color">{{ s.value }}</div>
        </div>
      </div>

      <!-- 账户卡片 -->
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

        <div v-for="acc in accounts" :key="acc.account_id"
          class="bg-dark-100 rounded-2xl border border-border-primary p-5 hover:border-border-focus transition-all"
          :class="{ 'opacity-60': acc._error }">

          <div class="flex items-start justify-between mb-4">
            <div>
              <div class="font-semibold text-text-primary">{{ acc.account_name }}</div>
              <div class="flex items-center gap-1.5 mt-1">
                <span class="px-1.5 py-0.5 rounded text-xs" :class="acc.is_mt5_account ? 'bg-purple-900/40 text-purple-300' : 'bg-blue-900/40 text-blue-300'">
                  {{ acc.is_mt5_account ? 'MT5' : platformName(acc.platform_id) }}
                </span>
                <span v-if="acc.account_role" class="px-1.5 py-0.5 rounded text-xs bg-yellow-900/40 text-yellow-300">
                  {{ acc.account_role === 'primary' ? '主' : '对冲' }}
                </span>
                <span :class="!acc._error && acc.is_active !== false ? 'text-success' : 'text-text-tertiary'" class="text-xs">
                  {{ acc._error ? '● 异常' : acc.is_active !== false ? '● 正常' : '○ 未启用' }}
                </span>
              </div>
            </div>
            <div class="text-right">
              <div class="text-xs text-text-tertiary mb-0.5">当日盈亏</div>
              <div class="text-xl font-bold font-mono" :class="pnlColor(getDailyPnl(acc))">
                {{ pnlStr(getDailyPnl(acc)) }}
              </div>
            </div>
          </div>

          <div v-if="acc._error" class="text-xs text-red-400 mb-2 truncate" :title="acc._error">{{ acc._error }}</div>

          <div class="space-y-2.5">
            <div class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">总资产</span>
              <span class="font-mono font-semibold text-text-primary">{{ fmtUSDT(getBal(acc, 'total_assets')) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">可用资产</span>
              <span class="font-mono text-text-secondary">{{ fmtUSDT(getBal(acc, 'available_balance')) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">净资产</span>
              <span class="font-mono text-text-secondary">{{ fmtUSDT(getBal(acc, 'net_assets')) }}</span>
            </div>
            <div v-if="getBal(acc, 'unrealized_pnl') != null" class="flex justify-between items-center">
              <span class="text-xs text-text-tertiary">未实现盈亏</span>
              <span class="font-mono text-sm" :class="pnlColor(getBal(acc, 'unrealized_pnl'))">{{ pnlStr(getBal(acc, 'unrealized_pnl')) }}</span>
            </div>

            <div v-if="getRisk(acc) > 0" class="pt-1">
              <div class="flex justify-between items-center mb-1">
                <span class="text-xs text-text-tertiary">风险率</span>
                <span class="text-xs font-mono" :class="riskColor(getRisk(acc))">{{ getRisk(acc).toFixed(1) }}%</span>
              </div>
              <div class="h-1.5 bg-dark-300 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all duration-500"
                  :class="riskBarColor(getRisk(acc))"
                  :style="{ width: Math.min(getRisk(acc), 100) + '%' }"></div>
              </div>
            </div>

            <div v-if="(acc.positions || []).length > 0" class="flex justify-between items-center pt-1 border-t border-border-secondary">
              <span class="text-xs text-text-tertiary">当前持仓</span>
              <span class="font-mono text-xs text-primary">{{ acc.positions.length }} 笔</span>
            </div>
          </div>
        </div>
      </div>

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
const summary = ref(null)
const lastUpdate = ref('--')
const connected = ref(false)
let timer = null

const summaryCards = computed(() => {
  const s = summary.value
  if (!s) {
    const sum = (f) => accounts.value.reduce((t, a) => t + (parseFloat(a.balance?.[f] ?? a[f] ?? 0) || 0), 0)
    const pnl = sum('daily_pnl')
    return [
      { label: '总资产合计', value: fmtUSDT(sum('total_assets')), color: 'text-text-primary' },
      { label: '可用资产',   value: fmtUSDT(sum('available_balance')), color: 'text-text-secondary' },
      { label: '净资产合计', value: fmtUSDT(sum('net_assets')), color: 'text-text-secondary' },
      { label: '当日总盈亏', value: pnlStr(pnl), color: pnlColor(pnl) },
    ]
  }
  return [
    { label: '总资产合计', value: fmtUSDT(s.total_assets), color: 'text-text-primary' },
    { label: '可用资产',   value: fmtUSDT(s.available_balance), color: 'text-text-secondary' },
    { label: '净资产合计', value: fmtUSDT(s.net_assets), color: 'text-text-secondary' },
    { label: '当日总盈亏', value: pnlStr(s.daily_pnl), color: pnlColor(s.daily_pnl) },
  ]
})

/**
 * 获取聚合数据 — backend 已按账户逐个查询 MT5 bridge
 * 每个 MT5 账户连接自己的 bridge 端口，数据已经隔离。
 * 不再单独调用 /mt5/account/info（那是导致数据交叉污染的 bug）
 */
async function fetchData() {
  try {
    const r = await api.get('/api/v1/accounts/dashboard/aggregated')
    const d = r.data

    if (d.summary) summary.value = d.summary

    const all = []
    if (d.accounts && Array.isArray(d.accounts)) all.push(...d.accounts)
    if (d.failed_accounts && Array.isArray(d.failed_accounts)) {
      for (const fa of d.failed_accounts) all.push({ ...fa, _error: fa.error || '数据获取失败' })
    }
    // Legacy flat array fallback
    if (Array.isArray(d) && !d.summary) all.push(...d)

    if (all.length > 0) accounts.value = all
    connected.value = true
    lastUpdate.value = dayjs().format('HH:mm:ss')
  } catch (e) {
    console.error('fetchData error:', e)
    connected.value = false
    if (e.response?.status === 401) { auth.logout(); return }
  } finally {
    loading.value = false
  }
}

function getBal(acc, field) {
  if (acc.balance?.[field] != null) return parseFloat(acc.balance[field])
  if (acc[field] != null) return parseFloat(acc[field])
  return null
}

function getDailyPnl(acc) {
  if (acc.daily_pnl != null && acc.daily_pnl !== 0) return parseFloat(acc.daily_pnl)
  return getBal(acc, 'daily_pnl') ?? getBal(acc, 'unrealized_pnl')
}

function getRisk(acc) {
  const v = getBal(acc, 'risk_ratio')
  return (v != null && !isNaN(v)) ? v : 0
}

function platformName(id) { return { 1: 'Binance', 2: 'Bybit', 3: 'IC Markets' }[id] || 'Unknown' }

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
