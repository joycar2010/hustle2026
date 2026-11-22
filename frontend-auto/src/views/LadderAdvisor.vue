<template>
  <div class="p-4 max-w-6xl mx-auto space-y-4">
    <!-- 模式控制卡 -->
    <div class="bg-[#151a21] border border-[#232a35] rounded-xl p-4">
      <div class="flex flex-wrap items-center gap-4">
        <div>
          <div class="text-sm font-semibold">阶梯自动调参</div>
          <div class="text-xs text-gray-500 mt-0.5">每小时按点差分布评估各目标阶梯 · 提案由硬校验守门</div>
        </div>
        <div class="flex flex-wrap items-center gap-2 w-full lg:w-auto lg:ml-auto">
          <span class="text-xs text-gray-400">模式</span>
          <select v-model="cfg.mode" class="bg-[#0d1117] border border-[#232a35] rounded-lg px-3 py-1.5 text-sm">
            <option value="shadow">shadow(只观察)</option>
            <option value="suggest">suggest(通知人批)</option>
            <option value="auto_small">auto_small(≤幅度自动)</option>
            <option value="auto">auto(30%硬上限内自动)</option>
          </select>
          <span class="text-xs text-gray-400 ml-2">幅度%</span>
          <input v-model.number="cfg.max_auto_pct" type="number" min="1" max="30" class="bg-[#0d1117] border border-[#232a35] rounded-lg px-2 py-1.5 text-sm w-16" />
          <span class="text-xs text-gray-400 ml-2">冷却h</span>
          <input v-model.number="cfg.cooldown_hours" type="number" min="1" max="168" class="bg-[#0d1117] border border-[#232a35] rounded-lg px-2 py-1.5 text-sm w-16" />
          <button @click="saveCfg" :disabled="saving" class="bg-emerald-600 hover:bg-emerald-500 rounded-lg px-4 py-1.5 text-sm font-medium disabled:opacity-40">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
      <div v-if="cfg.mode !== 'shadow'" class="mt-2 text-xs text-amber-400">
        ⚠ 非影子模式:{{ cfg.mode === 'suggest' ? '提案将飞书通知等待人工' : '通过硬校验的提案将自动改写 strategy_configs.ladders(运行中策略3s热生效)' }}
      </div>
      <div class="mt-3 pt-3 border-t border-[#232a35] grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
        <div><div class="text-gray-500">评估版本</div><div class="mt-1 font-mono">{{ summary.evaluation_version || 'shadow_replay_v1' }}</div></div>
        <div><div class="text-gray-500">启用目标</div><div class="mt-1 font-mono">{{ summary.active_targets ?? 0 }}</div></div>
        <div><div class="text-gray-500">同窗回放</div><div class="mt-1 font-mono">{{ summary.evaluated ?? 0 }}</div></div>
        <div><div class="text-gray-500">可候选（改善且过检）</div><div class="mt-1 font-mono">{{ summary.eligible_improved ?? 0 }} / {{ summary.evaluated ?? 0 }}</div></div>
        <div><div class="text-gray-500">平均净边际增量/天</div><div class="mt-1 font-mono">{{ fmt(summary.avg_net_edge_delta_per_day) }}</div></div>
      </div>
    </div>

    <!-- 提案时间线 -->
    <div class="bg-[#151a21] border border-[#232a35] rounded-xl overflow-hidden">
      <div class="px-4 py-3 border-b border-[#232a35] flex items-center">
        <span class="text-sm font-semibold">提案记录</span>
        <button @click="load" class="ml-auto text-xs text-gray-400 hover:text-white">刷新</button>
      </div>
      <div v-for="it in items" :key="it.id" class="px-4 py-3 border-b border-[#232a35]/60">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-mono text-xs text-gray-500">#{{ it.id }}</span>
          <span class="font-medium">{{ it.username }} · {{ it.pair_code }}/{{ it.strategy_type }}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded"
                :class="{'bg-gray-700 text-gray-300': it.action==='shadow',
                         'bg-blue-900 text-blue-300': it.action==='suggested',
                         'bg-emerald-900 text-emerald-300': it.action==='applied',
                         'bg-red-900 text-red-300': it.action==='rolled_back'}">{{ it.action }}</span>
          <span class="text-xs text-gray-500 ml-auto">{{ (it.created_at||'').replace('T',' ').slice(0,16) }}</span>
          <button v-if="it.action==='applied'" @click="rollback(it)" class="text-xs text-red-400 hover:text-red-300">回滚</button>
        </div>
        <div class="text-xs text-gray-400 mt-1.5">{{ it.rationale }}</div>
        <div v-if="it.validation_error" class="mt-1 text-[11px] text-red-400 font-mono">
          硬校验拦截: {{ it.validation_error }}
        </div>
        <div class="mt-2 grid md:grid-cols-2 gap-2 text-[11px] font-mono">
          <div class="bg-[#0d1117] rounded-lg p-2">
            <div class="text-gray-500 mb-1">旧阶梯</div>
            <div v-for="(l,i) in it.old_ladders" :key="'o'+i" class="text-gray-400">
              #{{i+1}} 开{{ l.openPrice }} 平{{ l.threshold }} 量{{ l.qtyLimit }}
            </div>
          </div>
          <div class="bg-[#0d1117] rounded-lg p-2">
            <div class="text-gray-500 mb-1">新阶梯(提案)</div>
            <div v-for="(l,i) in it.new_ladders" :key="'n'+i"
                 :class="diffCls(it.old_ladders[i], l)">
              #{{i+1}} 开{{ l.openPrice }} 平{{ l.threshold }} 量{{ l.qtyLimit }}
            </div>
          </div>
        </div>
        <div v-if="it.replay_metrics" class="mt-2 border-t border-[#232a35] pt-2">
          <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
            <div><span class="text-gray-500">旧净边际/天</span><div class="font-mono">{{ fmt(metric(it, 'old', 'net_edge_per_day')) }}</div></div>
            <div><span class="text-gray-500">提案净边际/天</span><div class="font-mono">{{ fmt(metric(it, 'proposal', 'net_edge_per_day')) }}</div></div>
            <div><span class="text-gray-500">增量/天</span><div class="font-mono" :class="deltaCls(metric(it, 'delta', 'net_edge_per_day'))">{{ fmt(metric(it, 'delta', 'net_edge_per_day')) }}</div></div>
            <div><span class="text-gray-500">最大回撤变化</span><div class="font-mono">{{ fmt(metric(it, 'delta', 'max_drawdown_edge')) }}</div></div>
            <div><span class="text-gray-500">提案峰值库存</span><div class="font-mono">{{ fmt(metric(it, 'proposal', 'peak_inventory')) }}</div></div>
            <div><span class="text-gray-500">提案库存占用</span><div class="font-mono">{{ fmtPct(metric(it, 'proposal', 'inventory_utilization_pct')) }}</div></div>
            <div><span class="text-gray-500">提案盈利平仓率</span><div class="font-mono">{{ fmtPct(metric(it, 'proposal', 'profitable_close_rate_pct')) }}</div></div>
            <div><span class="text-gray-500">提案平均持仓</span><div class="font-mono">{{ fmtDuration(metric(it, 'proposal', 'avg_holding_seconds')) }}</div></div>
          </div>
          <div class="mt-2 text-[11px] text-gray-500">
            真实执行质量（同用户/交易对/方向）:
            尝试 {{ it.replay_metrics.actual_execution?.attempts ?? 0 }}，
            成交率 {{ fmtPct(it.replay_metrics.actual_execution?.fill_rate_pct) }}，
            NO_FILL {{ it.replay_metrics.actual_execution?.no_fill ?? 0 }}，
            BUDGET_GATED {{ it.replay_metrics.actual_execution?.budget_gated ?? 0 }}
          </div>
        </div>
        <div v-else class="flex flex-wrap gap-4 mt-1.5 text-[11px] text-gray-500">
          <span>历史旧口径（不可用于提案归因）</span>
          <span>全账户前7d: {{ fmt(it.pnl_before_7d) }}</span>
          <span>全账户后24h: {{ it.pnl_after_24h === null ? '未回填' : fmt(it.pnl_after_24h) }}</span>
        </div>
      </div>
      <div v-if="!items.length" class="px-4 py-10 text-center text-sm text-gray-500">暂无提案记录</div>
      <div v-if="items.length >= limit" class="px-4 py-3 text-center">
        <button @click="more" class="text-xs text-gray-400 hover:text-white">加载更多</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/api'

