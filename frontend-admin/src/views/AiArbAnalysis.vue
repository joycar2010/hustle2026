<template>
  <div class="min-h-screen bg-dark-300 text-text-primary p-4 md:p-6">
    <!-- 选择+分析 -->
    <div class="bg-dark-100 rounded-xl border border-border-primary p-4 mb-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-base font-bold text-text-primary">AI 套利分析</h2>
        <div class="flex items-center gap-2 text-sm">
          <span class="text-text-secondary text-xs">时间窗</span>
          <select v-model.number="windowH" class="bg-dark-200 border border-border-primary rounded-lg px-2 py-1 text-text-primary text-xs">
            <option :value="24">24小时</option>
            <option :value="72">3天</option>
            <option :value="168">7天</option>
          </select>
          <button @click="analyze" :disabled="running || !selected.length"
                  class="px-4 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 text-xs font-medium rounded-lg disabled:opacity-40">
            {{ running ? '分析中…' : `分析(${selected.length})` }}
          </button>
        </div>
      </div>
      <p class="text-xs text-text-tertiary mb-3">从对冲平台列表选择产品对(数据只读实时缓存+历史落库, 不新增交易所请求)。灰色=近24h无历史点差。</p>
      <div class="flex flex-wrap gap-2">
        <label v-for="t in targets" :key="t.pair_code"
               class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs cursor-pointer select-none transition-colors"
               :class="[selected.includes(t.pair_code) ? 'border-primary bg-primary/10' : 'border-border-primary bg-dark-200',
                        !t.has_history && !t.is_active ? 'opacity-40' : '']">
          <input type="checkbox" :value="t.pair_code" v-model="selected" class="accent-primary" />
          <span class="font-medium text-text-primary">{{ t.pair_code }}</span>
          <span class="text-text-tertiary">{{ t.platform_a }}/{{ t.platform_b }}</span>
          <span v-if="t.has_history" class="w-1.5 h-1.5 rounded-full bg-success" title="有历史数据"></span>
        </label>
      </div>
    </div>

    <!-- 结果 -->
    <div v-if="result" class="bg-dark-100 rounded-xl border border-border-primary p-4 mb-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-sm font-bold text-text-primary">分析结果</span>
        <span class="text-xs text-text-tertiary">#{{ result.id }} · {{ (result.created_at||'').replace('T',' ').slice(0,16) }}</span>
      </div>
      <div class="text-sm text-text-secondary bg-primary/10 border border-primary/20 rounded-lg p-3 mb-3">{{ result.analysis.summary }}</div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[640px]">
          <thead>
            <tr class="text-xs text-text-tertiary border-b border-border-primary">
              <th class="text-left py-2 px-2">产品对</th><th class="text-left py-2 px-2">机会</th>
              <th class="text-left py-2 px-2">建议开仓区间</th><th class="text-left py-2 px-2">理由</th><th class="text-left py-2 px-2">风险</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in result.analysis.pairs" :key="p.pair_code" class="border-b border-border-primary/50">
              <td class="py-2 px-2 font-medium">{{ p.pair_code }}</td>
              <td class="py-2 px-2"><span class="px-2 py-0.5 rounded text-xs font-medium" :class="oppCls(p.opportunity)">{{ p.opportunity }}</span></td>
              <td class="py-2 px-2 font-mono text-xs text-text-secondary">{{ p.suggested_open_range ? p.suggested_open_range.join(' ~ ') : '—' }}</td>
              <td class="py-2 px-2 text-xs text-text-secondary max-w-xs">{{ p.rationale }}</td>
              <td class="py-2 px-2 text-xs text-warning">{{ (p.risks||[]).join('; ') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="result.analysis.caveats?.length" class="text-xs text-text-tertiary mt-2">
        注意: {{ result.analysis.caveats.join(' · ') }}
      </div>
    </div>

    <!-- 历史 -->
    <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
      <div class="text-sm font-bold text-text-primary mb-2">历史分析</div>
      <div v-for="h in hist" :key="h.id" class="border-b border-border-primary/50 py-2 text-xs flex items-center gap-2">
        <span class="font-mono text-text-tertiary">#{{ h.id }}</span>
        <span class="text-text-secondary">{{ (h.targets||[]).join(',') }}</span>
        <span class="text-text-tertiary flex-1 truncate">{{ h.analysis?.summary }}</span>
        <span class="text-text-tertiary">{{ (h.created_at||'').replace('T',' ').slice(5,16) }}</span>
      </div>
      <div v-if="!hist.length" class="text-xs text-text-tertiary py-4 text-center">暂无历史</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api.js'

const targets = ref([])
const selected = ref([])
const windowH = ref(24)
const running = ref(false)
const result = ref(null)
const hist = ref([])

function oppCls(o) {
  return { high: 'bg-success/20 text-success', medium: 'bg-info/20 text-info',
           low: 'bg-dark-50 text-text-secondary', none: 'bg-dark-50 text-text-tertiary' }[o] || 'bg-dark-50'
}
async function loadTargets() {
  try { const r = await api.get('/api/v1/ai-arb/targets'); targets.value = r.data.targets || [] } catch (e) { console.error(e) }
}
async function loadHist() {
  try { const r = await api.get('/api/v1/ai-arb/history?limit=15'); hist.value = r.data.items || [] } catch (e) { console.error(e) }
}
async function analyze() {
  running.value = true
  try {
    const r = await api.post('/api/v1/ai-arb/analyze', { pair_codes: selected.value, window_h: windowH.value })
    result.value = r.data; await loadHist()
  } catch (e) { alert(e?.response?.data?.detail || '分析失败') } finally { running.value = false }
}
onMounted(() => { loadTargets(); loadHist() })
</script>
