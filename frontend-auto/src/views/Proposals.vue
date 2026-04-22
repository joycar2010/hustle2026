<template>
  <div class="space-y-4">
    <!-- Header + filters -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary flex flex-wrap justify-between items-center gap-3">
      <div>
        <h2 class="font-semibold">策略提议中心</h2>
        <div class="text-xs text-text-tertiary mt-1">
          已加载 {{ items.length }} 条 · Codex/操作员发起的配置变更，批准后写入
          <span class="font-mono">agent_active_config</span> / <span class="font-mono">agent_target_config</span>
        </div>
      </div>
      <div class="flex flex-wrap gap-2 text-xs items-center">
        <span class="text-text-tertiary">目标:</span>
        <button @click="setTarget(null)"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">全部</button>
        <button v-for="t in targets" :key="t.id" @click="setTarget(t.id)"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">
          {{ t.username }}/{{ t.pair_code }}
        </button>
        <span class="text-text-tertiary">|</span>
        <button v-for="f in filters" :key="f.key" @click="setStatus(f.key)"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterStatus === f.key ? statusActiveClass(f.key) : 'bg-dark-200 text-text-secondary'">
          {{ f.label }}
        </button>
        <input v-model="searchText" @keyup.enter="reload()" placeholder="标题 / 推理"
          class="bg-dark-200 border border-border-primary rounded px-2 py-1 w-44">
        <button @click="reload()" class="px-3 py-1 rounded bg-primary text-dark-300 font-semibold">应用</button>
        <button @click="showCreate = !showCreate" class="ml-2 px-3 py-1.5 rounded bg-success text-dark-300 font-semibold text-xs">
          {{ showCreate ? '取消' : '+ 新建提议' }}
        </button>
      </div>
    </div>

    <!-- Create form -->
    <div v-if="showCreate" class="bg-dark-100 rounded-xl p-5 border border-border-primary space-y-3">
      <h3 class="font-semibold">新建策略提议</h3>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div class="lg:col-span-2">
          <div class="text-xs text-text-tertiary mb-1">标题</div>
          <input v-model="newProp.title" placeholder="例如: 提高 GBXAU 极端模式下单笔上限至 15%"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">作用范围</div>
          <select v-model="newProp.target_id"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
            <option :value="null">全局（所有目标）</option>
            <option v-for="t in targets" :key="t.id" :value="t.id">
              {{ t.username }} / {{ t.pair_code }} · #{{ t.id }}
            </option>
          </select>
        </div>
        <div class="lg:col-span-3">
          <div class="text-xs text-text-tertiary mb-1">业务推理</div>
          <textarea v-model="newProp.rationale" rows="2"
            placeholder="为什么要改、预期收益、风险点"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none font-mono"></textarea>
        </div>
        <div class="lg:col-span-3">
          <div class="text-xs text-text-tertiary mb-1">config_diff (JSON)</div>
          <textarea v-model="newProp.config_diff_text" rows="5"
            placeholder='{"position_caps":{"single_trade_pct":0.15,"total_position_pct":0.5,"daily_volume_pct":5.0}}'
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none font-mono"></textarea>
          <div v-if="newProp.json_err" class="text-danger text-xs mt-1">JSON 解析失败: {{ newProp.json_err }}</div>
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">预计仓位占比 (可选)</div>
          <input v-model.number="newProp.est_position_pct" type="number" step="0.01" min="0" max="1"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
        </div>
        <div class="lg:col-span-2 flex items-end gap-2">
          <button @click="submitCreate" class="px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover text-sm">提交待审批</button>
          <button @click="showCreate = false" class="px-4 py-2 bg-dark-200 text-text-secondary rounded text-sm">取消</button>
        </div>
      </div>
    </div>

    <!-- Proposals table -->
    <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-dark-200 text-text-tertiary">
          <tr class="text-left">
            <th class="px-3 py-2">#</th>
            <th>创建</th>
            <th>作用范围</th>
            <th>标题</th>
            <th>预计仓位</th>
            <th>状态</th>
            <th>审核时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="p in items" :key="p.id">
            <tr class="border-t border-border-primary hover:bg-dark-200 cursor-pointer" @click="toggle(p.id)">
              <td class="px-3 py-2 font-mono text-text-tertiary">#{{ p.id }}</td>
              <td class="font-mono text-text-tertiary" :title="p.created_at">{{ fmtTime(p.created_at) }}</td>
              <td>
                <span v-if="p.target_id" class="px-1.5 py-0.5 rounded text-[10px] bg-primary/20 text-primary">
                  {{ p.username }}/{{ p.pair_code }}
                </span>
                <span v-else class="px-1.5 py-0.5 rounded text-[10px] bg-dark-300 text-text-secondary">全局</span>
              </td>
              <td>{{ p.title }}</td>
              <td class="font-mono">{{ p.est_position_pct ? (p.est_position_pct * 100).toFixed(1) + '%' : '--' }}</td>
              <td><span class="px-1.5 py-0.5 rounded text-[10px]" :class="statusBadge(p.status)">{{ p.status }}</span></td>
              <td class="font-mono text-text-tertiary text-[10px]">{{ p.reviewed_at ? fmtTime(p.reviewed_at) : '—' }}</td>
              <td @click.stop>
                <div v-if="p.status === 'pending'" class="flex gap-1">
                  <button @click="approve(p)" class="px-2 py-0.5 bg-success/20 text-success rounded text-[10px] hover:bg-success/30">批准</button>
                  <button @click="reject(p)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">拒绝</button>
                </div>
              </td>
            </tr>
            <tr v-if="expanded === p.id" class="bg-dark-200">
              <td colspan="8" class="p-4 space-y-4">
                <!-- Rationale -->
                <div>
                  <div class="text-text-tertiary text-[10px] mb-1">RATIONALE</div>
                  <div class="text-text-primary text-xs whitespace-pre-wrap leading-relaxed">{{ p.rationale || '(空)' }}</div>
                </div>

                <!-- Config diff card grid -->
                <div>
                  <div class="text-text-tertiary text-[10px] mb-2">CONFIG_DIFF (顶层 key 即将写入 active config)</div>
                  <div v-if="!p.config_diff || !Object.keys(p.config_diff).length" class="text-text-tertiary text-[11px]">(空 diff)</div>
                  <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div v-for="(val, key) in p.config_diff" :key="key"
                         class="bg-dark-300 rounded p-3 border border-border-primary">
                      <div class="flex items-baseline justify-between mb-1">
                        <span class="font-mono text-[11px] text-primary font-semibold">{{ key }}</span>
                        <span class="text-[10px] text-text-tertiary">{{ summarizeType(val) }}</span>
                      </div>
                      <div v-if="isLeaf(val)" class="font-mono text-xs text-text-primary">{{ formatLeaf(val) }}</div>
                      <div v-else class="space-y-0.5">
                        <div v-for="(sv, sk) in val" :key="sk" class="flex justify-between text-[11px] gap-3">
                          <span class="text-text-secondary font-mono">{{ sk }}</span>
                          <span class="text-text-primary font-mono text-right">{{ formatLeaf(sv) }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Audit timeline (who approved / rejected) -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <div class="text-text-tertiary text-[10px]">审计轨迹</div>
                    <button v-if="!auditMap[p.id]" @click="loadAudit(p.id)"
                      class="text-[10px] text-primary hover:underline">查看</button>
                  </div>
                  <div v-if="auditLoading[p.id]" class="text-text-tertiary text-[11px]">加载中…</div>
                  <div v-else-if="auditMap[p.id]" class="space-y-1">
                    <div v-if="auditMap[p.id].length === 0" class="text-text-tertiary text-[11px]">无审计记录</div>
                    <div v-for="a in auditMap[p.id]" :key="a.id"
                         class="flex items-center gap-3 text-[11px] bg-dark-300 rounded px-2 py-1">
                      <span class="font-mono text-text-tertiary">{{ fmtTime(a.created_at) }}</span>
                      <span class="px-1.5 py-0.5 rounded text-[10px]" :class="auditActionBadge(a.action)">{{ a.action }}</span>
                      <span class="text-text-secondary">操作员：<span class="font-semibold">{{ a.actor_username || (a.actor_user_id || '').slice(0, 8) || '—' }}</span></span>
                      <span v-if="a.diff_keys && a.diff_keys.length" class="text-text-tertiary">
                        影响键：<span class="font-mono">{{ a.diff_keys.join(', ') }}</span>
                      </span>
                      <span v-if="a.reason" class="text-danger italic">理由：{{ a.reason }}</span>
                    </div>
                  </div>
                </div>

                <!-- Source decisions -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <div class="text-text-tertiary text-[10px]">关联决策（同一目标 · 提议创建前 24h）</div>
                    <button v-if="!sourceMap[p.id]" @click="loadSource(p.id)"
                      class="text-[10px] text-primary hover:underline">查看</button>
                  </div>
                  <div v-if="sourceLoading[p.id]" class="text-text-tertiary text-[11px]">加载中…</div>
                  <div v-else-if="sourceMap[p.id]" class="max-h-64 overflow-y-auto">
                    <div v-if="sourceMap[p.id].length === 0" class="text-text-tertiary text-[11px]">无关联决策（可能是全局提议或 24h 内无决策）</div>
                    <table v-else class="w-full text-[11px]">
                      <thead class="text-text-tertiary">
                        <tr><th class="text-left py-1">#</th><th>时间</th><th>触发</th><th>动作</th><th>conf</th><th>判决</th><th>原因</th></tr>
                      </thead>
                      <tbody>
                        <tr v-for="sd in sourceMap[p.id]" :key="sd.id" class="border-t border-border-primary">
                          <td class="py-1 font-mono text-text-tertiary">{{ sd.id }}</td>
                          <td class="font-mono text-text-tertiary">{{ fmtTime(sd.created_at) }}</td>
                          <td class="text-text-secondary">{{ sd.trigger }}</td>
                          <td class="font-mono">{{ sd.action }}</td>
                          <td class="font-mono text-text-tertiary">{{ Number(sd.confidence||0).toFixed(2) }}</td>
                          <td><span class="px-1 py-0.5 rounded text-[10px]" :class="verdictBadge(sd.verdict)">{{ sd.verdict }}</span></td>
                          <td class="text-text-secondary truncate max-w-[260px]" :title="sd.reject_reason || sd.reason">{{ sd.reject_reason || sd.reason }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-if="items.length === 0 && !loading" class="p-6 text-center text-text-tertiary text-sm">无符合条件的提议</div>
      <div v-if="loading" class="p-4 text-center text-text-tertiary text-sm">加载中…</div>
      <div v-if="hasMore && !loading" class="p-3 text-center">
        <button @click="loadMore()" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-300 text-text-secondary rounded text-xs">加载更多</button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'
import { useWsStream } from '@/stores/wsStream.js'

const PAGE = 50
const filters = [
  { key: '全部', label: '全部' },
  { key: 'pending', label: 'pending' },
  { key: 'approved', label: 'approved' },
  { key: 'rejected', label: 'rejected' },
  { key: 'rolled_back', label: 'rolled_back' },
]

const items = ref([])
const targets = ref([])
const expanded = ref(null)
const showCreate = ref(false)
const filterStatus = ref('pending')
const filterTarget = ref(null)
const searchText = ref('')
const hasMore = ref(false)
const nextCursor = ref(null)
const loading = ref(false)
const sourceMap = ref({})
const sourceLoading = ref({})
const auditMap = ref({})
const auditLoading = ref({})

const newProp = ref({
  title: '', rationale: '', config_diff_text: '', target_id: null,
  est_position_pct: null, json_err: null,
})

function fmtTime(t) { return dayjs(t).format('MM-DD HH:mm') }
function toggle(id) { expanded.value = expanded.value === id ? null : id }
function statusBadge(s) {
  return ({
    pending: 'bg-blue-900/30 text-blue-400',
    approved: 'bg-success/20 text-success',
    rejected: 'bg-danger/20 text-danger',
    rolled_back: 'bg-warning/20 text-warning',
  })[s] || 'bg-dark-300 text-text-tertiary'
}
function statusActiveClass(s) {
  return ({
    pending:  'bg-blue-900/40 text-blue-400 font-semibold',
    approved: 'bg-success/30 text-success font-semibold',
    rejected: 'bg-danger/30 text-danger font-semibold',
    rolled_back: 'bg-warning/30 text-warning font-semibold',
  })[s] || 'bg-primary text-dark-300 font-semibold'
}
function verdictBadge(v) {
  return ({
    executed: 'bg-success/20 text-success',
    shadow: 'bg-yellow-900/30 text-yellow-400',
    pending: 'bg-blue-900/30 text-blue-400',
    rejected: 'bg-danger/20 text-danger',
  })[v] || 'bg-dark-200 text-text-tertiary'
}

function isLeaf(v) {
  return v == null || typeof v !== 'object' || Array.isArray(v)
}
function summarizeType(v) {
  if (v == null) return 'null'
  if (typeof v === 'boolean') return 'bool'
  if (typeof v === 'number') return 'number'
  if (typeof v === 'string') return 'string'
  if (Array.isArray(v)) return 'array(' + v.length + ')'
  return 'object(' + Object.keys(v).length + ')'
}
function formatLeaf(v) {
  if (v == null) return 'null'
  if (Array.isArray(v)) return '[' + v.map(formatLeaf).join(', ') + ']'
  if (typeof v === 'number') {
    // Auto-percent obvious 0~1 ratios
    if (v > 0 && v <= 1) return v + ''
    return v + ''
  }
  return String(v)
}

function _params({ cursor } = {}) {
  const p = { limit: PAGE, status_filter: filterStatus.value === '全部' ? 'all' : filterStatus.value }
  if (filterTarget.value != null) p.target_id = filterTarget.value
  if (cursor != null) p.cursor = cursor
  if (searchText.value) p.q = searchText.value
  return p
}

async function reload() {
  loading.value = true
  try {
    const r = await api.get('/api/v1/agent/proposals', { params: _params() })
    items.value = r.data?.items || []
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}
async function loadMore() {
  if (!hasMore.value || loading.value || nextCursor.value == null) return
  loading.value = true
  try {
    const r = await api.get('/api/v1/agent/proposals', { params: _params({ cursor: nextCursor.value }) })
    const seen = new Set(items.value.map(x => x.id))
    for (const it of (r.data?.items || [])) if (!seen.has(it.id)) items.value.push(it)
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function loadSource(pid) {
  if (sourceMap.value[pid] || sourceLoading.value[pid]) return
  sourceLoading.value[pid] = true
  try {
    const r = await api.get('/api/v1/agent/proposals/' + pid + '/source-decisions', { params: { limit: 50 } })
    sourceMap.value[pid] = r.data?.items || []
  } catch (e) { sourceMap.value[pid] = [] }
  finally { sourceLoading.value[pid] = false }
}

async function loadAudit(pid) {
  if (auditMap.value[pid] || auditLoading.value[pid]) return
  auditLoading.value[pid] = true
  try {
    const r = await api.get('/api/v1/agent/proposals/' + pid + '/audit')
    auditMap.value[pid] = r.data?.items || []
  } catch (e) { auditMap.value[pid] = [] }
  finally { auditLoading.value[pid] = false }
}
function auditActionBadge(a) {
  return ({
    approved: 'bg-success/20 text-success',
    rejected: 'bg-danger/20 text-danger',
    created:  'bg-blue-900/30 text-blue-400',
    rolled_back: 'bg-warning/20 text-warning',
  })[a] || 'bg-dark-300 text-text-tertiary'
}

function setStatus(s) { filterStatus.value = s; reload() }
function setTarget(tid) { filterTarget.value = tid; reload() }

async function submitCreate() {
  newProp.value.json_err = null
  let diff
  try { diff = JSON.parse(newProp.value.config_diff_text) }
  catch (e) { newProp.value.json_err = e.message; return }
  if (!newProp.value.title || !newProp.value.rationale) {
    alert('请填写标题和推理'); return
  }
  try {
    await api.post('/api/v1/agent/proposals', {
      title: newProp.value.title,
      rationale: newProp.value.rationale,
      config_diff: diff,
      target_id: newProp.value.target_id,
      est_position_pct: newProp.value.est_position_pct,
    })
    newProp.value = { title: '', rationale: '', config_diff_text: '', target_id: null, est_position_pct: null, json_err: null }
    showCreate.value = false
    await reload()
  } catch (e) { alert('创建失败: ' + (e.response?.data?.detail || e.message)) }
}

async function approve(p) {
  const scope = p.target_id ? '目标 #' + p.target_id + ' (' + p.username + '/' + p.pair_code + ')' : '全局（所有目标）'
  if (!confirm('批准并立即热加载提议 #' + p.id + '？\n作用范围: ' + scope + '\n影响键: ' + Object.keys(p.config_diff || {}).join(', '))) return
  try { await api.post('/api/v1/agent/strategy-proposals/' + p.id + '/approve'); await reload() }
  catch (e) { alert('批准失败: ' + (e.response?.data?.detail || e.message)) }
}
async function reject(p) {
  if (!confirm('拒绝提议 #' + p.id + '？')) return
  try { await api.post('/api/v1/agent/strategy-proposals/' + p.id + '/reject', { reason: '操作员拒绝' }); await reload() }
  catch (e) { alert('拒绝失败: ' + (e.response?.data?.detail || e.message)) }
}

const ws = useWsStream()
let timer, wsStop
onMounted(async () => {
  try {
    const ts = await api.get('/api/v1/agent/scope/targets')
    targets.value = ts.data?.items?.filter(t => t.enabled) || []
  } catch {}
  await reload()
  timer = setInterval(reload, 30000)  // slower HTTP safety poll; WS is primary
  ws.connect()
  ws.subscribe('agent.proposals')
  wsStop = watch(() => ws.channels['agent.proposals'], (payload) => {
    // Any lifecycle event (approved / rejected / created) — invalidate list
    // and any cached audit for the affected id.
    if (!payload) return
    if (payload.id != null) {
      delete auditMap.value[payload.id]
    }
    reload()
  })
})
onUnmounted(() => {
  clearInterval(timer)
  try { ws.unsubscribe('agent.proposals') } catch {}
  if (wsStop) wsStop()
})
</script>
