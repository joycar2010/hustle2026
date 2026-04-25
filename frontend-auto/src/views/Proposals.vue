<template>
  <div class="space-y-4">
    <!-- Header + filters -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary flex flex-wrap justify-between items-center gap-3">
      <div>
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
      </div>
      <div class="flex flex-wrap gap-2 text-xs items-center">
        <span class="text-text-tertiary">目标:</span>
        <button @click="setTarget(null)"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">全部</button>
        <button v-for="t in targets" :key="t.id" @click="setTarget(t.id)"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">
          {{ t.username }}/{{ t.pair_code }}
        </button>
        <span class="text-text-tertiary">|</span>
        <button v-for="f in filters" :key="f.key" @click="setStatus(f.key)"
          class="px-2 py-1 rounded text-[11px]"
          :class="filterStatus === f.key ? statusActiveClass(f.key) : 'bg-dark-200 text-text-secondary'">
          {{ f.label }}
        </button>
        <input v-model="searchText" @keyup.enter="reload()" placeholder="标题 / 推理"
          class="bg-dark-200 border border-border-primary rounded px-2 py-1 w-44">
        <button @click="reload()" class="px-3 py-1 rounded bg-primary text-dark-300 font-semibold">应用</button>
        <button @click="showCreate = !showCreate" class="ml-2 px-3 py-1.5 rounded bg-success text-dark-300 font-semibold text-xs">
          {{ showCreate ? '取消' : '+ 新建提议' }}
        </button>
      </div>
    </div>

    <!-- Strategy Evolution Overview -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-semibold text-text-tertiary">策略演化趋势</h3>
        <div class="flex gap-2 text-[10px]">
          <button v-for="w in evoWindows" :key="w.key" @click="evoWindow = w.key; loadEvolution()"
            class="px-2 py-0.5 rounded"
            :class="evoWindow === w.key ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary'">{{ w.label }}</button>
        </div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">
        <div class="bg-dark-200 rounded-lg p-2.5 text-center">
          <div class="text-[10px] text-text-tertiary">提议总数</div>
          <div class="font-mono font-bold text-lg">{{ evoStats.total }}</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-2.5 text-center">
          <div class="text-[10px] text-text-tertiary">批准率</div>
          <div class="font-mono font-bold text-lg" :class="evoStats.approveRate > 50 ? 'text-success' : 'text-warning'">{{ evoStats.approveRate }}%</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-2.5 text-center">
          <div class="text-[10px] text-text-tertiary">平均审批耗时</div>
          <div class="font-mono font-bold text-lg">{{ evoStats.avgReviewTime }}</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-2.5 text-center">
          <div class="text-[10px] text-text-tertiary">回滚次数</div>
          <div class="font-mono font-bold text-lg" :class="evoStats.rollbacks > 0 ? 'text-warning' : 'text-text-tertiary'">{{ evoStats.rollbacks }}</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-2.5 text-center">
          <div class="text-[10px] text-text-tertiary">最常变更键</div>
          <div class="font-mono text-sm text-primary truncate">{{ evoStats.topKey || '--' }}</div>
        </div>
      </div>
      <!-- Approval funnel bar -->
      <div class="flex items-center gap-1 text-[9px]">
        <span class="text-text-tertiary">状态分布:</span>
        <div class="flex-1 h-2 bg-dark-200 rounded-full overflow-hidden flex">
          <div class="bg-success h-full" :style="{width: evoStats.approvedPct + '%'}" title="approved"></div>
          <div class="bg-blue-500 h-full" :style="{width: evoStats.pendingPct + '%'}" title="pending"></div>
          <div class="bg-danger h-full" :style="{width: evoStats.rejectedPct + '%'}" title="rejected"></div>
          <div class="bg-warning h-full" :style="{width: evoStats.rolledBackPct + '%'}" title="rolled_back"></div>
        </div>
        <span class="text-success">批准</span>
        <span class="text-blue-400">待审</span>
        <span class="text-danger">拒绝</span>
        <span class="text-warning">回滚</span>
      </div>
    </div>

    <!-- AI 对话式创建提议 -->
    <div v-if="showCreate" class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
      <!-- Mode tabs -->
      <div class="flex border-b border-border-primary">
        <button @click="createMode = 'ai'"
          class="px-4 py-2.5 text-xs font-semibold transition"
          :class="createMode === 'ai' ? 'text-primary border-b-2 border-primary bg-dark-200' : 'text-text-tertiary hover:text-text-secondary'">
          AI 对话生成
        </button>
        <button @click="createMode = 'manual'"
          class="px-4 py-2.5 text-xs font-semibold transition"
          :class="createMode === 'manual' ? 'text-primary border-b-2 border-primary bg-dark-200' : 'text-text-tertiary hover:text-text-secondary'">
          手动 JSON
        </button>
        <div class="flex-1"></div>
        <button @click="showCreate = false" class="px-3 text-text-tertiary hover:text-text-primary text-sm">✕</button>
      </div>

      <!-- AI mode -->
      <div v-if="createMode === 'ai'" class="p-4 space-y-3">
        <!-- Chat history -->
        <div v-if="aiChat.length" class="space-y-2 max-h-80 overflow-y-auto">
          <div v-for="(msg, i) in aiChat" :key="i"
            class="flex" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
            <div class="max-w-[80%] rounded-lg px-3 py-2 text-xs"
              :class="msg.role === 'user' ? 'bg-primary/20 text-primary' : 'bg-dark-200 text-text-primary'">
              <div class="whitespace-pre-wrap">{{ msg.content }}</div>
            </div>
          </div>
          <div v-if="aiLoading" class="flex justify-start">
            <div class="bg-dark-200 rounded-lg px-3 py-2 text-xs text-text-tertiary animate-pulse">AI 思考中…</div>
          </div>
        </div>
        <div v-else class="text-xs text-text-tertiary py-4 text-center space-y-2">
          <div>用自然语言描述你的配置变更需求，AI 会生成对应的提议草稿</div>
          <div class="flex flex-wrap justify-center gap-2">
            <button v-for="eg in aiExamples" :key="eg" @click="aiInput = eg"
              class="px-2.5 py-1 bg-dark-200 rounded text-[10px] text-text-secondary hover:bg-dark-300 hover:text-text-primary transition">
              {{ eg }}
            </button>
          </div>
        </div>

        <!-- Input -->
        <div class="flex gap-2">
          <select v-model="aiTargetId" class="bg-dark-200 border border-border-primary rounded px-2 py-2 text-xs w-36 shrink-0">
            <option :value="null">全局</option>
            <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.username }}/{{ t.pair_code }}</option>
          </select>
          <input v-model="aiInput" @keyup.enter="sendAiDraft" :disabled="aiLoading"
            placeholder="例如：把单笔交易上限从 10% 提高到 15%"
            class="flex-1 bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
          <button @click="sendAiDraft" :disabled="aiLoading || !aiInput.trim()"
            class="px-4 py-2 bg-primary text-dark-300 font-semibold rounded text-xs hover:bg-primary-hover disabled:opacity-40 shrink-0">
            {{ aiLoading ? '生成中…' : '发送' }}
          </button>
        </div>

        <!-- AI Draft preview -->
        <div v-if="aiDraft" class="border border-primary/30 rounded-lg p-4 space-y-3 bg-dark-200/50">
          <div class="flex items-center justify-between">
            <div class="text-xs font-semibold text-primary">AI 生成的提议草稿</div>
            <div class="flex gap-2">
              <button @click="aiDraft = null; aiChat = []" class="text-[10px] text-text-tertiary hover:text-text-secondary">重置</button>
            </div>
          </div>

          <!-- Warnings -->
          <div v-if="aiDraft.warnings && aiDraft.warnings.length" class="space-y-1">
            <div v-for="(w, i) in aiDraft.warnings" :key="i"
              class="text-[10px] text-warning bg-warning/10 rounded px-2 py-1">⚠ {{ w }}</div>
          </div>

          <!-- Draft fields -->
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div class="lg:col-span-2">
              <div class="text-[10px] text-text-tertiary mb-1">标题</div>
              <input v-model="aiDraft.title" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-1.5 text-xs focus:border-primary outline-none">
            </div>
            <div>
              <div class="text-[10px] text-text-tertiary mb-1">作用范围</div>
              <select v-model="aiDraft.target_id" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-1.5 text-xs">
                <option :value="null">全局</option>
                <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.username }}/{{ t.pair_code }}</option>
              </select>
            </div>
            <div class="lg:col-span-3">
              <div class="text-[10px] text-text-tertiary mb-1">业务推理</div>
              <textarea v-model="aiDraft.rationale" rows="2"
                class="w-full bg-dark-300 border border-border-primary rounded px-3 py-1.5 text-xs focus:border-primary outline-none"></textarea>
            </div>
          </div>

          <!-- Config diff display -->
          <div>
            <div class="text-[10px] text-text-tertiary mb-1">config_diff (可编辑)</div>
            <div v-if="!aiDraftJsonMode" class="space-y-2">
              <div v-for="(val, key) in aiDraft.config_diff" :key="key"
                class="bg-dark-300 rounded p-2.5 border border-border-primary">
                <div class="flex items-baseline justify-between mb-1">
                  <span class="font-mono text-[11px] text-primary font-semibold">{{ key }}</span>
                </div>
                <div v-if="typeof val === 'object' && val !== null && !Array.isArray(val)" class="space-y-0.5">
                  <div v-for="(sv, sk) in val" :key="sk" class="flex justify-between text-[11px] gap-3">
                    <span class="text-text-secondary font-mono">{{ sk }}</span>
                    <span class="text-text-primary font-mono text-right">{{ sv }}</span>
                  </div>
                </div>
                <div v-else class="text-[11px] font-mono text-text-primary">{{ JSON.stringify(val) }}</div>
              </div>
            </div>
            <textarea v-else v-model="aiDraftJsonText" rows="4"
              class="w-full bg-dark-300 border border-border-primary rounded px-3 py-1.5 text-xs font-mono focus:border-primary outline-none"></textarea>
            <div class="flex items-center justify-between mt-1">
              <button @click="toggleDraftJson" class="text-[10px] text-primary hover:underline">
                {{ aiDraftJsonMode ? '切换可视化' : '切换 JSON 编辑' }}
              </button>
              <div v-if="aiDraftJsonErr" class="text-danger text-[10px]">{{ aiDraftJsonErr }}</div>
            </div>
          </div>

          <!-- Submit buttons -->
          <div class="flex items-center gap-2 pt-1">
            <button @click="submitAiDraft" class="px-4 py-2 bg-primary text-dark-300 font-semibold rounded text-xs hover:bg-primary-hover">确认提交待审批</button>
            <button @click="showCreate = false" class="px-4 py-2 bg-dark-300 text-text-secondary rounded text-xs">取消</button>
          </div>
        </div>

        <!-- Error -->
        <div v-if="aiError" class="text-danger text-xs bg-danger/10 rounded px-3 py-2">{{ aiError }}</div>
      </div>

      <!-- Manual mode (original) -->
      <div v-if="createMode === 'manual'" class="p-4">
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
              placeholder="为什么要改、预期收益、风险点"
              class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none font-mono"></textarea>
          </div>
          <div class="lg:col-span-3">
            <div class="text-xs text-text-tertiary mb-1">config_diff (JSON)</div>
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
            <th>审核时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="p in items" :key="p.id">
            <tr class="border-t border-border-primary hover:bg-dark-200 cursor-pointer" @click="toggle(p.id)">
              <td class="px-3 py-2 font-mono text-text-tertiary">#{{ p.id }}</td>
              <td class="font-mono text-text-tertiary" :title="p.created_at">{{ fmtTime(p.created_at) }}</td>
              <td>
                <span v-if="p.target_id" class="px-1.5 py-0.5 rounded text-[10px] bg-primary/20 text-primary">
                  {{ p.username }}/{{ p.pair_code }}
                </span>
                <span v-else class="px-1.5 py-0.5 rounded text-[10px] bg-dark-300 text-text-secondary">全局</span>
              </td>
              <td>{{ p.title }}</td>
              <td class="font-mono">{{ p.est_position_pct ? (p.est_position_pct * 100).toFixed(1) + '%' : '--' }}</td>
              <td><span class="px-1.5 py-0.5 rounded text-[10px]" :class="statusBadge(p.status)">{{ p.status }}</span></td>
              <td class="font-mono text-text-tertiary text-[10px]">{{ p.reviewed_at ? fmtTime(p.reviewed_at) : '—' }}</td>
              <td @click.stop>
                <div v-if="p.status === 'pending'" class="flex gap-1">
                  <button @click="approve(p)" class="px-2 py-0.5 bg-success/20 text-success rounded text-[10px] hover:bg-success/30">批准</button>
                  <button @click="reject(p)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">拒绝</button>
                </div>
              </td>
            </tr>
            <tr v-if="expanded === p.id" class="bg-dark-200">
              <td colspan="8" class="p-4 space-y-4">
                <!-- Rationale -->
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
                </div>

                <!-- Config diff card grid — old→new comparison -->
                <div>
                  <div class="text-text-tertiary text-[10px] mb-2 flex items-center gap-2">
                    CONFIG_DIFF (顶层 key 即将写入 active config)
                    <span v-if="activeConfigCache[p.id]" class="text-success text-[9px]">✓ 已加载当前值</span>
                    <span v-else class="text-text-tertiary text-[9px] animate-pulse">加载当前配置…</span>
                  </div>
                  <div v-if="!p.config_diff || !Object.keys(p.config_diff).length" class="text-text-tertiary text-[11px]">(空 diff)</div>
                  <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div v-for="(val, key) in p.config_diff" :key="key"
                         class="bg-dark-300 rounded p-3 border border-border-primary">
                      <div class="flex items-baseline justify-between mb-1">
                        <span class="font-mono text-[11px] text-primary font-semibold">{{ key }}</span>
                        <span class="text-[10px] text-text-tertiary">{{ summarizeType(val) }}</span>
                      </div>
                      <div v-if="isLeaf(val)" class="space-y-0.5">
                        <div class="flex items-center gap-2 text-xs font-mono">
                          <template v-if="activeConfigCache[p.id]">
                            <span class="line-through text-danger/70">{{ formatLeaf(getActiveVal(p.id, key)) }}</span>
                            <span class="text-text-tertiary">→</span>
                            <span class="text-success font-semibold">{{ formatLeaf(val) }}</span>
                          </template>
                          <span v-else class="text-text-primary">{{ formatLeaf(val) }}</span>
                        </div>
                      </div>
                      <div v-else class="space-y-0.5">
                        <div v-for="(sv, sk) in val" :key="sk" class="flex justify-between text-[11px] gap-3">
                          <span class="text-text-secondary font-mono">{{ sk }}</span>
                          <div class="flex items-center gap-1.5 font-mono text-right">
                            <template v-if="activeConfigCache[p.id]">
                              <span class="line-through text-danger/70 text-[10px]">{{ formatLeaf(getActiveSubVal(p.id, key, sk)) }}</span>
                              <span class="text-text-tertiary text-[10px]">→</span>
                              <span class="text-success font-semibold">{{ formatLeaf(sv) }}</span>
                            </template>
                            <span v-else class="text-text-primary">{{ formatLeaf(sv) }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Audit timeline (who approved / rejected) -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <div class="text-text-tertiary text-[10px]">审计轨迹</div>
                    <button v-if="!auditMap[p.id]" @click="loadAudit(p.id)"
                      class="text-[10px] text-primary hover:underline">查看</button>
                  </div>
                  <div v-if="auditLoading[p.id]" class="text-text-tertiary text-[11px]">加载中…</div>
                  <div v-else-if="auditMap[p.id]" class="space-y-1">
                    <div v-if="auditMap[p.id].length === 0" class="text-text-tertiary text-[11px]">无审计记录</div>
                    <div v-for="a in auditMap[p.id]" :key="a.id"
                         class="flex items-center gap-3 text-[11px] bg-dark-300 rounded px-2 py-1">
                      <span class="font-mono text-text-tertiary">{{ fmtTime(a.created_at) }}</span>
                      <span class="px-1.5 py-0.5 rounded text-[10px]" :class="auditActionBadge(a.action)">{{ a.action }}</span>
                      <span class="text-text-secondary">操作员：<span class="font-semibold">{{ a.actor_username || (a.actor_user_id || '').slice(0, 8) || '—' }}</span></span>
                      <span v-if="a.diff_keys && a.diff_keys.length" class="text-text-tertiary">
                        影响键：<span class="font-mono">{{ a.diff_keys.join(', ') }}</span>
                      </span>
                      <span v-if="a.reason" class="text-danger italic">理由：{{ a.reason }}</span>
                    </div>
                  </div>
                </div>

                <!-- Source decisions -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <div class="text-text-tertiary text-[10px]">关联决策（同一目标 · 提议创建前 24h）</div>
                    <button v-if="!sourceMap[p.id]" @click="loadSource(p.id)"
                      class="text-[10px] text-primary hover:underline">查看</button>
                  </div>
                  <div v-if="sourceLoading[p.id]" class="text-text-tertiary text-[11px]">加载中…</div>
                  <div v-else-if="sourceMap[p.id]" class="max-h-64 overflow-y-auto">
                    <div v-if="sourceMap[p.id].length === 0" class="text-text-tertiary text-[11px]">无关联决策（可能是全局提议或 24h 内无决策）</div>
                    <table v-else class="w-full text-[11px]">
                      <thead class="text-text-tertiary">
                        <tr><th class="text-left py-1">#</th><th>时间</th><th>触发</th><th>动作</th><th>conf</th><th>判决</th><th>原因</th></tr>
                      </thead>
                      <tbody>
                        <tr v-for="sd in sourceMap[p.id]" :key="sd.id" class="border-t border-border-primary">
                          <td class="py-1 font-mono text-text-tertiary">{{ sd.id }}</td>
                          <td class="font-mono text-text-tertiary">{{ fmtTime(sd.created_at) }}</td>
                          <td class="text-text-secondary">{{ sd.trigger }}</td>
                          <td class="font-mono">{{ sd.action }}</td>
                          <td class="font-mono text-text-tertiary">{{ Number(sd.confidence||0).toFixed(2) }}</td>
                          <td><span class="px-1 py-0.5 rounded text-[10px]" :class="verdictBadge(sd.verdict)">{{ sd.verdict }}</span></td>
                          <td class="text-text-secondary truncate max-w-[260px]" :title="sd.reject_reason || sd.reason">{{ sd.reject_reason || sd.reason }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-if="items.length === 0 && !loading" class="p-6 text-center text-text-tertiary text-sm">无符合条件的提议</div>
      <div v-if="loading" class="p-4 text-center text-text-tertiary text-sm">加载中…</div>
      <div v-if="hasMore && !loading" class="p-3 text-center">
        <button @click="loadMore()" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-300 text-text-secondary rounded text-xs">加载更多</button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'
import { useWsStream } from '@/stores/wsStream.js'

const PAGE = 50
const evoWindows = [
  { key: '7d', label: '7天' },
  { key: '30d', label: '30天' },
  { key: 'all', label: '全部' },
]
const evoWindow = ref('7d')
const evoStats = ref({ total: 0, approveRate: 0, avgReviewTime: '--', rollbacks: 0, topKey: '', approvedPct: 0, pendingPct: 0, rejectedPct: 0, rolledBackPct: 0 })

async function loadEvolution() {
  try {
    const w = evoWindow.value
    const wq = w !== 'all' ? '?window=' + w : ''
    const r = await api.get('/api/v1/agent/proposals/stats' + wq)
    const d = r.data || {}
    const bs = d.by_status || {}
    const total = d.total || 0
    const approved = bs.approved || 0
    const pending = bs.pending || 0
    const rejected = bs.rejected || 0
    const rolledBack = bs.rolled_back || 0
    evoStats.value = {
      total,
      approveRate: total ? (approved / total * 100).toFixed(0) : 0,
      avgReviewTime: d.avg_review_hours != null ? d.avg_review_hours.toFixed(1) + 'h' : '--',
      rollbacks: rolledBack,
      topKey: d.top_changed_key || '--',
      approvedPct: total ? (approved / total * 100).toFixed(1) : 0,
      pendingPct: total ? (pending / total * 100).toFixed(1) : 0,
      rejectedPct: total ? (rejected / total * 100).toFixed(1) : 0,
      rolledBackPct: total ? (rolledBack / total * 100).toFixed(1) : 0,
    }
  } catch {
    // Fallback: compute from loaded items
    const all = items.value
    const total = all.length || 1
    const approved = all.filter(p => p.status === 'approved').length
    const pending = all.filter(p => p.status === 'pending').length
    const rejected = all.filter(p => p.status === 'rejected').length
    const rolledBack = all.filter(p => p.status === 'rolled_back').length
    evoStats.value = {
      total: all.length, approveRate: (approved / total * 100).toFixed(0),
      avgReviewTime: '--', rollbacks: rolledBack, topKey: '--',
      approvedPct: (approved / total * 100).toFixed(1),
      pendingPct: (pending / total * 100).toFixed(1),
      rejectedPct: (rejected / total * 100).toFixed(1),
      rolledBackPct: (rolledBack / total * 100).toFixed(1),
    }
  }
}
const filters = [
  { key: '全部', label: '全部' },
  { key: 'pending', label: 'pending' },
  { key: 'approved', label: 'approved' },
  { key: 'rejected', label: 'rejected' },
  { key: 'rolled_back', label: 'rolled_back' },
]

const items = ref([])
const targets = ref([])
const expanded = ref(null)
const showCreate = ref(false)
const filterStatus = ref('pending')
const filterTarget = ref(null)
const searchText = ref('')
const hasMore = ref(false)
const nextCursor = ref(null)
const loading = ref(false)
const sourceMap = ref({})
const activeConfigCache = ref({})
const sourceLoading = ref({})
const auditMap = ref({})
const auditLoading = ref({})

const newProp = ref({
  title: '', rationale: '', config_diff_text: '', target_id: null,
  est_position_pct: null, json_err: null,
})

const createMode = ref('ai')
const aiInput = ref('')
const aiTargetId = ref(null)
const aiChat = ref([])
const aiDraft = ref(null)
const aiLoading = ref(false)
const aiError = ref('')
const aiDraftJsonMode = ref(false)
const aiDraftJsonText = ref('')
const aiDraftJsonErr = ref('')

const aiExamples = [
  '把单笔交易上限提高到 15%',
  '净资产守卫警告阈值调到 0.85',
  '每分钟最大决策数改为 5',
  'LLM 余额告警阈值设为 50 元',
]

async function sendAiDraft() {
  const msg = aiInput.value.trim()
  if (!msg || aiLoading.value) return
  aiError.value = ''
  aiChat.value.push({ role: 'user', content: msg })
  aiInput.value = ''
  aiLoading.value = true
  try {
    const history = aiChat.value.slice(0, -1).map(m => ({ role: m.role, content: m.content }))
    const r = await api.post('/api/v1/agent/proposals/ai-draft', {
      message: msg,
      target_id: aiTargetId.value,
      history: history.length ? history : undefined,
    })
    if (r.data?.ok && r.data.draft) {
      const d = r.data.draft
      aiDraft.value = { ...d }
      aiDraftJsonText.value = JSON.stringify(d.config_diff, null, 2)
      aiDraftJsonMode.value = false
      aiDraftJsonErr.value = ''
      const summary = '已生成提议草稿：「' + d.title + '」\n变更键: ' + Object.keys(d.config_diff || {}).join(', ')
        + (d.warnings?.length ? '\n⚠ ' + d.warnings.join('\n⚠ ') : '')
      aiChat.value.push({ role: 'assistant', content: summary })
    } else {
      const errMsg = r.data?.error || '生成失败'
      aiError.value = errMsg
      aiChat.value.push({ role: 'assistant', content: '抱歉，' + errMsg + (r.data?.raw ? '\n原始返回: ' + r.data.raw.slice(0, 200) : '') })
    }
  } catch (e) {
    const msg2 = e.response?.data?.detail || e.message
    aiError.value = msg2
    aiChat.value.push({ role: 'assistant', content: '请求失败: ' + msg2 })
  } finally {
    aiLoading.value = false
  }
}

function toggleDraftJson() {
  if (aiDraftJsonMode.value) {
    try {
      aiDraft.value.config_diff = JSON.parse(aiDraftJsonText.value)
      aiDraftJsonErr.value = ''
      aiDraftJsonMode.value = false
    } catch (e) {
      aiDraftJsonErr.value = 'JSON 格式错误: ' + e.message
    }
  } else {
    aiDraftJsonText.value = JSON.stringify(aiDraft.value.config_diff, null, 2)
    aiDraftJsonMode.value = true
  }
}

async function submitAiDraft() {
  if (!aiDraft.value) return
  const d = aiDraft.value
  if (!d.title || !d.rationale) { alert('请填写标题和推理'); return }
  if (aiDraftJsonMode.value) {
    try { d.config_diff = JSON.parse(aiDraftJsonText.value) }
    catch (e) { aiDraftJsonErr.value = 'JSON 格式错误'; return }
  }
  try {
    await api.post('/api/v1/agent/proposals', {
      title: d.title,
      rationale: d.rationale,
      config_diff: d.config_diff,
      target_id: d.target_id,
      est_position_pct: d.est_position_pct,
    })
    aiDraft.value = null
    aiChat.value = []
    aiInput.value = ''
    showCreate.value = false
    await reload()
  } catch (e) { alert('创建失败: ' + (e.response?.data?.detail || e.message)) }
}

const proposalStats = ref({ pending: 0, approved: 0, rejected: 0, rolled_back: 0 })
function updateStats() {
  const all = items.value
  proposalStats.value = {
    pending: all.filter(p => p.status === 'pending').length,
    approved: all.filter(p => p.status === 'approved').length,
    rejected: all.filter(p => p.status === 'rejected').length,
    rolled_back: all.filter(p => p.status === 'rolled_back').length,
  }
}

function fmtTime(t) { return dayjs(t).format('MM-DD HH:mm') }
function toggle(id) {
  if (expanded.value === id) { expanded.value = null; return }
  expanded.value = id
  const p = items.value.find(x => x.id === id)
  if (p && p.config_diff && Object.keys(p.config_diff).length && !activeConfigCache.value[id]) {
    const tid = p.target_id
    const url = tid ? '/api/v1/agent/config?target_id=' + tid : '/api/v1/agent/config'
    api.get(url).then(r => { activeConfigCache.value[id] = r.data || {} }).catch(() => {})
  }
}
function getActiveVal(pid, key) {
  const cfg = activeConfigCache.value[pid]
  return cfg ? cfg[key] : undefined
}
function getActiveSubVal(pid, key, subKey) {
  const cfg = activeConfigCache.value[pid]
  const block = cfg ? cfg[key] : undefined
  return block && typeof block === 'object' ? block[subKey] : undefined
}
function statusBadge(s) {
  return ({
    pending: 'bg-blue-900/30 text-blue-400',
    approved: 'bg-success/20 text-success',
    rejected: 'bg-danger/20 text-danger',
    rolled_back: 'bg-warning/20 text-warning',
  })[s] || 'bg-dark-300 text-text-tertiary'
}
function statusActiveClass(s) {
  return ({
    pending:  'bg-blue-900/40 text-blue-400 font-semibold',
    approved: 'bg-success/30 text-success font-semibold',
    rejected: 'bg-danger/30 text-danger font-semibold',
    rolled_back: 'bg-warning/30 text-warning font-semibold',
  })[s] || 'bg-primary text-dark-300 font-semibold'
}
function verdictBadge(v) {
  return ({
    executed: 'bg-success/20 text-success',
    shadow: 'bg-yellow-900/30 text-yellow-400',
    pending: 'bg-blue-900/30 text-blue-400',
    rejected: 'bg-danger/20 text-danger',
  })[v] || 'bg-dark-200 text-text-tertiary'
}

function isLeaf(v) {
  return v == null || typeof v !== 'object' || Array.isArray(v)
}
function summarizeType(v) {
  if (v == null) return 'null'
  if (typeof v === 'boolean') return 'bool'
  if (typeof v === 'number') return 'number'
  if (typeof v === 'string') return 'string'
  if (Array.isArray(v)) return 'array(' + v.length + ')'
  return 'object(' + Object.keys(v).length + ')'
}
function formatLeaf(v) {
  if (v == null) return 'null'
  if (Array.isArray(v)) return '[' + v.map(formatLeaf).join(', ') + ']'
  if (typeof v === 'number') {
    // Auto-percent obvious 0~1 ratios
    if (v > 0 && v <= 1) return v + ''
    return v + ''
  }
  return String(v)
}

function _params({ cursor } = {}) {
  const p = { limit: PAGE, status_filter: filterStatus.value === '全部' ? 'all' : filterStatus.value }
  if (filterTarget.value != null) p.target_id = filterTarget.value
  if (cursor != null) p.cursor = cursor
  if (searchText.value) p.q = searchText.value
  return p
}

async function reload() {
  loading.value = true
  try {
    const r = await api.get('/api/v1/agent/proposals', { params: _params() })
    items.value = r.data?.items || []
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
    updateStats()
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}
async function loadMore() {
  if (!hasMore.value || loading.value || nextCursor.value == null) return
  loading.value = true
  try {
    const r = await api.get('/api/v1/agent/proposals', { params: _params({ cursor: nextCursor.value }) })
    const seen = new Set(items.value.map(x => x.id))
    for (const it of (r.data?.items || [])) if (!seen.has(it.id)) items.value.push(it)
    nextCursor.value = r.data?.next_cursor ?? null
    hasMore.value = !!r.data?.has_more
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function loadSource(pid) {
  if (sourceMap.value[pid] || sourceLoading.value[pid]) return
  sourceLoading.value[pid] = true
  try {
    const r = await api.get('/api/v1/agent/proposals/' + pid + '/source-decisions', { params: { limit: 50 } })
    sourceMap.value[pid] = r.data?.items || []
  } catch (e) { sourceMap.value[pid] = [] }
  finally { sourceLoading.value[pid] = false }
}

async function loadAudit(pid) {
  if (auditMap.value[pid] || auditLoading.value[pid]) return
  auditLoading.value[pid] = true
  try {
    const r = await api.get('/api/v1/agent/proposals/' + pid + '/audit')
    auditMap.value[pid] = r.data?.items || []
  } catch (e) { auditMap.value[pid] = [] }
  finally { auditLoading.value[pid] = false }
}
function auditActionBadge(a) {
  return ({
    approved: 'bg-success/20 text-success',
    rejected: 'bg-danger/20 text-danger',
    created:  'bg-blue-900/30 text-blue-400',
    rolled_back: 'bg-warning/20 text-warning',
  })[a] || 'bg-dark-300 text-text-tertiary'
}

function setStatus(s) { filterStatus.value = s; reload() }
function setTarget(tid) { filterTarget.value = tid; reload() }

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
    await reload()
  } catch (e) { alert('创建失败: ' + (e.response?.data?.detail || e.message)) }
}

async function approve(p) {
  const scope = p.target_id ? '目标 #' + p.target_id + ' (' + p.username + '/' + p.pair_code + ')' : '全局（所有目标）'
  if (!confirm('批准并立即热加载提议 #' + p.id + '？\n作用范围: ' + scope + '\n影响键: ' + Object.keys(p.config_diff || {}).join(', '))) return
  try { await api.post('/api/v1/agent/strategy-proposals/' + p.id + '/approve'); await reload() }
  catch (e) { alert('批准失败: ' + (e.response?.data?.detail || e.message)) }
}
async function reject(p) {
  if (!confirm('拒绝提议 #' + p.id + '？')) return
  try { await api.post('/api/v1/agent/strategy-proposals/' + p.id + '/reject', { reason: '操作员拒绝' }); await reload() }
  catch (e) { alert('拒绝失败: ' + (e.response?.data?.detail || e.message)) }
}

const ws = useWsStream()
let timer, wsStop
onMounted(async () => {
  try {
    const ts = await api.get('/api/v1/agent/scope/targets')
    targets.value = ts.data?.items?.filter(t => t.enabled) || []
  } catch {}
  await reload()
  loadEvolution()
  timer = setInterval(() => { reload(); loadEvolution() }, 30000)  // slower HTTP safety poll; WS is primary
  ws.connect()
  ws.subscribe('agent.proposals')
  wsStop = watch(() => ws.channels['agent.proposals'], (payload) => {
    // Any lifecycle event (approved / rejected / created) — invalidate list
    // and any cached audit for the affected id.
    if (!payload) return
    if (payload.id != null) {
      delete auditMap.value[payload.id]
    }
    reload()
  })
})
onUnmounted(() => {
  clearInterval(timer)
  try { ws.unsubscribe('agent.proposals') } catch {}
  if (wsStop) wsStop()
})
</script>
