<template>
  <div class="space-y-4 max-w-6xl">
    <!-- Codex 模型配置 -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <h3 class="font-semibold mb-3 flex items-center justify-between">
        <span>Codex 模型配置</span>
        <span class="text-xs text-text-tertiary">热加载生效，无需重启</span>
      </h3>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-4">
        <div>
          <div class="text-xs text-text-tertiary mb-1">模型</div>
          <select v-model="llm.model" class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
            <option v-for="m in llm.available_models || []" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div class="flex flex-col">
          <div class="text-xs text-text-tertiary mb-1">流式获取</div>
          <label class="flex items-center gap-2 mt-2">
            <input type="checkbox" v-model="llm.streaming" class="accent-primary">
            <span class="text-sm">启用 stream=true</span>
          </label>
        </div>
        <div></div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">已充值额度（{{ llm.currency_symbol || "$" }}，中继原生计价）</div>
          <input v-model.number="llm.recharge_total_cny" type="number" step="1" min="0"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">低额告警阈值（{{ llm.currency_symbol || "$" }}）</div>
          <input v-model.number="llm.balance_alert_threshold_cny" type="number" step="1" min="0"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">换算系数 (raw×x=金额)</div>
          <input v-model.number="llm.usage_multiplier" type="number" step="0.01" min="0"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none"
            placeholder="1.0">
          <div class="text-[10px] text-text-tertiary mt-1">raw={{ stats?.balance?.relay_usage_raw?.toFixed(4) ?? '--' }} · 中继原生 USD=1.0, 人民币折算 ≈7.3</div>
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">货币符号</div>
          <select v-model="llm.currency_symbol"
            class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
            <option value="$">$ USD</option>
            <option value="¥">¥ CNY</option>
          </select>
        </div>
        <div class="flex items-end">
          <button @click="saveLlm" class="w-full px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover">
            保存 LLM 配置
          </button>
        </div>
      </div>
      <div v-if="stats" class="grid grid-cols-2 lg:grid-cols-5 gap-3 text-xs border-t border-border-primary pt-3">
        <div>
          <div class="text-text-tertiary">今日 tokens 总</div>
          <div class="font-mono font-bold text-base">{{ fmtInt(stats.tokens_today?.total) }}</div>
          <div class="text-[10px] text-text-tertiary">{{ stats.tokens_today?.calls }} 次调用</div>
        </div>
        <div>
          <div class="text-text-tertiary">今日 in / out</div>
          <div class="font-mono">{{ fmtInt(stats.tokens_today?.in) }} / {{ fmtInt(stats.tokens_today?.out) }}</div>
        </div>
        <div>
          <div class="text-text-tertiary">累计 tokens</div>
          <div class="font-mono font-bold text-base">{{ fmtInt(stats.tokens_total?.total) }}</div>
          <div class="text-[10px] text-text-tertiary">{{ stats.tokens_total?.calls }} 次</div>
        </div>
        <div>
          <div class="text-text-tertiary">中转站已消耗</div>
          <div class="font-mono font-bold text-base">{{ stats.balance?.currency_symbol || '¥' }}{{ stats.balance?.spent_cny?.toFixed(4) ?? '--' }}</div>
          <div class="text-[10px] text-text-tertiary">raw: {{ stats.balance?.relay_usage_raw }}</div>
        </div>
        <div>
          <div class="text-text-tertiary">当前余额</div>
          <div class="font-mono font-bold text-base" :class="balanceColor">
            {{ stats.balance?.currency_symbol || '¥' }}{{ stats.balance?.balance_cny?.toFixed(2) ?? '--' }}
          </div>
          <div class="text-[10px]" :class="stats.balance?.low_balance ? 'text-danger' : 'text-text-tertiary'">
            {{ stats.balance?.low_balance ? '⚠ 低于阈值' : '正常' }}
          </div>
        </div>
      </div>
    </div>

    <!-- Agent 作用域矩阵（多用户 × 多产品对并行） -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold">智能体作用域矩阵</h3>
        <span class="text-xs text-text-tertiary">每行 = 一个独立执行目标；每目标独立 snapshot/决策/频次桶/FSM</span>
      </div>
      <div class="bg-dark-200 rounded p-3 mb-3 grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div>
          <div class="text-xs text-text-tertiary mb-1">新增目标 — 用户</div>
          <select v-model="newTarget.user_id" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
            <option :value="null">选择用户…</option>
            <option v-for="u in scopeOpts.users || []" :key="u.user_id" :value="u.user_id">
              {{ u.username }} · {{ u.role }}
            </option>
          </select>
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">产品对</div>
          <select v-model="newTarget.pair_code" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
            <option :value="null">选择产品对…</option>
            <option v-for="p in scopeOpts.pair_codes || []" :key="p" :value="p">{{ p }}</option>
          </select>
        </div>
        <div>
          <div class="text-xs text-text-tertiary mb-1">优先级（大的先）</div>
          <input v-model.number="newTarget.priority" type="number" step="1" min="0"
            class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
        </div>
        <div class="flex items-end">
          <button @click="addTarget" :disabled="!newTarget.user_id || !newTarget.pair_code"
            class="w-full px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover disabled:opacity-40">
            添加目标
          </button>
        </div>
      </div>

      <div v-if="!targets || targets.length === 0" class="text-text-tertiary text-sm py-4 text-center">
        尚无目标 — 添加至少一个才会产生决策
      </div>
      <table v-else class="w-full text-xs">
        <thead class="text-text-tertiary">
          <tr class="text-left border-b border-border-primary">
            <th class="py-2">ID</th><th>用户</th><th>产品对</th><th>优先级</th><th>启用</th><th>创建</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in targets" :key="t.id" class="border-b border-border-primary hover:bg-dark-200">
            <td class="py-2 font-mono text-text-tertiary">#{{ t.id }}</td>
            <td><span class="font-semibold">{{ t.username }}</span></td>
            <td><span class="font-mono text-primary">{{ t.pair_code }}</span></td>
            <td class="font-mono">{{ t.priority }}</td>
            <td>
              <label class="inline-flex items-center gap-1">
                <input type="checkbox" :checked="t.enabled" @change="toggleTarget(t, $event.target.checked)" class="accent-primary">
                <span :class="t.enabled ? 'text-success' : 'text-text-tertiary'">{{ t.enabled ? '启用' : '停用' }}</span>
              </label>
            </td>
            <td class="font-mono text-text-tertiary">{{ fmtTime(t.created_at) }}</td>
            <td>
              <button @click="removeTarget(t)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="text-[10px] text-text-tertiary mt-3">
        ⚠ 多目标并行时，每目标每 60s 一次决策；N 个目标 → N 倍 Codex token 消耗。注意 /llm-stats 余额。
      </div>
    </div>

    <!-- 运行模式 -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <h3 class="font-semibold mb-3">运行模式</h3>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button v-for="m in modes" :key="m.key" @click="setMode(m.key)"
          class="p-4 rounded-lg border-2 text-left transition"
          :class="status?.mode === m.key ? 'border-primary bg-primary/10' : 'border-border-primary hover:bg-dark-200'">
          <div class="font-bold">{{ m.label }}</div>
          <div class="text-xs text-text-tertiary mt-1">{{ m.desc }}</div>
        </button>
      </div>
    </div>

    <!-- Kill switch -->
    <div class="bg-dark-100 rounded-xl p-5 border" :class="status?.kill_switch ? 'border-danger' : 'border-border-primary'">
      <div class="flex justify-between items-center">
        <div>
          <h3 class="font-semibold">紧急停机 (Kill Switch)</h3>
          <div class="text-xs text-text-tertiary mt-1">
            开启后立即冻结所有决策与执行；shadow 模式仍记录但不下单
          </div>
        </div>
        <button @click="toggleKill"
          class="px-6 py-3 rounded-lg font-bold text-base transition"
          :class="status?.kill_switch ? 'bg-success text-dark-300' : 'bg-danger text-white'">
          {{ status?.kill_switch ? '解除停机' : '立即停机' }}
        </button>
      </div>
      <div v-if="status?.kill_switch" class="mt-3 text-danger text-sm">⚠ 当前已停机：所有 LLM 决策都会被拒</div>
    </div>

    <!-- 干预记录 -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <h3 class="font-semibold mb-3">净资产干预记录</h3>
      <div v-if="!interventions || interventions.length === 0" class="text-text-tertiary text-sm py-4 text-center">无记录</div>
      <table v-else class="w-full text-xs">
        <thead class="text-text-tertiary">
          <tr class="text-left">
            <th class="py-1">触发时间</th><th>账户</th><th>状态</th><th>占比</th><th>强减%</th><th>解除</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="i in interventions" :key="i.id" class="border-t border-border-primary">
            <td class="py-1.5 font-mono">{{ fmtTime(i.triggered_at) }}</td>
            <td class="font-mono text-text-tertiary">{{ i.account_id.slice(0, 8) }}</td>
            <td><span class="px-1.5 py-0.5 rounded text-[10px]" :class="stateBadge(i.state)">{{ i.state }}</span></td>
            <td class="font-mono">{{ (i.equity_ratio * 100).toFixed(1) }}%</td>
            <td class="font-mono">{{ i.forced_reduce_pct ? (i.forced_reduce_pct * 100).toFixed(0) + '%' : '--' }}</td>
            <td class="font-mono text-text-tertiary">{{ i.resolved_at ? fmtTime(i.resolved_at) : '进行中' }}</td>
            <td>
              <button v-if="!i.resolved_at" @click="ackIntervention(i.account_id)"
                class="px-2 py-0.5 bg-blue-600 text-white rounded text-[10px]">操作员确认</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 生效配置 -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <div class="flex justify-between items-center mb-3">
        <h3 class="font-semibold">当前生效配置</h3>
        <button @click="loadConfig" class="text-xs text-primary hover:underline">刷新</button>
      </div>
      <pre class="text-[10px] text-text-secondary bg-dark-300 p-3 rounded overflow-x-auto max-h-96">{{ JSON.stringify(config, null, 2) }}</pre>
    </div>
  </div>
