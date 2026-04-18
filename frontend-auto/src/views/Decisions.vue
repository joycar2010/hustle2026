<template>
  <div class="space-y-3">
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary flex justify-between items-center">
      <div>
        <h2 class="font-semibold">决策流</h2>
        <div class="text-xs text-text-tertiary mt-1">每 5 秒刷新 · 共 {{ items.length }} 条</div>
      </div>
      <div class="flex flex-col gap-2 text-xs">
        <div class="flex gap-2 items-center">
          <span class="text-text-tertiary">目标:</span>
          <button @click="selectedTarget = null"
            class="px-2 py-1 rounded text-[11px]"
            :class="selectedTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">全部</button>
          <button v-for="t in targets" :key="t.id" @click="selectedTarget = t.id"
            class="px-2 py-1 rounded text-[11px]"
            :class="selectedTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">
            {{ t.username }}/{{ t.pair_code }}
          </button>
        </div>
        <div class="flex gap-2">
          <button v-for="f in filters" :key="f" @click="active=f"
            class="px-3 py-1.5 rounded border" :class="active===f ? 'bg-primary text-dark-300 border-primary' : 'border-border-primary text-text-secondary hover:bg-dark-200'">
            {{ f }} <span class="opacity-60 ml-1">{{ counts[f] || 0 }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-dark-200 text-text-tertiary">
          <tr class="text-left">
            <th class="px-3 py-2">#</th>
            <th>时间</th>
            <th>目标</th>
            <th>触发</th>
            <th>动作</th>
            <th>腿</th>
            <th>数量</th>
            <th>conf</th>
            <th>判决</th>
            <th>tokens</th>
            <th>ms</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="d in filtered" :key="d.id">
            <tr class="border-t border-border-primary hover:bg-dark-200 cursor-pointer" @click="toggle(d.id)">
              <td class="px-3 py-2 font-mono text-text-tertiary">{{ d.id }}</td>
              <td class="font-mono text-text-tertiary">{{ fmtTime(d.created_at) }}</td>
              <td class="text-text-tertiary text-[11px]">
                <span v-if="d.username" class="font-semibold text-text-secondary">{{ d.username }}</span>
                <span v-if="d.pair_code" class="font-mono text-primary">/{{ d.pair_code }}</span>
                <span v-if="!d.username" class="text-text-tertiary">—</span>
              </td>
              <td class="text-text-secondary">{{ d.trigger }}</td>
              <td><span class="font-mono" :class="actionColor(d.action)">{{ d.action }}</span></td>
              <td class="font-mono text-text-tertiary">{{ d.leg }}</td>
              <td class="font-mono">{{ d.qty }}</td>
              <td class="font-mono text-text-tertiary">{{ Number(d.confidence||0).toFixed(2) }}</td>
              <td><span class="px-1.5 py-0.5 rounded text-[10px]" :class="verdictBadge(d.verdict)">{{ d.verdict }}</span></td>
              <td class="font-mono text-text-tertiary">{{ (d.tokens_in||0)+(d.tokens_out||0) }}</td>
              <td class="font-mono text-text-tertiary">{{ d.latency_ms }}</td>
            </tr>
            <tr v-if="expanded === d.id" class="bg-dark-200">
              <td colspan="11" class="p-3 space-y-2">
                <div>
                  <div class="text-text-tertiary text-[10px] mb-1">REASON</div>
                  <div class="text-text-primary text-xs whitespace-pre-wrap">{{ d.reason || '(空)' }}</div>
                </div>
                <div v-if="d.reject_reason">
                  <div class="text-danger text-[10px] mb-1">REJECT_REASON</div>
                  <div class="text-danger text-xs font-mono">{{ d.reject_reason }}</div>
                </div>
                <div v-if="d.execution_result">
                  <div class="text-success text-[10px] mb-1">EXECUTION_RESULT</div>
                  <pre class="text-[10px] text-text-secondary bg-dark-300 p-2 rounded overflow-x-auto">{{ JSON.stringify(d.execution_result, null, 2) }}</pre>
                </div>
                <div v-if="d.verdict==='pending'" class="flex gap-2 pt-2 border-t border-border-primary">
                  <button @click.stop="approve(d.id)" class="px-3 py-1.5 bg-success text-dark-300 rounded font-semibold text-xs hover:opacity-90">批准并执行</button>
                  <button @click.stop="reject(d.id)" class="px-3 py-1.5 bg-danger text-white rounded font-semibold text-xs hover:opacity-90">拒绝</button>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-if="filtered.length===0" class="p-6 text-center text-text-tertiary text-sm">无符合条件决策</div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'

const items = ref([])
const expanded = ref(null)
const active = ref('全部')
const targets = ref([])
const selectedTarget = ref(null)
const filters = ['全部', 'executed', 'shadow', 'pending', 'rejected']

const counts = computed(() => {
  const c = { '全部': items.value.length }
  for (const it of items.value) c[it.verdict] = (c[it.verdict] || 0) + 1
  return c
})
const filtered = computed(() => active.value === '全部' ? items.value : items.value.filter(d => d.verdict === active.value))

function fmtTime(t) { return dayjs(t).format('MM-DD HH:mm:ss') }
function toggle(id) { expanded.value = expanded.value === id ? null : id }
function actionColor(a) {
  if (a === 'noop') return 'text-text-tertiary'
  if (a?.startsWith('open')) return 'text-primary'
  if (a?.startsWith('close') || a === 'partial_reduce') return 'text-blue-400'
  if (a === 'rebalance') return 'text-yellow-400'
  return 'text-text-primary'
}
function verdictBadge(v) {
  return ({
    executed: 'bg-success/20 text-success',
    shadow: 'bg-yellow-900/30 text-yellow-400',
    pending: 'bg-blue-900/30 text-blue-400',
    rejected: 'bg-danger/20 text-danger',
    skipped: 'bg-dark-200 text-text-tertiary',
  })[v] || 'bg-dark-200 text-text-tertiary'
}
async function refresh() {
  try {
    const tid = selectedTarget.value
    const [r, ts] = await Promise.all([
      api.get('/api/v1/agent/decisions?limit=100' + (tid != null ? '&target_id=' + tid : '')),
      targets.value.length === 0 ? api.get('/api/v1/agent/scope/targets').catch(() => null) : Promise.resolve(null),
    ])
    items.value = r.data?.items || []
    if (ts) targets.value = ts.data?.items?.filter(t => t.enabled) || []
  } catch (e) { console.error(e) }
}
async function approve(id) {
  if (!confirm(`批准决策 #${id} 并立即执行？`)) return
  try { await api.post(`/api/v1/agent/decisions/${id}/approve`); await refresh() }
  catch (e) { alert('批准失败: ' + (e.response?.data?.detail || e.message)) }
}
async function reject(id) {
  if (!confirm(`拒绝决策 #${id}？`)) return
  try { await api.post(`/api/v1/agent/decisions/${id}/reject`, { reason: '操作员拒绝' }); await refresh() }
  catch (e) { alert('拒绝失败: ' + (e.response?.data?.detail || e.message)) }
}
import { watch as _watch } from 'vue'
_watch(selectedTarget, () => refresh())
let timer
onMounted(() => { refresh(); timer = setInterval(refresh, 5000) })
onUnmounted(() => clearInterval(timer))
</script>
