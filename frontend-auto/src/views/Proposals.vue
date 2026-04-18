<template>
  <div class="space-y-4">
    <!-- Header + filters + create toggle -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary flex flex-wrap justify-between items-center gap-3">
      <div>
        <h2 class="font-semibold">策略提议中心</h2>
        <div class="text-xs text-text-tertiary mt-1">
          Codex 或操作员创建的配置变更提议；批准后写入
          <span class="font-mono">agent_active_config</span>（全局）或
          <span class="font-mono">agent_target_config</span>（单一目标）— 即时热加载，可回滚
        </div>
      </div>
      <div class="flex gap-2 text-xs items-center">
        <span class="text-text-tertiary">目标:</span>
        <button @click="filterTarget = null"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">全部</button>
        <button v-for="t in targets" :key="t.id" @click="filterTarget = t.id"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">
          {{ t.username }}/{{ t.pair_code }}
        </button>
        <span class="text-text-tertiary">|</span>
        <button v-for="f in filters" :key="f" @click="filterStatus = f"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterStatus === f ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">{{ f }}</button>
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
            placeholder="为什么要改、预期收益、风险点（越具体越好，便于审批时判断）"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none font-mono"></textarea>
        </div>
        <div class="lg:col-span-3">
          <div class="text-xs text-text-tertiary mb-1">config_diff (JSON, top-level keys from agent_active_config will be替换)</div>
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
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="p in filtered" :key="p.id">
            <tr class="border-t border-border-primary hover:bg-dark-200 cursor-pointer" @click="toggle(p.id)">
              <td class="px-3 py-2 font-mono text-text-tertiary">#{{ p.id }}</td>
              <td class="font-mono text-text-tertiary">{{ fmtTime(p.created_at) }}</td>
              <td>
                <span v-if="p.target_id" class="px-1.5 py-0.5 rounded text-[10px] bg-primary/20 text-primary">
                  {{ p.username }}/{{ p.pair_code }}
                </span>
                <span v-else class="px-1.5 py-0.5 rounded text-[10px] bg-dark-300 text-text-secondary">全局</span>
              </td>
              <td>{{ p.title }}</td>
              <td class="font-mono">{{ p.est_position_pct ? (p.est_position_pct * 100).toFixed(1) + '%' : '--' }}</td>
              <td><span class="px-1.5 py-0.5 rounded text-[10px]" :class="statusBadge(p.status)">{{ p.status }}</span></td>
              <td @click.stop>
                <div v-if="p.status === 'pending'" class="flex gap-1">
                  <button @click="approve(p)" class="px-2 py-0.5 bg-success/20 text-success rounded text-[10px] hover:bg-success/30">批准</button>
                  <button @click="reject(p)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">拒绝</button>
                </div>
              </td>
            </tr>
            <tr v-if="expanded === p.id" class="bg-dark-200">
              <td colspan="7" class="p-4 space-y-2">
                <div>
                  <div class="text-text-tertiary text-[10px] mb-1">RATIONALE</div>
                  <div class="text-text-primary text-xs whitespace-pre-wrap">{{ p.rationale || '(空)' }}</div>
                </div>
                <div>
                  <div class="text-text-tertiary text-[10px] mb-1">CONFIG_DIFF</div>
                  <pre class="text-[10px] text-text-secondary bg-dark-300 p-2 rounded overflow-x-auto">{{ JSON.stringify(p.config_diff, null, 2) }}</pre>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-if="filtered.length === 0" class="p-6 text-center text-text-tertiary text-sm">无符合条件的提议</div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'

const items = ref([])
const targets = ref([])
const expanded = ref(null)
const showCreate = ref(false)
const filterStatus = ref('全部')
const filterTarget = ref(null)
const filters = ['全部', 'pending', 'approved', 'rejected']

const newProp = ref({
  title: '', rationale: '', config_diff_text: '', target_id: null,
  est_position_pct: null, json_err: null,
})

const filtered = computed(() => items.value.filter(p => {
  if (filterStatus.value !== '全部' && p.status !== filterStatus.value) return false
  if (filterTarget.value !== null && p.target_id !== filterTarget.value) return false
  return true
}))

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

async function refresh() {
  try {
    const statusQs = filterStatus.value === '全部' ? 'all' : filterStatus.value
    const [r, ts] = await Promise.all([
      api.get('/api/v1/agent/proposals?status_filter=' + statusQs),
      targets.value.length === 0 ? api.get('/api/v1/agent/scope/targets').catch(() => null) : Promise.resolve(null),
    ])
    items.value = r.data?.items || []
    if (ts) targets.value = ts.data?.items?.filter(t => t.enabled) || []
  } catch (e) { console.error(e) }
}

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
    await refresh()
  } catch (e) { alert('创建失败: ' + (e.response?.data?.detail || e.message)) }
}

async function approve(p) {
  const scope = p.target_id ? '目标 #' + p.target_id + ' (' + p.username + '/' + p.pair_code + ')' : '全局（所有目标）'
  if (!confirm('批准并立即热加载提议 #' + p.id + '？\n作用范围: ' + scope + '\n影响键: ' + Object.keys(p.config_diff || {}).join(', '))) return
  try { await api.post('/api/v1/agent/strategy-proposals/' + p.id + '/approve'); await refresh() }
  catch (e) { alert('批准失败: ' + (e.response?.data?.detail || e.message)) }
}

async function reject(p) {
  if (!confirm('拒绝提议 #' + p.id + '？')) return
  try { await api.post('/api/v1/agent/strategy-proposals/' + p.id + '/reject', { reason: '操作员拒绝' }); await refresh() }
  catch (e) { alert('拒绝失败: ' + (e.response?.data?.detail || e.message)) }
}

watch([filterStatus, filterTarget], () => refresh())

let timer
onMounted(() => { refresh(); timer = setInterval(refresh, 8000) })
onUnmounted(() => clearInterval(timer))
</script>