</template>
<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'

const status = ref(null)
const interventions = ref([])
const config = ref({})
const stats = ref(null)
const scopeOpts = ref({ users: [], pair_codes: [] })
const llm = reactive({ model: 'gpt-5', streaming: true, recharge_total_cny: 100, balance_alert_threshold_cny: 20, usage_multiplier: 1.0, currency_symbol: '$', available_models: [] })
const targets = ref([])
const newTarget = ref({ user_id: null, pair_code: null, priority: 0 })

const modes = [
  { key: 'shadow', label: 'Shadow', desc: '只观察记录，不下单。建议至少 7 天。' },
  { key: 'semi', label: '半自动', desc: '入 pending 需审批后执行。' },
  { key: 'auto', label: '全自动', desc: 'Guard 通过即执行。' },
  { key: 'off', label: '已停机', desc: '关闭 LLM 决策。' },
]

const balanceColor = computed(() => {
  const b = stats.value?.balance?.balance_cny
  if (b == null) return 'text-text-primary'
  if (b < 20) return 'text-danger'
  if (b < 50) return 'text-warning'
  return 'text-success'
})

function fmtInt(n) { return n != null ? Number(n).toLocaleString() : '--' }
function fmtTime(t) { return dayjs(t).format('MM-DD HH:mm:ss') }
function stateBadge(s) {
  return ({
    NORMAL: 'bg-success/20 text-success', WARNING: 'bg-warning/20 text-warning',
    ESCALATING: 'bg-orange-900/30 text-orange-300', FORCED_REDUCE: 'bg-danger/20 text-danger',
    RESOLVED: 'bg-dark-200 text-text-tertiary',
  })[s] || 'bg-dark-200 text-text-tertiary'
}

