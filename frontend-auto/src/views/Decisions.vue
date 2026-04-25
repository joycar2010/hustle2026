<template>
  <div class="space-y-3">
    <!-- Header + approx count -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary flex flex-wrap justify-between items-center gap-3">
      <div>
        <h2 class="font-semibold">决策流</h2>
        <div class="text-xs text-text-tertiary mt-1">
          已加载 {{ items.length }} / 约 {{ totalApprox || '—' }} 条 · 头部每 5s 自动刷新
        </div>
      </div>
      <div class="flex items-center gap-2 text-xs">
        <span class="text-text-tertiary">目标:</span>
        <button @click="setTarget(null)"
          class="px-2 py-1 rounded text-[11px]"
          :class="selectedTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">全部</button>
        <button v-for="t in targets" :key="t.id" @click="setTarget(t.id)"
          class="px-2 py-1 rounded text-[11px]"
          :class="selectedTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">
          {{ t.username }}/{{ t.pair_code }}
        </button>
      </div>
    </div>

    <!-- Decision Pipeline Visualization -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-semibold text-text-tertiary">决策管线 · {{ windowKey }}</h3>
        <span class="text-[10px] text-text-tertiary">{{ pipelineStats.total }} 条决策</span>
      </div>
      <div class="flex items-center gap-1">
        <!-- Stage: Signal -->
        <div class="flex-1 text-center">
          <div class="bg-blue-900/30 rounded-lg px-3 py-2 border border-blue-500/30">
            <div class="text-[10px] text-blue-400 mb-0.5">信号触发</div>
            <div class="font-mono font-bold text-lg text-blue-400">{{ pipelineStats.total }}</div>
            <div class="text-[9px] text-text-tertiary mt-0.5">
              <span v-for="(cnt, trig) in pipelineStats.topTriggers" :key="trig" class="inline-block mr-1">{{ trig }}:{{ cnt }}</span>
            </div>
          </div>
        </div>
        <div class="text-text-tertiary text-lg">→</div>
        <!-- Stage: LLM -->
        <div class="flex-1 text-center">
          <div class="bg-purple-900/30 rounded-lg px-3 py-2 border border-purple-500/30">
            <div class="text-[10px] text-purple-400 mb-0.5">LLM 分析</div>
            <div class="font-mono font-bold text-lg text-purple-400">{{ pipelineStats.llmProcessed }}</div>
            <div class="text-[9px] text-text-tertiary mt-0.5">
              avg conf: {{ pipelineStats.avgConf }}% · {{ pipelineStats.avgLatency }}ms
            </div>
          </div>
        </div>
        <div class="text-text-tertiary text-lg">→</div>
        <!-- Stage: Guard -->
        <div class="flex-1 text-center">
          <div class="bg-yellow-900/30 rounded-lg px-3 py-2 border border-yellow-500/30">
            <div class="text-[10px] text-yellow-400 mb-0.5">风控守卫</div>
            <div class="font-mono font-bold text-lg text-yellow-400">{{ pipelineStats.guardPassed }}</div>
            <div class="text-[9px] text-text-tertiary mt-0.5">
              拦截: <span class="text-danger">{{ pipelineStats.guardRejected }}</span> · 通过率: {{ pipelineStats.guardPassRate }}%
            </div>
          </div>
        </div>
        <div class="text-text-tertiary text-lg">→</div>
        <!-- Stage: Verdict -->
        <div class="flex-1 text-center">
          <div class="rounded-lg px-3 py-2 border" :class="pipelineStats.executed > 0 ? 'bg-green-900/30 border-green-500/30' : 'bg-dark-200 border-border-primary'">
            <div class="text-[10px] text-success mb-0.5">最终执行</div>
            <div class="font-mono font-bold text-lg text-success">{{ pipelineStats.executed }}</div>
            <div class="text-[9px] text-text-tertiary mt-0.5">
              shadow: {{ pipelineStats.shadow }} · pending: {{ pipelineStats.pending }}
            </div>
          </div>
        </div>
      </div>
      <!-- Funnel conversion bar -->
      <div class="mt-2 flex items-center gap-1 text-[9px]">
        <span class="text-text-tertiary">转化漏斗:</span>
        <div class="flex-1 h-2 bg-dark-200 rounded-full overflow-hidden flex">
          <div class="bg-success h-full transition-all" :style="{width: pipelineStats.execPct + '%'}" title="executed"></div>
          <div class="bg-yellow-500 h-full transition-all" :style="{width: pipelineStats.shadowPct + '%'}" title="shadow"></div>
          <div class="bg-blue-500 h-full transition-all" :style="{width: pipelineStats.pendingPct + '%'}" title="pending"></div>
          <div class="bg-danger h-full transition-all" :style="{width: pipelineStats.rejPct + '%'}" title="rejected"></div>
        </div>
        <span class="text-success">{{ pipelineStats.execPct }}%执行</span>
        <span class="text-danger">{{ pipelineStats.rejPct }}%拦截</span>
      </div>
    </div>

    <!-- Filter row -->
    <div class="bg-dark-100 rounded-xl p-3 border border-border-primary flex flex-wrap items-center gap-3 text-xs">
      <div class="flex items-center gap-1">
        <span class="text-text-tertiary">判决:</span>
        <button v-for="v in VERDICTS" :key="v" @click="toggleVerdict(v)"
          class="px-2 py-1 rounded"
          :class="selectedVerdicts.includes(v) ? verdictActiveClass(v) : 'bg-dark-200 text-text-secondary'">{{ v }}</button>
      </div>
      <div class="flex items-center gap-1">
        <span class="text-text-tertiary">时间:</span>
        <button v-for="w in WINDOWS" :key="w.key" @click="windowKey = w.key; reload()"
          class="px-2 py-1 rounded"
          :class="windowKey === w.key ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">{{ w.label }}</button>
      </div>
      <div class="flex items-center gap-1">
        <span class="text-text-tertiary">最低置信度:</span>
        <input v-model.number="minConfidence" type="number" step="0.05" min="0" max="1"
          @change="reload()"
          class="w-20 bg-dark-200 border border-border-primary rounded px-2 py-1 font-mono">
      </div>
      <div class="flex items-center gap-1 flex-1 min-w-[180px]">
        <span class="text-text-tertiary">关键字:</span>
        <input v-model="searchText" @keyup.enter="reload()" placeholder="原因 / reject_reason"
          class="flex-1 bg-dark-200 border border-border-primary rounded px-2 py-1">
        <button @click="reload()" class="px-3 py-1 rounded bg-primary text-dark-300 font-semibold">应用</button>
        <button @click="resetFilters()" class="px-3 py-1 rounded bg-dark-200 text-text-secondary">重置</button>
      </div>
    </div>

    <!-- Table -->
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
          <template v-for="d in items" :key="d.id">
            <tr class="border-t border-border-primary hover:bg-dark-200 cursor-pointer" @click="toggle(d.id)">
              <td class="px-3 py-2 font-mono text-text-tertiary">{{ d.id }}</td>
              <td class="font-mono text-text-tertiary" :title="d.created_at">{{ fmtTime(d.created_at) }}</td>
              <td class="text-text-tertiary text-[11px]">
                <span v-if="d.username" class="font-semibold text-text-secondary">{{ d.username }}</span>
                <span v-if="d.pair_code" class="font-mono text-primary">/{{ d.pair_code }}</span>
                <span v-if="!d.username" class="text-text-tertiary">—</span>
              </td>
              <td class="text-text-secondary">
                <span class="mr-1">{{ triggerIcon(d.trigger) }}</span>{{ d.trigger }}
              </td>
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
                <!-- Market Snapshot -->
                <div v-if="d.market_snapshot">
                  <div class="text-text-tertiary text-[10px] mb-1">MARKET_SNAPSHOT</div>
                  <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">即时点差:</span>
                      <span class="font-mono ml-1" :class="Math.abs(d.market_snapshot.spread_now) > 5 ? 'text-danger' : ''">{{ d.market_snapshot.spread_now?.toFixed(2) }}</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">30m均值:</span>
                      <span class="font-mono ml-1">{{ d.market_snapshot.spread_30m_avg?.toFixed(2) }}</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">总权益:</span>
                      <span class="font-mono ml-1">${{ d.market_snapshot.total_equity?.toFixed(2) }}</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">资金费:</span>
                      <span class="font-mono ml-1">{{ (d.market_snapshot.funding_rate * 100)?.toFixed(4) }}%</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">A权益:</span>
                      <span class="font-mono ml-1">${{ d.market_snapshot.a_equity?.toFixed(2) }}</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">B权益:</span>
                      <span class="font-mono ml-1">${{ d.market_snapshot.b_equity?.toFixed(2) }}</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">A仓位:</span>
                      <span class="font-mono ml-1">{{ d.market_snapshot.a_size }}</span>
                    </div>
                    <div class="bg-dark-300 rounded px-2 py-1">
                      <span class="text-text-tertiary">B仓位:</span>
                      <span class="font-mono ml-1">{{ d.market_snapshot.b_size }} × {{ d.market_snapshot.conversion_factor }}</span>
                    </div>
                  </div>
                </div>

                <!-- Confidence gauge -->
                <div v-if="d.confidence">
                  <div class="text-text-tertiary text-[10px] mb-1">LLM CONFIDENCE</div>
                  <div class="flex items-center gap-2">
                    <div class="flex-1 h-2 bg-dark-300 rounded-full overflow-hidden max-w-[200px]">
                      <div class="h-full rounded-full"
                        :class="d.confidence > 0.7 ? 'bg-success' : d.confidence > 0.4 ? 'bg-warning' : 'bg-danger'"
                        :style="{width: (d.confidence * 100) + '%'}"></div>
                    </div>
                    <span class="font-mono text-[11px]">{{ (d.confidence * 100).toFixed(0) }}%</span>
                    <span class="text-[10px] text-text-tertiary">{{ d.confidence > 0.7 ? '高置信' : d.confidence > 0.4 ? '中等' : '低置信' }}</span>
                  </div>
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
      <div v-if="items.length===0 && !loading" class="p-6 text-center text-text-tertiary text-sm">无符合条件决策</div>
      <div v-if="loading" class="p-4 text-center text-text-tertiary text-sm">加载中…</div>
      <div v-if="hasMore && !loading" class="p-3 text-center">
        <button @click="loadMore()" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-300 text-text-secondary rounded text-xs">加载更多</button>
      </div>
      <div v-if="!hasMore && items.length > 0" class="p-3 text-center text-text-tertiary text-[10px]">已到末尾</div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'
