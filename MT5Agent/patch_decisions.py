"""Patch Decisions.vue: add market snapshot display + LLM confidence gauge"""
path = "/home/ubuntu/hustle2026/frontend-auto/src/views/Decisions.vue"
with open(path, "r") as f:
    c = f.read()

# 1. Add market snapshot panel in expanded decision row
old_expanded_exec = """                <div v-if="d.execution_result">
                  <div class="text-success text-[10px] mb-1">EXECUTION_RESULT</div>
                  <pre class="text-[10px] text-text-secondary bg-dark-300 p-2 rounded overflow-x-auto">{{ JSON.stringify(d.execution_result, null, 2) }}</pre>
                </div>"""

new_expanded_exec = """                <!-- Market Snapshot -->
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
                </div>"""

c = c.replace(old_expanded_exec, new_expanded_exec, 1)

# 2. Add trigger type icons in the table
old_trigger_td = """              <td class="text-text-secondary">{{ d.trigger }}</td>"""
new_trigger_td = """              <td class="text-text-secondary">
                <span class="mr-1">{{ triggerIcon(d.trigger) }}</span>{{ d.trigger }}
              </td>"""
# Only replace the first occurrence (inside the main table, not the expanded area)
c = c.replace(old_trigger_td, new_trigger_td, 1)

# 3. Add triggerIcon helper
old_action_color = "function actionColor(a) {"
new_action_color = """function triggerIcon(t) {
  if (!t) return ''
  if (t.includes('heartbeat')) return '💓'
  if (t.includes('spread')) return '📊'
  if (t.includes('funding')) return '💰'
  if (t.includes('forced_reduce')) return '🔻'
  if (t.includes('circuit_breaker')) return '⚡'
  if (t.includes('llm_fallback')) return '🔄'
  return '⚙'
}
function actionColor(a) {"""
c = c.replace(old_action_color, new_action_color, 1)

with open(path, "w") as f:
    f.write(c)
print("Decisions.vue: market snapshot + confidence gauge + trigger icons added")