async function saveLlm() {
  try {
    await api.post('/api/v1/agent/llm-config', {
      model: llm.model, streaming: llm.streaming,
      recharge_total_cny: llm.recharge_total_cny,
      balance_alert_threshold_cny: llm.balance_alert_threshold_cny,
      usage_multiplier: llm.usage_multiplier,
      currency_symbol: llm.currency_symbol,
    })
    alert('LLM 配置已保存并热加载生效')
    await refresh()
  } catch (e) { alert('保存失败: ' + (e.response?.data?.detail || e.message)) }
}

async function loadTargets() {
  try {
    const r = await api.get('/api/v1/agent/scope/targets')
    targets.value = r.data?.items || []
  } catch (e) { console.error(e) }
}
async function addTarget() {
  if (!newTarget.value.user_id || !newTarget.value.pair_code) return
  try {
    await api.post('/api/v1/agent/scope/targets', {
      user_id: newTarget.value.user_id,
      pair_code: newTarget.value.pair_code,
      priority: newTarget.value.priority || 0,
    })
    newTarget.value = { user_id: null, pair_code: null, priority: 0 }
    await loadTargets()
  } catch (e) { alert('添加失败: ' + (e.response?.data?.detail || e.message)) }
}
async function removeTarget(t) {
  if (!confirm('删除目标 #' + t.id + ' (' + t.username + ' / ' + t.pair_code + ')？')) return
  try { await api.delete('/api/v1/agent/scope/targets/' + t.id); await loadTargets() }
  catch (e) { alert('删除失败: ' + (e.response?.data?.detail || e.message)) }
}
async function toggleTarget(t, enabled) {
  try { await api.post('/api/v1/agent/scope/targets/' + t.id + '/toggle', { enabled }); await loadTargets() }
  catch (e) { alert('切换失败: ' + (e.response?.data?.detail || e.message)); await loadTargets() }
}

