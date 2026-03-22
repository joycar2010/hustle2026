<template>
  <div class="pb-20 md:pb-6">
    <!-- PC 顶部 -->
    <header class="hidden md:flex bg-dark-100 border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40">
      <span class="font-semibold">HustleXAU · 交易历史</span>
      <button @click="auth.logout(); $router.push('/login')" class="text-sm text-text-tertiary hover:text-danger transition-colors">退出</button>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3">
      <span class="font-semibold text-sm">交易历史统计</span>
    </div>

    <div class="px-4 py-4 md:px-6 md:py-6 max-w-5xl mx-auto space-y-5">

      <!-- 查询控件 -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-4">
        <div class="flex flex-wrap gap-3 items-end">
          <div class="flex-1 min-w-36">
            <label class="block text-xs text-text-tertiary mb-1">开始时间</label>
            <input type="datetime-local" v-model="startTime" class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-xl text-sm focus:outline-none focus:border-primary"/>
          </div>
          <div class="flex-1 min-w-36">
            <label class="block text-xs text-text-tertiary mb-1">结束时间</label>
            <input type="datetime-local" v-model="endTime" class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-xl text-sm focus:outline-none focus:border-primary"/>
          </div>
          <div class="flex gap-2 flex-wrap">
            <button @click="setRange(1)"  class="px-3 py-2 bg-dark-200 hover:bg-dark-50 rounded-xl text-xs transition-colors">1天</button>
            <button @click="setRange(7)"  class="px-3 py-2 bg-dark-200 hover:bg-dark-50 rounded-xl text-xs transition-colors">7天</button>
            <button @click="setRange(30)" class="px-3 py-2 bg-dark-200 hover:bg-dark-50 rounded-xl text-xs transition-colors">30天</button>
            <button @click="queryData" :disabled="loading" class="px-4 py-2 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-xl text-sm transition-colors">
              {{ loading ? '查询中...' : '查询' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 统计面板 (与 go站 Trading.vue 一致) -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div v-for="s in statsCards" :key="s.label" class="bg-dark-100 rounded-2xl border border-border-primary p-4">
          <div class="text-xs text-text-tertiary mb-1">{{ s.label }}</div>
          <div class="text-lg md:text-xl font-bold font-mono" :class="s.color">{{ s.value }}</div>
          <div v-if="s.sub" class="text-xs text-text-tertiary mt-0.5">{{ s.sub }}</div>
        </div>
      </div>

      <!-- 交易记录表 -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary overflow-hidden">
        <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
          <span class="font-semibold text-sm">交易记录明细</span>
          <span class="text-xs text-text-tertiary">{{ orders.length }} 条</span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs md:text-sm">
            <thead><tr class="border-b border-border-secondary text-text-tertiary text-xs">
              <th class="text-left px-4 py-2.5">时间</th>
              <th class="text-left px-3 py-2.5">账户</th>
              <th class="text-left px-3 py-2.5">品种</th>
              <th class="text-left px-3 py-2.5">方向</th>
              <th class="text-right px-3 py-2.5">数量</th>
              <th class="text-right px-3 py-2.5">价格</th>
              <th class="text-right px-4 py-2.5">盈亏</th>
            </tr></thead>
            <tbody>
              <tr v-if="loading"><td colspan="7" class="text-center py-10 text-text-tertiary">加载中...</td></tr>
              <tr v-else-if="!orders.length"><td colspan="7" class="text-center py-10 text-text-tertiary">暂无交易记录</td></tr>
              <tr v-for="o in orders" :key="o.id || o.order_id" class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="px-4 py-2.5 font-mono text-text-tertiary whitespace-nowrap">{{ fmtTime(o.created_at || o.filled_at) }}</td>
                <td class="px-3 py-2.5 text-text-secondary">{{ o.account_name || '--' }}</td>
                <td class="px-3 py-2.5 font-medium">{{ o.symbol }}</td>
                <td class="px-3 py-2.5">
                  <span :class="o.side === 'BUY' || o.side === 'buy' ? 'text-success' : 'text-danger'" class="font-semibold">{{ o.side }}</span>
                </td>
                <td class="px-3 py-2.5 text-right font-mono text-text-secondary">{{ o.quantity || o.filled_quantity }}</td>
                <td class="px-3 py-2.5 text-right font-mono text-text-secondary">{{ o.price ? parseFloat(o.price).toFixed(2) : '--' }}</td>
                <td class="px-4 py-2.5 text-right font-mono font-semibold" :class="pnlColor(o.pnl || o.realized_pnl)">
                  {{ pnlStr(o.pnl || o.realized_pnl) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

const auth = useAuthStore()
const loading = ref(false)
const orders = ref([])
const startTime = ref(dayjs().subtract(7, 'day').format('YYYY-MM-DDTHH:mm'))
const endTime   = ref(dayjs().format('YYYY-MM-DDTHH:mm'))

const statsCards = computed(() => {
  const pnls = orders.value.map(o => parseFloat(o.pnl || o.realized_pnl || 0))
  const total = pnls.reduce((s, v) => s + v, 0)
  const wins  = pnls.filter(v => v > 0).length
  const rate  = orders.value.length ? ((wins / orders.value.length) * 100).toFixed(1) : 0
  const bybitVol = orders.value.filter(o => !o.is_mt5).reduce((s, o) => s + parseFloat(o.quantity || 0), 0)
  return [
    { label: '总盈亏 (USDT)', value: (total >= 0 ? '+' : '') + total.toFixed(2), color: total >= 0 ? 'text-success' : 'text-danger' },
    { label: '交易次数',     value: orders.value.length, color: 'text-text-primary' },
    { label: '胜率',         value: rate + '%', color: parseFloat(rate) >= 50 ? 'text-success' : 'text-warning', sub: `${wins} 盈 / ${orders.value.length - wins} 亏` },
    { label: 'Bybit 量',    value: bybitVol.toFixed(4), color: 'text-primary', sub: '张' },
  ]
})

function setRange(days) {
  startTime.value = dayjs().subtract(days, 'day').format('YYYY-MM-DDTHH:mm')
  endTime.value   = dayjs().format('YYYY-MM-DDTHH:mm')
  queryData()
}

async function queryData() {
  loading.value = true
  try {
    const r = await api.get('/api/v1/orders/history', {
      params: { start_time: startTime.value + ':00', end_time: endTime.value + ':00' }
    })
    orders.value = Array.isArray(r.data) ? r.data : r.data?.orders || r.data?.records || []
  } catch {
    try {
      const r2 = await api.get('/api/v1/trading/history', {
        params: { start_time: startTime.value + ':00', end_time: endTime.value + ':00' }
      })
      orders.value = Array.isArray(r2.data) ? r2.data : r2.data?.orders || []
    } catch { orders.value = [] }
  } finally { loading.value = false }
}

function fmtTime(v) { return v ? dayjs(v).format('MM-DD HH:mm') : '--' }
function pnlStr(v) {
  if (v == null || v === '' || isNaN(v)) return '--'
  const n = parseFloat(v)
  return (n >= 0 ? '+' : '') + n.toFixed(2)
}
function pnlColor(v) {
  if (v == null || v === '' || isNaN(v)) return 'text-text-tertiary'
  return parseFloat(v) >= 0 ? 'text-success' : 'text-danger'
}

onMounted(queryData)
</script>