import { useWsStream } from '@/stores/wsStream.js'

const VERDICTS = ['executed', 'shadow', 'pending', 'rejected']
const WINDOWS = [
  { key: '1h',  label: '1h' },
  { key: '24h', label: '24h' },
  { key: '7d',  label: '7d' },
  { key: '30d', label: '30d' },
  { key: 'all', label: '全部' },
]
const PAGE = 50

const items = ref([])
const expanded = ref(null)
const targets = ref([])
const selectedTarget = ref(null)
const selectedVerdicts = ref([])
const windowKey = ref('24h')
const minConfidence = ref(null)
const searchText = ref('')
const hasMore = ref(false)
const nextCursor = ref(null)
const totalApprox = ref(null)
const loading = ref(false)

const pipelineStatsData = ref(null)

const pipelineStats = computed(() => {
  const s = pipelineStatsData.value || {}
  const bv = s.by_verdict || {}
  const total = s.total || 0
  const executed = bv.executed || 0
  const shadow = bv.shadow || 0
  const pending = bv.pending || 0
  const rejected = bv.rejected || 0
  const topTriggers = {}
  for (const t of (s.by_trigger || []).slice(0, 3)) topTriggers[t.trigger] = t.count
  return {
    total,
    llmProcessed: total,
    guardPassed: executed + shadow + pending,
    guardRejected: rejected,
    guardPassRate: total ? ((total - rejected) / total * 100).toFixed(0) : 0,
    executed, shadow, pending,
    avgConf: ((s.avg_conf || 0) * 100).toFixed(0),
    avgLatency: s.latency?.avg_ms?.toFixed(0) || s.avg_latency_ms?.toFixed(0) || '--',
    topTriggers,
    execPct: total ? (executed / total * 100).toFixed(1) : 0,
    shadowPct: total ? (shadow / total * 100).toFixed(1) : 0,
    pendingPct: total ? (pending / total * 100).toFixed(1) : 0,
    rejPct: total ? (rejected / total * 100).toFixed(1) : 0,
  }
})