const cfg = ref({ mode: 'shadow', max_auto_pct: 10, cooldown_hours: 24, enabled: true })
const items = ref([])
const summary = ref({})
const saving = ref(false)
const limit = ref(50)

function fmt(v) { if (v === null || v === undefined) return '—'; const n = Number(v); return (n>0?'+':'')+n.toFixed(2) }
function fmtPct(v) { return v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%` }
function fmtDuration(v) {
  if (v === null || v === undefined) return '—'
  const seconds = Number(v)
  return seconds >= 3600 ? `${(seconds / 3600).toFixed(1)}h` : `${(seconds / 60).toFixed(1)}m`
}
function metric(it, section, key) { return it.replay_metrics?.[section]?.[key] }
function deltaCls(v) { return Number(v) > 0 ? 'text-emerald-400' : Number(v) < 0 ? 'text-red-400' : '' }
function diffCls(o, n) {
  if (!o) return 'text-gray-400'
  const changed = o.openPrice !== n.openPrice || o.threshold !== n.threshold || o.qtyLimit !== n.qtyLimit
  return changed ? 'text-amber-300' : 'text-gray-400'
}

async function load() {
  try {
    const c = await api.get('/api/v1/agent/ladder-advisor/config'); cfg.value = { ...cfg.value, ...c.data }
    const r = await api.get(`/api/v1/agent/ladder-advisor/log?limit=${limit.value}`); items.value = r.data.items || []
    const s = await api.get('/api/v1/agent/ladder-advisor/evaluation-summary'); summary.value = s.data || {}
  } catch (e) { console.error(e) }
}
async function saveCfg() {
  saving.value = true
  try {
    if (['auto_small','auto'].includes(cfg.value.mode) && !confirm(`确认切到 ${cfg.value.mode}?通过硬校验的提案将自动改写线上阶梯配置`)) { saving.value = false; return }
    await api.put('/api/v1/agent/ladder-advisor/config', cfg.value); await load()
  } catch (e) { alert(e?.response?.data?.detail || '保存失败') } finally { saving.value = false }
}
async function rollback(it) {
  if (!confirm(`回滚 #${it.id}(${it.pair_code}/${it.strategy_type})到旧阶梯?`)) return
  try { await api.post(`/api/v1/agent/ladder-advisor/rollback/${it.id}`); await load() }
  catch (e) { alert(e?.response?.data?.detail || '回滚失败') }
}
async function more() { limit.value += 50; await load() }
onMounted(load)
</script>