async function setMode(m) {
  if (!confirm(`切换运行模式为 [${m}]？`)) return
  try { await api.post('/api/v1/agent/mode', { mode: m }); await refresh() }
  catch (e) { alert('切换失败: ' + (e.response?.data?.detail || e.message)) }
}
async function toggleKill() {
  const next = !status.value?.kill_switch
  if (!confirm(next ? '⚠ 立即停机所有决策？' : '解除停机？')) return
  try { await api.post('/api/v1/agent/kill', { on: next }); await refresh() }
  catch (e) { alert('操作失败: ' + (e.response?.data?.detail || e.message)) }
}
async function ackIntervention(account_id) {
  if (!confirm('确认情况正常，取消自动强减？')) return
  try { await api.post('/api/v1/agent/equity-ack', { account_id }); await refresh() }
  catch (e) { alert('确认失败: ' + (e.response?.data?.detail || e.message)) }
}
async function loadConfig() {
  const r = await api.get('/api/v1/agent/config')
  config.value = r.data
  if (r.data.llm_settings) Object.assign(llm, r.data.llm_settings)
  if (r.data.agent_scope) Object.assign(scope, r.data.agent_scope)
}
async function refresh() {
  try {
    const [s, i, st, so] = await Promise.all([
      api.get('/api/v1/agent/status').catch(() => null),
      api.get('/api/v1/agent/equity-interventions').catch(() => null),
      api.get('/api/v1/agent/llm-stats').catch(() => null),
      api.get('/api/v1/agent/scope-options').catch(() => null),
    ])
    if (s) status.value = s.data
    if (i) interventions.value = i.data?.items || []
    if (st) {
      stats.value = st.data
      Object.assign(llm, { model: st.data.model, streaming: st.data.streaming, available_models: st.data.available_models,
        recharge_total_cny: st.data.balance?.recharge_total_cny ?? llm.recharge_total_cny,
        balance_alert_threshold_cny: st.data.balance?.alert_threshold_cny ?? llm.balance_alert_threshold_cny,
        usage_multiplier: st.data.balance?.usage_multiplier ?? llm.usage_multiplier,
        currency_symbol: st.data.balance?.currency_symbol ?? llm.currency_symbol })
    }
    if (so) { scopeOpts.value = so.data; if (so.data.current_scope) Object.assign(scope, so.data.current_scope) }
  } catch (e) { console.error(e) }
}

let timer
onMounted(() => { refresh(); loadConfig(); timer = setInterval(refresh, 10000) })
onUnmounted(() => clearInterval(timer))
</script>
