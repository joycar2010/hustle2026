<template>
  <div class="p-4 max-w-6xl mx-auto space-y-4">
    <!-- 模式控制卡 -->
    <div class="bg-[#151a21] border border-[#232a35] rounded-xl p-4">
      <div class="flex flex-wrap items-center gap-4">
        <div>
          <div class="text-sm font-semibold">阶梯自动调参</div>
          <div class="text-xs text-gray-500 mt-0.5">每小时按点差分布评估各目标阶梯 · 提案由硬校验守门</div>
        </div>
        <div class="flex items-center gap-2 ml-auto">
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
        <div class="flex gap-4 mt-1.5 text-[11px] text-gray-500">
          <span>提案前7d收益: {{ fmt(it.pnl_before_7d) }}</span>
          <span>后24h收益: {{ it.pnl_after_24h === null ? '待回填' : fmt(it.pnl_after_24h) }}</span>
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
const saving = ref(false)
const limit = ref(50)

function fmt(v) { if (v === null || v === undefined) return '—'; const n = Number(v); return (n>0?'+':'')+n.toFixed(2) }
function diffCls(o, n) {
  if (!o) return 'text-gray-400'
  const changed = o.openPrice !== n.openPrice || o.threshold !== n.threshold || o.qtyLimit !== n.qtyLimit
  return changed ? 'text-amber-300' : 'text-gray-400'
}

async function load() {
  try {
    const c = await api.get('/api/v1/agent/ladder-advisor/config'); cfg.value = { ...cfg.value, ...c.data }
    const r = await api.get(`/api/v1/agent/ladder-advisor/log?limit=${limit.value}`); items.value = r.data.items || []
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