function fmtTime(t) { return dayjs(t).format('MM-DD HH:mm:ss') }
function toggle(id) { expanded.value = expanded.value === id ? null : id }
function triggerIcon(t) {
  if (!t) return ''
  if (t.includes('heartbeat')) return '💓'
  if (t.includes('spread')) return '📊'
  if (t.includes('funding')) return '💰'
  if (t.includes('forced_reduce')) return '🔻'
  if (t.includes('circuit_breaker')) return '⚡'
  if (t.includes('llm_fallback')) return '🔄'
  return '⚙'
}
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
function verdictActiveClass(v) {
  return ({
    executed: 'bg-success/30 text-success font-semibold',
    shadow:   'bg-yellow-900/40 text-yellow-400 font-semibold',
    pending:  'bg-blue-900/40 text-blue-400 font-semibold',
    rejected: 'bg-danger/30 text-danger font-semibold',
  })[v] || 'bg-primary text-dark-300 font-semibold'
}

function toggleVerdict(v) {
  const i = selectedVerdicts.value.indexOf(v)
  if (i >= 0) selectedVerdicts.value.splice(i, 1)
  else selectedVerdicts.value.push(v)
  reload()
}
function setTarget(tid) { selectedTarget.value = tid; reload() }
function resetFilters() {
  selectedVerdicts.value = []
  windowKey.value = '24h'
  minConfidence.value = null
  searchText.value = ''
  reload()
}

