"""Patch Dashboard.vue: enhance with OpenCLAW intelligence metrics"""
path = "/home/ubuntu/hustle2026/frontend-auto/src/views/Dashboard.vue"
with open(path, "r") as f:
    c = f.read()

# 1. Add intelligence summary panel after the KPI strip
# Insert after the closing </div> of the KPI grid, before the leg-balance section
old_mid = """    <!-- Mid: leg balance + rate buckets (compact) -->"""

new_mid = """    <!-- OpenCLAW 智能化实时指标 -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold text-sm flex items-center gap-2">
          <span class="text-primary">⚡</span> OpenCLAW 智能决策引擎
          <span class="px-2 py-0.5 rounded text-[10px]" :class="modeColor">{{ modeLabel }}</span>
          <span v-if="llmHealth?.circuit_open" class="px-2 py-0.5 rounded text-[10px] bg-danger/20 text-danger">LLM 熔断中</span>
        </h3>
        <div class="text-[10px] text-text-tertiary">
          <span v-if="status?.openclaw_enabled" class="text-success">● 已启用</span>
          <span v-else class="text-danger">● 已关闭</span>
        </div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-2 text-xs">
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">智能信号</div>
          <div class="font-mono font-bold text-lg" :class="stats?.by_action?.open_long || stats?.by_action?.open_short ? 'text-primary' : 'text-text-tertiary'">
            {{ (stats?.by_action?.open_long || 0) + (stats?.by_action?.open_short || 0) }}
          </div>
          <div class="text-[9px] text-text-tertiary">开仓提案</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">成功执行</div>
          <div class="font-mono font-bold text-lg text-success">{{ stats?.by_verdict?.executed || 0 }}</div>
          <div class="text-[9px] text-text-tertiary">executed</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">风控拦截</div>
          <div class="font-mono font-bold text-lg text-danger">{{ stats?.by_verdict?.rejected || 0 }}</div>
          <div class="text-[9px] text-text-tertiary">guard/rejected</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">观察记录</div>
          <div class="font-mono font-bold text-lg text-yellow-400">{{ stats?.by_verdict?.shadow || 0 }}</div>
          <div class="text-[9px] text-text-tertiary">shadow</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">平均置信</div>
          <div class="font-mono font-bold text-lg" :class="(stats?.avg_conf || 0) > 0.5 ? 'text-success' : 'text-warning'">
            {{ (stats?.avg_conf * 100 || 0).toFixed(0) }}%
          </div>
          <div class="text-[9px] text-text-tertiary">LLM conf</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">Token成本</div>
          <div class="font-mono font-bold text-lg">¥{{ tokenCostCny }}</div>
          <div class="text-[9px] text-text-tertiary">今日消耗</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">响应延迟</div>
          <div class="font-mono font-bold text-lg">{{ stats?.latency?.p50_ms?.toFixed(0) ?? '--' }}<span class="text-[10px] text-text-tertiary">ms</span></div>
          <div class="text-[9px] text-text-tertiary">p50中位</div>
        </div>
        <div class="bg-dark-200 rounded-lg px-2.5 py-2 text-center">
          <div class="text-text-tertiary text-[10px]">决策效率</div>
          <div class="font-mono font-bold text-lg" :class="decisionEfficiency > 30 ? 'text-success' : 'text-warning'">
            {{ decisionEfficiency }}%
          </div>
          <div class="text-[9px] text-text-tertiary">有效/总数</div>
        </div>
      </div>
      <!-- Recent decision quality bar -->
      <div class="mt-3 flex items-center gap-2 text-[10px]">
        <span class="text-text-tertiary">决策质量分布:</span>
        <div class="flex-1 h-2.5 bg-dark-200 rounded-full overflow-hidden flex">
          <div class="bg-success h-full" :style="{width: verdictPctBar('executed') + '%'}" :title="'executed ' + verdictPctBar('executed') + '%'"></div>
          <div class="bg-yellow-500 h-full" :style="{width: verdictPctBar('shadow') + '%'}" :title="'shadow ' + verdictPctBar('shadow') + '%'"></div>
          <div class="bg-blue-500 h-full" :style="{width: verdictPctBar('pending') + '%'}" :title="'pending ' + verdictPctBar('pending') + '%'"></div>
          <div class="bg-danger h-full" :style="{width: verdictPctBar('rejected') + '%'}" :title="'rejected ' + verdictPctBar('rejected') + '%'"></div>
        </div>
        <span class="text-success">●执行</span>
        <span class="text-yellow-500">●观察</span>
        <span class="text-blue-500">●待审</span>
        <span class="text-danger">●拦截</span>
      </div>
    </div>

    <!-- Mid: leg balance + rate buckets (compact) -->"""

c = c.replace(old_mid, new_mid, 1)

# 2. Add computed properties in script
old_spread_mode = """const spreadModeLabel = computed(() => {"""
new_spread_mode = """const tokenCostCny = computed(() => {
  const t = stats.value?.tokens_total || 0
  return (t / 1000000 * 2 * 7.3).toFixed(2)  // ~$2/1M tokens * 7.3 CNY rate
})
const decisionEfficiency = computed(() => {
  const total = stats.value?.total || 0
  if (total === 0) return 0
  const effective = (stats.value?.by_verdict?.executed || 0) + (stats.value?.by_verdict?.shadow || 0)
  return ((effective / total) * 100).toFixed(0)
})
const spreadModeLabel = computed(() => {"""

c = c.replace(old_spread_mode, new_spread_mode, 1)

# 3. Add verdictPctBar helper function
old_fmt = "\nfunction fmt(n)"
new_fmt = """
function verdictPctBar(v) {
  const total = stats.value?.total || 1
  return (((stats.value?.by_verdict?.[v] || 0) / total) * 100).toFixed(1)
}

// LLM health state
const llmHealth = ref(null)
async function loadLlmHealth() {
  try {
    const r = await api.get('/api/v1/agent/llm-health')
    llmHealth.value = r.data
  } catch {}
}

function fmt(n)"""

c = c.replace(old_fmt, new_fmt, 1)

# 4. Add llmHealth refresh to core polling
old_refresh_core_start = """async function refreshCore() {"""
new_refresh_core_start = """async function refreshCore() {
  loadLlmHealth()"""
c = c.replace(old_refresh_core_start, new_refresh_core_start, 1)

with open(path, "w") as f:
    f.write(c)
print("Dashboard.vue: intelligence metrics + quality bar added")
