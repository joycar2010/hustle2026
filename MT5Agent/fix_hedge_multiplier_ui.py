"""Restore hedge multiplier UI to StrategyPanel.vue (lost during a previous rewrite)"""
path = "/home/ubuntu/hustle2026/frontend-go/src/components/trading/StrategyPanel.vue"
with open(path, "r") as f:
    c = f.read()

# 1. Insert hedge multiplier template before "Execution Status Display"
old_template = """        <!-- Execution Status Display - 只显示开仓状态 -->"""

new_template = """        <!-- Hedge Multiplier Control -->
        <div v-if="showHedgeRatio" class="mt-2 bg-[#1a1d21] rounded p-2">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-[10px] text-gray-400">对冲倍数</span>
            <span class="text-xs font-mono font-bold" :class="hedgeMultiplier > 1 ? 'text-[#f0b90b]' : 'text-gray-300'">{{ hedgeMultiplier }}x</span>
          </div>
          <div class="flex gap-1">
            <button v-for="m in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]" :key="m"
              @click="setHedgeMultiplier(m)"
              :disabled="continuousExecutionEnabled.opening || continuousExecutionEnabled.closing"
              :class="['flex-1 py-1 rounded text-[10px] font-bold transition-all',
                hedgeMultiplier === m ? 'bg-primary text-dark-300' : 'bg-dark-200 text-gray-400 hover:bg-dark-50',
                (continuousExecutionEnabled.opening || continuousExecutionEnabled.closing) ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer']">
              {{ m }}x
            </button>
          </div>
        </div>

        <!-- Execution Status Display - 只显示开仓状态 -->"""

assert old_template in c, "Execution Status anchor not found"
c = c.replace(old_template, new_template, 1)

# 2. Insert script: hedgeMultiplier ref + functions before continuousExecutionEnabled
old_script = """const continuousExecutionEnabled = ref({ opening: false, closing: false })"""

new_script = """const hedgeMultiplier = ref(1.0)
const showHedgeRatio = ref(true)

async function fetchHedgeMultiplier() {
  try {
    const r = await api.get('/api/v1/hedge-ratio', { params: { pair_code: currentPair.value || 'XAU' } })
    hedgeMultiplier.value = r.data?.hedge_multiplier ?? 1.0
    showHedgeRatio.value = !!r.data?.enabled
  } catch { hedgeMultiplier.value = 1.0; showHedgeRatio.value = false }
}

async function setHedgeMultiplier(m) {
  if (continuousExecutionEnabled.value?.opening || continuousExecutionEnabled.value?.closing) return
  if (!confirm(`确定将对冲倍数设为 ${m}x 吗？开仓和平仓都将按此倍数执行。`)) return
  try {
    await api.put('/api/v1/hedge-ratio', { hedge_multiplier: m, pair_code: currentPair.value || 'XAU' })
    hedgeMultiplier.value = m
  } catch (e) {
    console.error('Failed to set hedge multiplier:', e)
  }
}

const continuousExecutionEnabled = ref({ opening: false, closing: false })"""

assert old_script in c, "continuousExecutionEnabled anchor not found"
c = c.replace(old_script, new_script, 1)

# 3. Add fetchHedgeMultiplier() call in onMounted
old_mounted = """  fetchPairBinding()"""
new_mounted = """  fetchPairBinding()
  fetchHedgeMultiplier()"""
c = c.replace(old_mounted, new_mounted, 1)

with open(path, "w") as f:
    f.write(c)
print("StrategyPanel.vue: hedge multiplier UI restored")
