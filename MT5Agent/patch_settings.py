"""Patch Settings.vue: add per-target risk cap editor + LLM health panel"""
path = "/home/ubuntu/hustle2026/frontend-auto/src/views/Settings.vue"
with open(path, "r") as f:
    c = f.read()

# 1. Add per-target cap editing UI in the scope matrix section
# After the scope targets table, before the warning text
old_warning = """      <div class="text-[10px] text-text-tertiary mt-3">
        ⚠ 多目标并行时，每目标每 60s 一次决策；N 个目标 → N 倍 Codex token 消耗。注意 /llm-stats 余额。
      </div>"""

new_warning = """      <!-- Per-target risk cap editor -->
      <div v-if="editingCaps" class="mt-3 bg-dark-200 rounded-lg p-4 border border-border-primary">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-sm font-semibold">风控参数 · 目标 #{{ editingCaps.target_id }} <span class="text-primary font-mono">{{ editingCaps.pair_code }}</span></h4>
          <button @click="editingCaps = null" class="text-xs text-text-tertiary hover:text-text-primary">✕ 关闭</button>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-4 gap-3">
          <div>
            <div class="text-xs text-text-tertiary mb-1">单笔上限 %<span class="text-text-tertiary ml-1">(全局: {{ (editingCaps.global_caps?.single_trade_pct * 100 || 10).toFixed(0) }}%)</span></div>
            <input v-model.number="editingCaps.single_trade_pct" type="number" step="0.01" min="0.01" max="1"
              class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">总持仓上限 %<span class="text-text-tertiary ml-1">(全局: {{ (editingCaps.global_caps?.total_position_pct * 100 || 50).toFixed(0) }}%)</span></div>
            <input v-model.number="editingCaps.total_position_pct" type="number" step="0.05" min="0.05" max="2"
              class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">日内累计上限 %<span class="text-text-tertiary ml-1">(全局: {{ (editingCaps.global_caps?.daily_volume_pct * 100 || 500).toFixed(0) }}%)</span></div>
            <input v-model.number="editingCaps.daily_volume_pct" type="number" step="0.5" min="0.5" max="20"
              class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div class="flex items-end">
            <button @click="saveTargetCaps" class="w-full px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover text-sm">
              保存风控参数
            </button>
          </div>
        </div>
        <div class="text-[10px] text-text-tertiary mt-2">⚡ 5 秒内热加载生效（config_loader TTL=5s），无需重启</div>
      </div>
      <div class="text-[10px] text-text-tertiary mt-3">
        ⚠ 多目标并行时，每目标每 60s 一次决策；N 个目标 → N 倍 Codex token 消耗。注意 /llm-stats 余额。
      </div>"""

assert old_warning in c, "warning anchor not found"
c = c.replace(old_warning, new_warning, 1)

# 2. Add "编辑风控" button in table rows
old_delete_btn = """              <button @click="removeTarget(t)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">删除</button>"""
new_delete_btn = """              <button @click="editCaps(t)" class="px-2 py-0.5 bg-primary/20 text-primary rounded text-[10px] hover:bg-primary/30 mr-1">风控</button>
              <button @click="removeTarget(t)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">删除</button>"""
c = c.replace(old_delete_btn, new_delete_btn, 1)

# 3. Add LLM health panel before the existing LLM config section
old_llm_header = """    <!-- Codex 模型配置 -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <h3 class="font-semibold mb-3 flex items-center justify-between">
        <span>Codex 模型配置</span>"""