function _buildParams({ cursor } = {}) {
  const p = { limit: PAGE }
  if (cursor != null) p.cursor = cursor
  if (selectedTarget.value != null) p.target_id = selectedTarget.value
  if (selectedVerdicts.value.length) p.verdict = selectedVerdicts.value.join(',')
  if (minConfidence.value != null && minConfidence.value !== '') p.min_confidence = minConfidence.value
  if (searchText.value) p.q = searchText.value
  if (windowKey.value && windowKey.value !== 'all') {
    const now = new Date()
    const secs = { '1h': 3600, '24h': 86400, '7d': 604800, '30d': 2592000 }[windowKey.value]
    const from = new Date(now.getTime() - secs * 1000)
    p.from = from.toISOString()
  }
  return p
}

async function loadPipelineStats() {
  try {
    const tid = selectedTarget.value
    const w = windowKey.value
    const tq = tid != null ? '&target_id=' + tid : ''
    const wq = w && w !== 'all' ? '&window=' + w : ''
    const r = await api.get('/api/v1/agent/decisions/stats?' + 'x=1' + wq + tq)
    pipelineStatsData.value = r.data || {}
  } catch {}
}

async function reload() {
  loading.value = true
  loadPipelineStats()
  try {
    const r = await api.get('/api/v1/agent/decisions', { params: _buildParams() })
    items.value = r.data?.items || []
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
    totalApprox.value = r.data?.total_approx ?? null
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}
async function loadMore() {
  if (!hasMore.value || loading.value || nextCursor.value == null) return
  loading.value = true
  try {
    const r = await api.get('/api/v1/agent/decisions', { params: _buildParams({ cursor: nextCursor.value }) })
    const newItems = r.data?.items || []
    // Avoid dupes on slow networks
    const seen = new Set(items.value.map(x => x.id))
    for (const it of newItems) if (!seen.has(it.id)) items.value.push(it)
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function refreshHead() {
  // Tail-poll: only fetch rows newer than items[0]; prepend them.
  // Cheapest: refetch page 1 with current filters, merge on id.
  try {
    const r = await api.get('/api/v1/agent/decisions', { params: _buildParams() })
    const fresh = r.data?.items || []
    if (!fresh.length || !items.value.length) {
      items.value = fresh
      nextCursor.value = r.data?.next_cursor ?? null
      hasMore.value = !!r.data?.has_more
      totalApprox.value = r.data?.total_approx ?? null
      return
    }
    const topId = items.value[0].id
    const added = fresh.filter(x => x.id > topId)
    if (added.length) items.value = [...added, ...items.value]
    totalApprox.value = r.data?.total_approx ?? totalApprox.value
  } catch (e) { /* swallow for background refresh */ }
}

async function approve(id) {
  if (!confirm(`批准决策 #${id} 并立即执行？`)) return
  try { await api.post(`/api/v1/agent/decisions/${id}/approve`); await reload() }
  catch (e) { alert('批准失败: ' + (e.response?.data?.detail || e.message)) }
}
async function reject(id) {
  if (!confirm(`拒绝决策 #${id}？`)) return
  try { await api.post(`/api/v1/agent/decisions/${id}/reject`, { reason: '操作员拒绝' }); await reload() }
  catch (e) { alert('拒绝失败: ' + (e.response?.data?.detail || e.message)) }
}

// Use the WS stream_hub channel agent.decisions for live head updates.
// Falls back to a 30s safety poll in case the socket is down (reconnect is
// handled by wsStream but during backoff we still want fresh data).
const ws = useWsStream()
let safetyTimer
let wsWatchStop = null

function _prependIfNew(d) {
  if (!d || d.id == null) return
  if (items.value.find(x => x.id === d.id)) return
  // Respect currently-applied filters — drop events that wouldn't match.
  if (selectedTarget.value != null && d.target_id !== selectedTarget.value) return
  if (selectedVerdicts.value.length && !selectedVerdicts.value.includes(d.verdict)) return
  items.value = [d, ...items.value]
}

onMounted(async () => {
  try {
    const ts = await api.get('/api/v1/agent/scope/targets')
    targets.value = ts.data?.items?.filter(t => t.enabled) || []
  } catch {}
  await reload()
  ws.connect()
  ws.subscribe('agent.decisions')
  // Whenever the channel payload updates, prepend the new decision
  const { watch } = await import('vue')
  wsWatchStop = watch(() => ws.channels['agent.decisions'], (payload) => {
    if (payload && payload.event === 'decision_new') _prependIfNew(payload)
  })
  // 30s safety poll in case WS is flapping
  safetyTimer = setInterval(refreshHead, 30000)
})
onUnmounted(() => {
  clearInterval(safetyTimer)
  try { ws.unsubscribe('agent.decisions') } catch {}
  if (wsWatchStop) wsWatchStop()
})
</script>
