"""Patch Proposals.vue: add decision-linked proposals tab + statistics"""
path = "/home/ubuntu/hustle2026/frontend-auto/src/views/Proposals.vue"
with open(path, "r") as f:
    c = f.read()

# 1. Add a statistics header showing proposal counts by status
old_header = """      <div>
        <h2 class="font-semibold">策略提议中心</h2>
        <div class="text-xs text-text-tertiary mt-1">
          已加载 {{ items.length }} 条 · Codex/操作员发起的配置变更，批准后写入
          <span class="font-mono">agent_active_config</span> / <span class="font-mono">agent_target_config</span>
        </div>
      </div>"""

new_header = """      <div>
        <h2 class="font-semibold flex items-center gap-2">
          策略提议中心
          <span v-if="proposalStats.pending > 0" class="px-2 py-0.5 rounded text-[10px] bg-blue-900/30 text-blue-400 animate-pulse">
            {{ proposalStats.pending }} 待审批
          </span>
        </h2>
        <div class="text-xs text-text-tertiary mt-1 flex items-center gap-3">
          <span>已加载 {{ items.length }} 条</span>
          <span class="text-text-tertiary">·</span>
          <span class="text-success">✓ {{ proposalStats.approved }}</span>
          <span class="text-danger">✕ {{ proposalStats.rejected }}</span>
          <span class="text-warning">↺ {{ proposalStats.rolled_back }}</span>
          <span class="text-text-tertiary">·</span>
          <span>批准后写入 <span class="font-mono">agent_active_config</span> / <span class="font-mono">agent_target_config</span></span>
        </div>
      </div>"""

c = c.replace(old_header, new_header, 1)

# 2. Add proposal snapshot display in expanded row
old_rationale = """                <!-- Rationale -->
                <div>
                  <div class="text-text-tertiary text-[10px] mb-1">RATIONALE</div>
                  <div class="text-text-primary text-xs whitespace-pre-wrap leading-relaxed">{{ p.rationale || '(空)' }}</div>
                </div>"""

new_rationale = """                <!-- Rationale -->
                <div>
                  <div class="text-text-tertiary text-[10px] mb-1">RATIONALE</div>
                  <div class="text-text-primary text-xs whitespace-pre-wrap leading-relaxed">{{ p.rationale || '(空)' }}</div>
                </div>

                <!-- LLM Proposal Detail (if linked to decision) -->
                <div v-if="p.source_decision_id" class="bg-dark-300 rounded-lg p-3 border border-border-primary">
                  <div class="text-text-tertiary text-[10px] mb-2">来源决策 #{{ p.source_decision_id }}</div>
                  <div v-if="p.proposal_snapshot" class="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                    <div><span class="text-text-tertiary">动作:</span> <span class="font-mono text-primary">{{ p.proposal_snapshot?.action }}</span></div>
                    <div><span class="text-text-tertiary">腿:</span> <span class="font-mono">{{ p.proposal_snapshot?.leg }}</span></div>
                    <div><span class="text-text-tertiary">数量:</span> <span class="font-mono">{{ p.proposal_snapshot?.qty }}</span></div>
                    <div><span class="text-text-tertiary">置信度:</span>
                      <span class="font-mono" :class="(p.proposal_snapshot?.confidence || 0) > 0.5 ? 'text-success' : 'text-warning'">
                        {{ ((p.proposal_snapshot?.confidence || 0) * 100).toFixed(0) }}%
                      </span>
                    </div>
                  </div>
                </div>"""

c = c.replace(old_rationale, new_rationale, 1)

# 3. Add proposalStats computed + adjusted table to show source_decision_id
# Add computed after newProp ref
old_new_prop = """const newProp = ref({
  title: '', rationale: '', config_diff_text: '', target_id: null,
  est_position_pct: null, json_err: null,
})"""

new_new_prop = """const newProp = ref({
  title: '', rationale: '', config_diff_text: '', target_id: null,
  est_position_pct: null, json_err: null,
})

const proposalStats = ref({ pending: 0, approved: 0, rejected: 0, rolled_back: 0 })
function updateStats() {
  const all = items.value
  proposalStats.value = {
    pending: all.filter(p => p.status === 'pending').length,
    approved: all.filter(p => p.status === 'approved').length,
    rejected: all.filter(p => p.status === 'rejected').length,
    rolled_back: all.filter(p => p.status === 'rolled_back').length,
  }
}"""

c = c.replace(old_new_prop, new_new_prop, 1)

# 4. Call updateStats after reload
old_reload_end = """    items.value = r.data?.items || []
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}"""

new_reload_end = """    items.value = r.data?.items || []
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
    updateStats()
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}"""

c = c.replace(old_reload_end, new_reload_end, 1)

with open(path, "w") as f:
    f.write(c)
print("Proposals.vue: statistics header + decision-linked display added")
