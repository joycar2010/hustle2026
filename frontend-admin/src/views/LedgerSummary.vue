<template>
  <div class="min-h-screen bg-dark-300 text-text-primary p-4 md:p-6">
    <!-- 合计卡 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
        <div class="text-xs text-text-tertiary">纳管账户数</div>
        <div class="text-xl font-bold text-text-primary mt-1">{{ total.users || 0 }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
        <div class="text-xs text-text-tertiary">预设值合计</div>
        <div class="text-xl font-bold text-text-primary mt-1 font-mono">{{ fmt(total.baseline) }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
        <div class="text-xs text-text-tertiary">最新总额合计</div>
        <div class="text-xl font-bold text-text-primary mt-1 font-mono">{{ fmt(total.latest) }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-3">
        <div class="text-xs text-text-tertiary">累计纯收益合计</div>
        <div class="text-xl font-bold mt-1 font-mono" :class="pnlCls(total.cumulative_pnl)">{{ fmtPnl(total.cumulative_pnl) }}</div>
      </div>
    </div>

    <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
      <div class="px-4 py-3 border-b border-border-primary flex items-center">
        <span class="text-sm font-bold text-text-primary">手工对账汇总(各主账户 · 点击行展开明细)</span>
        <button @click="load" class="ml-auto text-xs px-3 py-1 bg-dark-200 hover:bg-dark-50 rounded-lg text-text-secondary">刷新</button>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[720px]">
          <thead>
            <tr class="text-xs text-text-tertiary border-b border-border-primary">
              <th class="text-left py-2.5 px-4">账户</th>
              <th class="text-right py-2.5 px-4">预设值</th>
              <th class="text-right py-2.5 px-4">最新总额</th>
              <th class="text-right py-2.5 px-4">累计纯收益</th>
              <th class="text-right py-2.5 px-4">笔数</th>
              <th class="text-left py-2.5 px-4">起始日</th>
              <th class="text-left py-2.5 px-4">最后记账</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="it in items" :key="it.username">
              <tr class="border-b border-border-primary/50 hover:bg-dark-200 cursor-pointer" @click="toggle(it.username)">
                <td class="py-2.5 px-4 font-medium text-text-primary">
                  <span class="inline-block w-3 text-text-tertiary">{{ expanded === it.username ? '▾' : '▸' }}</span>
                  {{ it.username }}
                </td>
                <td class="py-2.5 px-4 text-right font-mono text-text-secondary">{{ fmt(it.baseline) }}</td>
                <td class="py-2.5 px-4 text-right font-mono text-text-secondary">{{ fmt(it.latest) }}</td>
                <td class="py-2.5 px-4 text-right font-mono font-semibold" :class="pnlCls(it.cumulative_pnl)">{{ fmtPnl(it.cumulative_pnl) }}</td>
                <td class="py-2.5 px-4 text-right text-text-tertiary">{{ it.entry_count }}</td>
                <td class="py-2.5 px-4 text-text-tertiary text-xs">{{ it.first_date }}</td>
                <td class="py-2.5 px-4 text-text-tertiary text-xs">{{ it.last_date }}</td>
              </tr>
              <tr v-if="expanded === it.username">
                <td colspan="7" class="bg-dark-200 px-4 py-2">
                  <div v-if="detailLoading" class="text-xs text-text-tertiary py-2">加载中…</div>
                  <table v-else class="w-full text-xs">
                    <thead>
                      <tr class="text-text-tertiary border-b border-border-primary">
                        <th class="text-left py-1.5">日期</th>
                        <th class="text-right py-1.5">总金额</th>
                        <th class="text-right py-1.5">日纯收益</th>
                        <th class="text-right py-1.5">系统日收益</th>
                        <th class="text-right py-1.5">对账差值</th>
                        <th class="text-left py-1.5 pl-4">备注</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="e in detail" :key="e.entry_date" class="border-b border-border-primary/30">
                        <td class="py-1.5">{{ e.entry_date }}<span v-if="e.is_baseline" class="ml-1 text-primary">(预设)</span></td>
                        <td class="py-1.5 text-right font-mono text-text-secondary">{{ fmt(e.total_amount) }}</td>
                        <td class="py-1.5 text-right font-mono" :class="e.is_baseline ? 'text-text-tertiary' : pnlCls(e.daily_pnl)">{{ e.is_baseline ? '—' : fmtPnl(e.daily_pnl) }}</td>
                        <td class="py-1.5 text-right font-mono text-text-tertiary">{{ e.sys_pnl === null ? '—' : fmtPnl(e.sys_pnl) }}</td>
                        <td class="py-1.5 text-right font-mono" :class="diffCls(e.diff)">{{ e.diff === null ? '—' : fmtPnl(e.diff) }}</td>
                        <td class="py-1.5 pl-4 text-text-tertiary">{{ e.note || '' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
            <tr v-if="!items.length">
              <td colspan="7" class="py-10 text-center text-text-tertiary text-sm">暂无手工记账数据(用户在 test 站录入后此处汇总)</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api.js'

const items = ref([])
const total = ref({})
const expanded = ref(null)
const detail = ref([])
const detailLoading = ref(false)

function fmt(v) { return v === null || v === undefined ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPnl(v) { if (v === null || v === undefined) return '—'; const n = Number(v); return (n > 0 ? '+' : '') + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function pnlCls(v) { return v > 0 ? 'text-success' : v < 0 ? 'text-danger' : 'text-text-tertiary' }
function diffCls(v) { if (v === null) return 'text-text-tertiary'; return Math.abs(v) < 1 ? 'text-text-tertiary' : 'text-warning' }

async function load() {
  try { const r = await api.get('/api/v1/ai-arb/ledger-summary'); items.value = r.data.items || []; total.value = r.data.total || {} }
  catch (e) { console.error(e) }
}
async function toggle(username) {
  if (expanded.value === username) { expanded.value = null; return }
  expanded.value = username; detail.value = []; detailLoading.value = true
  try { const r = await api.get('/api/v1/ai-arb/ledger-detail', { params: { username } }); detail.value = r.data.entries || [] }
  catch (e) { console.error(e) } finally { detailLoading.value = false }
}
onMounted(load)
</script>