new_llm_header = """    <!-- LLM 健康状态 -->
    <div v-if="llmHealth" class="bg-dark-100 rounded-xl p-4 border" :class="llmHealth.circuit_open ? 'border-danger' : 'border-border-primary'">
      <div class="flex items-center justify-between">
        <h3 class="font-semibold text-sm flex items-center gap-2">
          LLM 服务健康
          <span class="px-2 py-0.5 rounded text-[10px]"
            :class="llmHealth.circuit_open ? 'bg-danger/20 text-danger' : 'bg-success/20 text-success'">
            {{ llmHealth.circuit_open ? '熔断中' : '正常' }}
          </span>
        </h3>
        <button @click="loadLlmHealth" class="text-xs text-primary hover:underline">刷新</button>
      </div>
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3 mt-3 text-xs">
        <div>
          <div class="text-text-tertiary">主模型</div>
          <div class="font-mono font-semibold">{{ llmHealth.primary_model }}</div>
        </div>
        <div>
          <div class="text-text-tertiary">降级模型</div>
          <div class="font-mono text-warning">{{ llmHealth.fallback_model }}</div>
        </div>
        <div>
          <div class="text-text-tertiary">5分钟内失败</div>
          <div class="font-mono" :class="llmHealth.recent_failures > 3 ? 'text-danger' : 'text-text-primary'">
            {{ llmHealth.recent_failures }} / {{ llmHealth.failure_threshold }}
          </div>
        </div>
        <div>
          <div class="text-text-tertiary">熔断策略</div>
          <div class="text-[10px]">{{ llmHealth.failure_threshold }}次/{{ llmHealth.failure_window_s }}s → 冷却120s</div>
        </div>
        <div v-if="llmHealth.circuit_open">
          <div class="text-danger text-[10px]">⚠ 熔断中：所有LLM调用返回noop，等待自动恢复</div>
        </div>
      </div>
    </div>

    <!-- Codex 模型配置 -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <h3 class="font-semibold mb-3 flex items-center justify-between">
        <span>Codex 模型配置</span>"""

c = c.replace(old_llm_header, new_llm_header, 1)

# 4. Add script methods for caps editing and LLM health
old_script_end = """let timer
onMounted(() => {
  refresh()
  loadConfig()
  loadTargets()                 // initial matrix population
  timer = setInterval(() => { refresh(); loadTargets() }, 10000)
})
onUnmounted(() => clearInterval(timer))"""

new_script_end = """const editingCaps = ref(null)
const llmHealth = ref(null)

async function editCaps(t) {
  try {
    const r = await api.get('/api/v1/agent/scope/targets/' + t.id + '/caps')
    editingCaps.value = {
      target_id: t.id,
      pair_code: t.pair_code,
      username: t.username,
      single_trade_pct: r.data.caps?.single_trade_pct ?? 0.10,
      total_position_pct: r.data.caps?.total_position_pct ?? 0.50,
      daily_volume_pct: r.data.caps?.daily_volume_pct ?? 5.0,
      global_caps: r.data.global_caps || {},
    }
  } catch (e) { alert('加载风控参数失败: ' + (e.response?.data?.detail || e.message)) }
}

async function saveTargetCaps() {
  if (!editingCaps.value) return
  try {
    await api.post('/api/v1/agent/scope/targets/' + editingCaps.value.target_id + '/caps', {
      single_trade_pct: editingCaps.value.single_trade_pct,
      total_position_pct: editingCaps.value.total_position_pct,
      daily_volume_pct: editingCaps.value.daily_volume_pct,
    })
    alert('风控参数已保存，5秒内热加载生效')
    editingCaps.value = null
    await loadConfig()
  } catch (e) { alert('保存失败: ' + (e.response?.data?.detail || e.message)) }
}

async function loadLlmHealth() {
  try {
    const r = await api.get('/api/v1/agent/llm-health')
    llmHealth.value = r.data
  } catch (e) { console.error('LLM health:', e) }
}

let timer
onMounted(() => {
  refresh()
  loadConfig()
  loadTargets()
  loadLlmHealth()
  timer = setInterval(() => { refresh(); loadTargets(); loadLlmHealth() }, 10000)
})
onUnmounted(() => clearInterval(timer))"""

c = c.replace(old_script_end, new_script_end, 1)

with open(path, "w") as f:
    f.write(c)
print("Settings.vue: per-target caps + LLM health panel added")
