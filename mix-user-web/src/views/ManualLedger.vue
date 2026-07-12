<template>
  <div class="pb-20 md:pb-6 px-4 pt-4 max-w-3xl mx-auto">
    <!-- 汇总卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <div class="bg-[#1e2329] rounded-xl p-3">
        <div class="text-xs text-gray-400">预设值{{ summary.baseline_date ? '('+summary.baseline_date+')' : '' }}</div>
        <div class="text-lg font-semibold mt-1">{{ fmt(summary.baseline) }}</div>
      </div>
      <div class="bg-[#1e2329] rounded-xl p-3">
        <div class="text-xs text-gray-400">最新总金额</div>
        <div class="text-lg font-semibold mt-1">{{ fmt(summary.latest) }}</div>
      </div>
      <div class="bg-[#1e2329] rounded-xl p-3">
        <div class="text-xs text-gray-400">累计纯收益</div>
        <div class="text-lg font-semibold mt-1" :class="pnlColor(summary.cumulative_pnl)">{{ fmtPnl(summary.cumulative_pnl) }}</div>
      </div>
      <div class="bg-[#1e2329] rounded-xl p-3">
        <div class="text-xs text-gray-400">记录笔数</div>
        <div class="text-lg font-semibold mt-1">{{ summary.entry_count || 0 }}</div>
      </div>
    </div>

    <!-- 录入框 -->
    <div class="bg-[#1e2329] rounded-xl p-4 mb-4">
      <div class="text-sm font-semibold mb-3">{{ summary.entry_count ? '记一笔(同日重录=覆盖)' : '先设总金额预设值(第一笔)' }}</div>
      <div class="flex flex-wrap gap-2 items-center">
        <input v-model="form.date" type="date" class="bg-[#2b3139] rounded-lg px-3 py-2 text-sm outline-none" />
        <input v-model.number="form.amount" type="number" step="0.01" min="0" placeholder="当日总金额"
               class="bg-[#2b3139] rounded-lg px-3 py-2 text-sm outline-none w-36" />
        <input v-model="form.note" type="text" maxlength="200" placeholder="备注(选填)"
               class="bg-[#2b3139] rounded-lg px-3 py-2 text-sm outline-none flex-1 min-w-[8rem]" />
        <button @click="save" :disabled="saving || form.amount === null || form.amount === ''"
                class="bg-[#f0b90b] text-black rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-40">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
      <div v-if="msg" class="text-xs mt-2" :class="msgErr ? 'text-[#f6465d]' : 'text-[#0ecb81]'">{{ msg }}</div>
    </div>

    <!-- 月份筛选 -->
    <div class="flex items-center gap-2 mb-3">
      <select v-model="month" @change="load" class="bg-[#2b3139] rounded-lg px-3 py-1.5 text-sm outline-none">
        <option value="">全部</option>
        <option v-for="m in monthOptions" :key="m" :value="m">{{ m }}</option>
      </select>
      <span class="text-xs text-gray-500">对账差值 = 手工日收益 − 系统日收益</span>
    </div>

    <!-- 明细表 -->
    <div class="bg-[#1e2329] rounded-xl overflow-x-auto">
      <table class="w-full text-sm min-w-[560px]">
        <thead>
          <tr class="text-xs text-gray-400 border-b border-[#2b3139]">
            <th class="text-left py-2.5 px-3">日期</th>
            <th class="text-right py-2.5 px-3">总金额</th>
            <th class="text-right py-2.5 px-3">日纯收益</th>
            <th class="text-right py-2.5 px-3">系统日收益</th>
            <th class="text-right py-2.5 px-3">对账差值</th>
            <th class="text-left py-2.5 px-3">备注</th>
            <th class="py-2.5 px-2"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in entries" :key="e.entry_date" class="border-b border-[#2b3139]/60 hover:bg-[#2b3139]/30">
            <td class="py-2.5 px-3 whitespace-nowrap">
              {{ e.entry_date }}
              <span v-if="e.is_baseline" class="ml-1 text-[10px] text-[#f0b90b] border border-[#f0b90b]/50 rounded px-1">预设</span>
            </td>
            <td class="py-2.5 px-3 text-right">{{ fmt(e.total_amount) }}</td>
            <td class="py-2.5 px-3 text-right" :class="e.is_baseline ? 'text-gray-500' : pnlColor(e.daily_pnl)">
              {{ e.is_baseline ? '—' : fmtPnl(e.daily_pnl) }}
            </td>
            <td class="py-2.5 px-3 text-right text-gray-400">{{ e.sys_pnl === null ? '—' : fmtPnl(e.sys_pnl) }}</td>
            <td class="py-2.5 px-3 text-right" :class="diffColor(e.diff)">{{ e.diff === null ? '—' : fmtPnl(e.diff) }}</td>
            <td class="py-2.5 px-3 text-gray-400 max-w-[10rem] truncate">{{ e.note || '' }}</td>
            <td class="py-2.5 px-2 text-right whitespace-nowrap">
              <button @click="edit(e)" class="text-xs text-gray-400 hover:text-white mr-2">改</button>
              <button @click="del(e)" class="text-xs text-[#f6465d]/70 hover:text-[#f6465d]">删</button>
            </td>
          </tr>
          <tr v-if="!entries.length && !loading">
            <td colspan="7" class="py-8 text-center text-gray-500 text-sm">暂无记录 — 先在上方录入总金额预设值</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api.js'

const entries = ref([])
const summary = ref({})
const month = ref('')
const loading = ref(false)
const saving = ref(false)
const msg = ref('')
const msgErr = ref(false)
const form = ref({ date: new Date().toISOString().slice(0, 10), amount: null, note: '' })

const monthOptions = computed(() => {
  const s = new Set(entries.value.map(e => e.entry_date.slice(0, 7)))
  if (month.value) s.add(month.value)
  return [...s].sort().reverse()
})

function fmt(v) { return v === null || v === undefined ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPnl(v) { if (v === null || v === undefined) return '—'; const n = Number(v); return (n > 0 ? '+' : '') + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function pnlColor(v) { return v > 0 ? 'text-[#0ecb81]' : v < 0 ? 'text-[#f6465d]' : 'text-gray-400' }
function diffColor(v) { if (v === null) return 'text-gray-500'; return Math.abs(v) < 1 ? 'text-gray-400' : 'text-[#f0b90b]' }

async function load() {
  loading.value = true
  try {
    const r = await api.get('/api/v1/manual-ledger/entries' + (month.value ? `?month=${month.value}` : ''))
    entries.value = r.data.entries || []
    summary.value = r.data.summary || {}
  } catch (e) { console.error(e) } finally { loading.value = false }
}

async function save() {
  saving.value = true; msg.value = ''
  try {
    const r = await api.post('/api/v1/manual-ledger/entries', {
      entry_date: form.value.date, total_amount: form.value.amount, note: form.value.note || null,
    })
    msgErr.value = false
    msg.value = r.data.is_baseline ? '预设值已保存' : `已保存,当日纯收益 ${fmtPnl(r.data.daily_pnl)}`
    form.value.amount = null; form.value.note = ''
    await load()
  } catch (e) {
    msgErr.value = true
    msg.value = e?.response?.data?.detail || '保存失败'
  } finally { saving.value = false }
}

function edit(e) {
  form.value = { date: e.entry_date, amount: e.total_amount, note: e.note || '' }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function del(e) {
  if (!confirm(`删除 ${e.entry_date} 的记录?后续日收益将自动重算`)) return
  try { await api.delete(`/api/v1/manual-ledger/entries/${e.entry_date}`); await load() }
  catch (er) { alert(er?.response?.data?.detail || '删除失败') }
}

onMounted(load)
</script>
