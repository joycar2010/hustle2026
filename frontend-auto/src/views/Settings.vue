<template>
  <div class="space-y-4 max-w-6xl">
    <!-- LLM 健康状态 -->
    <div v-if="llmHealth" class="bg-dark-100 rounded-xl p-4 border" :class="llmHealth.circuit_open ? 'border-danger' : 'border-border-primary'">
      <div class="flex items-center justify-between">
        <h3 class="font-semibold text-sm flex items-center gap-2">
          LLM 服务健康
          <span class="px-2 py-0.5 rounded text-[10px]"
            :class="llmHealth.circuit_open ? 'bg-danger/20 text-danger' : 'bg-success/20 text-success'">
            {{ llmHealth.circuit_open ? '熔断中' : '正常' }}
          </span>
        </h3>
        <span class="flex items-center gap-2">
          <button v-if="llmHealth.circuit_open" @click="resetCircuit" :disabled="resettingCircuit"
            class="text-xs px-3 py-1 bg-danger/20 text-danger border border-danger/40 rounded hover:bg-danger/30 disabled:opacity-40">
            {{ resettingCircuit ? '恢复中…' : '手动恢复' }}
          </button>
          <button @click="loadLlmHealth" class="text-xs text-primary hover:underline">刷新</button>
        </span>
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
        <div>
          <div class="text-text-tertiary">退避策略</div>
          <div class="text-[10px]">{{ llmHealth.consecutive_trips || 0 }}次连续触发 · 冷却{{ llmHealth.current_cooldown_s || 60 }}s</div>
          <div class="text-[10px] text-text-tertiary">60s→120s→240s→480s 指数退避</div>
        </div>
        <div v-if="llmHealth.circuit_open" class="lg:col-span-5">
          <div class="text-danger text-[10px]">⚠ 熔断中（第{{ llmHealth.consecutive_trips }}次）：所有LLM调用返回noop，自动探测恢复中</div>
        </div>
      </div>
    </div>

    <!-- 中转站管理（含模型配置） -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold">中转站管理 <span class="text-xs text-text-tertiary font-normal ml-2">主从自动切换 · 热加载</span></h3>
        <button @click="showAddRelay = true" class="text-xs px-3 py-1 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover">+ 添加中转站</button>
      </div>

      <!-- Add relay form -->
      <div v-if="showAddRelay" class="bg-dark-200 rounded-lg p-4 mb-3 border border-border-primary">
        <div class="text-sm font-semibold mb-2">添加中转站</div>
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <div>
            <div class="text-xs text-text-tertiary mb-1">名称</div>
            <input v-model="newRelay.name" placeholder="如: backup-relay" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">chesspnt API 地址</div>
            <input v-model="newRelay.api_base" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">LLM 转发地址</div>
            <input v-model="newRelay.llm_base_url" placeholder="http://host:port" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">LLM API Key</div>
            <input v-model="newRelay.llm_api_key" type="password" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">chesspnt 用户名</div>
            <input v-model="newRelay.chesspnt_username" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
          <div>
            <div class="text-xs text-text-tertiary mb-1">chesspnt 密码</div>
            <input v-model="newRelay.chesspnt_password" type="password" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
          </div>
        </div>
        <div class="flex items-center gap-2 mt-3">
          <button @click="addRelay" class="px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover text-sm">添加</button>
          <button @click="showAddRelay = false" class="px-4 py-2 bg-dark-300 border border-border-primary rounded text-sm">取消</button>
          <div class="text-xs text-text-tertiary ml-2">角色默认"备用"，添加后可设为主站</div>
        </div>
      </div>

      <!-- Relay station list -->
      <div v-if="!relayStations.length" class="text-text-tertiary text-sm py-4 text-center">尚无中转站 — 添加至少一个</div>
      <div v-for="rs in relayStations" :key="rs.id" class="mb-3 border rounded-lg overflow-hidden"
        :class="rs.role === 'primary' ? 'border-primary/50' : 'border-border-primary'">
        <!-- Station header row -->
        <div class="flex items-center justify-between px-4 py-2.5 bg-dark-200/50 cursor-pointer" @click="toggleExpand(rs.id)">
          <div class="flex items-center gap-2">
            <span class="text-xs px-1.5 py-0.5 rounded font-bold"
              :class="rs.role === 'primary' ? 'bg-primary/20 text-primary' : 'bg-dark-300 text-text-tertiary'">
              {{ rs.role === 'primary' ? '主' : '备' }}
            </span>
            <span class="font-semibold text-sm">{{ rs.name }}</span>
            <span class="text-xs px-1.5 py-0.5 rounded"
              :class="rs.enabled ? 'bg-success/20 text-success' : 'bg-danger/20 text-danger'">
              {{ rs.enabled ? '启用' : '禁用' }}
            </span>
            <span class="text-xs px-1.5 py-0.5 rounded"
              :class="rs.cookie_set ? 'bg-success/20 text-success' : 'bg-warning/20 text-warning'">
              {{ rs.cookie_set ? 'Cookie✓' : 'Cookie✗' }}
            </span>
            <span class="text-xs text-text-tertiary font-mono">{{ rs.model || '--' }}</span>
          </div>
          <div class="flex items-center gap-2">
            <button v-if="rs.role !== 'primary'" @click.stop="setAsPrimary(rs)" class="text-[10px] px-2 py-0.5 bg-primary/20 text-primary rounded hover:bg-primary/30">设为主站</button>
            <button @click.stop="toggleStation(rs)" class="text-[10px] px-2 py-0.5 rounded"
              :class="rs.enabled ? 'bg-danger/20 text-danger hover:bg-danger/30' : 'bg-success/20 text-success hover:bg-success/30'">
              {{ rs.enabled ? '禁用' : '启用' }}
            </button>
            <button @click.stop="deleteStation(rs)" class="text-[10px] px-2 py-0.5 bg-danger/20 text-danger rounded hover:bg-danger/30">删除</button>
            <span class="text-text-tertiary text-xs">{{ expandedRelay === rs.id ? '▼' : '▶' }}</span>
          </div>
        </div>

        <!-- Expanded detail -->
        <div v-if="expandedRelay === rs.id" class="px-4 py-3 space-y-3 bg-dark-100">
          <!-- Connection info -->
          <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            <div>
              <div class="text-text-tertiary mb-1">chesspnt API</div>
              <input v-model="rs.api_base" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs font-mono focus:border-primary outline-none">
            </div>
            <div>
              <div class="text-text-tertiary mb-1">LLM 转发地址</div>
              <input v-model="rs.llm_base_url" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs font-mono focus:border-primary outline-none">
            </div>
            <div>
              <div class="text-text-tertiary mb-1">用户名</div>
              <input v-model="rs.chesspnt_username" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs font-mono focus:border-primary outline-none">
            </div>
            <div>
              <div class="text-text-tertiary mb-1">API User ID</div>
              <input v-model="rs.new_api_user" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs font-mono focus:border-primary outline-none">
            </div>
          </div>

          <!-- Model config (merged from Codex) -->
          <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            <div>
              <div class="text-text-tertiary mb-1 flex items-center justify-between">
                <span>模型 ({{ (rs.available_models || []).length }})</span>
                <button @click="refreshStationModels(rs)" :disabled="rs._refreshing"
                  class="text-[10px] px-1.5 py-0.5 bg-dark-200 border border-border-primary rounded hover:border-primary disabled:opacity-40">
                  {{ rs._refreshing ? '…' : '🔄' }}
                </button>
              </div>
              <select v-model="rs.model" class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs focus:border-primary outline-none">
                <option v-for="m in rs.available_models || []" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
            <div>
              <div class="text-text-tertiary mb-1">流式</div>
              <label class="flex items-center gap-2 mt-1">
                <input type="checkbox" v-model="rs.streaming" class="accent-primary">
                <span>stream=true</span>
              </label>
            </div>
            <div>
              <div class="text-text-tertiary mb-1">低额告警(¥)</div>
              <input v-model.number="rs.balance_alert_threshold_cny" type="number" step="1" min="0"
                class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs font-mono focus:border-primary outline-none">
            </div>
            <div>
              <div class="text-text-tertiary mb-1">Units/USD</div>
              <input v-model.number="rs.units_per_usd" type="number" step="1000" min="1"
                class="w-full bg-dark-200 border border-border-primary rounded px-2 py-1.5 text-xs font-mono focus:border-primary outline-none">
            </div>
          </div>

          <!-- Actions row -->
          <div class="flex items-center gap-2 flex-wrap">
            <button @click="saveStation(rs)" class="px-3 py-1.5 bg-primary text-dark-300 font-semibold rounded text-xs hover:bg-primary-hover">保存配置</button>
            <button @click="refreshStationCookie(rs)" :disabled="rs._cookieRefreshing"
              class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded text-xs hover:border-primary disabled:opacity-40">
              {{ rs._cookieRefreshing ? '刷新中…' : '刷新 Cookie' }}
            </button>
            <span v-if="rs._status" class="text-xs" :class="rs._status.startsWith('✅') ? 'text-success' : 'text-danger'">{{ rs._status }}</span>
          </div>
        </div>
      </div>

      <!-- Token stats (from active primary) -->
      <div v-if="stats" class="grid grid-cols-2 lg:grid-cols-5 gap-3 text-xs border-t border-border-primary pt-3 mt-3">
        <div>
          <div class="text-text-tertiary">今日 tokens</div>
          <div class="font-mono font-bold text-base">{{ fmtInt(stats.tokens_today?.total) }}</div>
          <div class="text-[10px] text-text-tertiary">{{ stats.tokens_today?.calls }} 次</div>
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
          <div class="text-text-tertiary">
            {{ stats.balance?.source === 'chesspnt_self' ? '钱包余额' : '中转站消耗' }}
          </div>
          <div class="font-mono font-bold text-base" :class="balanceColor">
            {{ stats.balance?.source === 'chesspnt_self'
               ? '$' + (stats.balance?.balance_usd?.toFixed(2) ?? '--')
               : ('¥' + (stats.balance?.spent_cny?.toFixed(4) ?? '--')) }}
          </div>
        </div>
        <div>
          <div class="text-text-tertiary">活跃中转站</div>
          <div class="font-mono text-primary text-sm">{{ stats.active_relay_name || '--' }}</div>
          <div class="text-[10px] text-text-tertiary">{{ stats.balance?.source === 'chesspnt_self' ? '直连' : 'relay' }}</div>
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
              <button @click="editCaps(t)" class="px-2 py-0.5 bg-primary/20 text-primary rounded text-[10px] hover:bg-primary/30 mr-1">风控</button>
              <button @click="removeTarget(t)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <!-- Per-target risk cap editor -->
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
import { useWsStream } from '@/stores/wsStream.js'
import { watch } from 'vue'
import dayjs from 'dayjs'

const wsStore = useWsStream()
wsStore.subscribe('agent.status')
wsStore.subscribe('agent.llm-stats')
watch(() => wsStore.channels['agent.llm-stats'], (v) => { if (v) stats.value = { ...(stats.value||{}), balance: v } })
const status = ref(null)
// Push-update: when agent.status arrives via stream, mirror into local status ref
watch(() => wsStore.channels['agent.status'], (val) => { if (val) status.value = { ...(status.value||{}), ...val } }, { deep: true })

const interventions = ref([])
const config = ref({})
const stats = ref(null)
const scopeOpts = ref({ users: [], pair_codes: [] })
const llm = reactive({ model: 'gpt-5', streaming: true, balance_alert_threshold_cny: 20, available_models: [] })
const targets = ref([])
const newTarget = ref({ user_id: null, pair_code: null, priority: 0 })

const modes = [
  { key: 'shadow', label: 'Shadow', desc: '只观察记录，不下单。建议至少 7 天。' },
  { key: 'semi', label: '半自动', desc: '入 pending 需审批后执行。' },
  { key: 'auto', label: '全自动', desc: 'Guard 通过即执行。' },
  { key: 'off', label: '已停机', desc: '关闭 LLM 决策。' },
]

const balanceColor = computed(() => {
  const b = stats.value?.balance?.balance_usd
  if (b == null) return 'text-text-primary'
  if (b < 3) return 'text-danger'
  if (b < 15) return 'text-warning'
  return 'text-success'
})

const refreshingSession = ref(false)
const sessionStatus = ref('')
const refreshingModels = ref(false)
const modelsRefreshStatus = ref('')
const resettingCircuit = ref(false)
const relayStations = ref([])
const expandedRelay = ref(null)
const showAddRelay = ref(false)
const newRelay = reactive({
  name: '', api_base: 'https://api.chesspnt.com', llm_base_url: '', llm_api_key: '',
  chesspnt_username: '', chesspnt_password: '',
})

async function resetCircuit() {
  resettingCircuit.value = true
  try {
    const r = await api.post('/api/v1/agent/llm-health/reset')
    if (r.data?.ok) { await loadLlmHealth(); alert('熔断器已重置') }
    else alert('重置失败: ' + (r.data?.error || '未知错误'))
  } catch (e) { alert('重置失败: ' + (e.response?.data?.detail || e.message)) }
  finally { resettingCircuit.value = false }
}

async function loadRelayStations() {
  try {
    const r = await api.get('/api/v1/agent/relay-stations')
    relayStations.value = (r.data?.items || []).map(s => ({ ...s, _refreshing: false, _cookieRefreshing: false, _status: '' }))
  } catch (e) { console.error('loadRelayStations:', e) }
}

function toggleExpand(id) {
  expandedRelay.value = expandedRelay.value === id ? null : id
}

async function addRelay() {
  try {
    const r = await api.post('/api/v1/agent/relay-stations', { ...newRelay })
    if (r.data?.ok) {
      showAddRelay.value = false
      Object.assign(newRelay, { name: '', api_base: 'https://api.chesspnt.com', llm_base_url: '', llm_api_key: '', chesspnt_username: '', chesspnt_password: '' })
      await loadRelayStations()
    }
  } catch (e) { alert('添加失败: ' + (e.response?.data?.detail || e.message)) }
}

async function saveStation(rs) {
  try {
    const body = {
      name: rs.name, api_base: rs.api_base, llm_base_url: rs.llm_base_url,
      chesspnt_username: rs.chesspnt_username, new_api_user: rs.new_api_user,
      model: rs.model, streaming: rs.streaming,
      balance_alert_threshold_cny: rs.balance_alert_threshold_cny,
      units_per_usd: rs.units_per_usd, available_models: rs.available_models,
    }
    const r = await api.put('/api/v1/agent/relay-stations/' + rs.id, body)
    if (r.data?.ok) { rs._status = '✅ 已保存'; setTimeout(() => { rs._status = '' }, 3000) }
  } catch (e) { alert('保存失败: ' + (e.response?.data?.detail || e.message)) }
}

async function toggleStation(rs) {
  try {
    await api.post('/api/v1/agent/relay-stations/' + rs.id + '/toggle', { enabled: !rs.enabled })
    await loadRelayStations()
  } catch (e) { alert('操作失败: ' + (e.response?.data?.detail || e.message)) }
}

async function setAsPrimary(rs) {
  if (!confirm('将 ' + rs.name + ' 设为主站？当前主站将降为备用。')) return
  try {
    await api.post('/api/v1/agent/relay-stations/' + rs.id + '/set-role', { role: 'primary' })
    await loadRelayStations()
  } catch (e) { alert('设置失败: ' + (e.response?.data?.detail || e.message)) }
}

async function deleteStation(rs) {
  if (!confirm('删除中转站 ' + rs.name + '？')) return
  try {
    await api.delete('/api/v1/agent/relay-stations/' + rs.id)
    await loadRelayStations()
  } catch (e) { alert('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

async function refreshStationCookie(rs) {
  rs._cookieRefreshing = true; rs._status = ''
  try {
    const r = await api.post('/api/v1/agent/relay-stations/' + rs.id + '/refresh-cookie')
    rs._status = r.data?.ok ? '✅ Cookie 已更新' : ('❌ ' + (r.data?.error || '失败'))
    if (r.data?.ok) await loadRelayStations()
  } catch (e) { rs._status = '❌ ' + (e.response?.data?.detail || e.message) }
  finally { rs._cookieRefreshing = false; setTimeout(() => { rs._status = '' }, 5000) }
}

async function refreshStationModels(rs) {
  rs._refreshing = true
  try {
    const r = await api.post('/api/v1/agent/relay-stations/' + rs.id + '/refresh-models')
    if (r.data?.ok) { rs.available_models = r.data.available_models; rs._status = '✅ ' + r.data.count + ' 模型' }
    else rs._status = '❌ ' + (r.data?.error || '失败')
  } catch (e) { rs._status = '❌ ' + (e.response?.data?.detail || e.message) }
  finally { rs._refreshing = false; setTimeout(() => { rs._status = '' }, 5000) }
}

// refreshModels and refreshChesspntSession are now per-station (see refreshStationModels/refreshStationCookie above)

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
    const res = await api.post('/api/v1/agent/llm-config', {
      model: llm.model, streaming: llm.streaming,
      balance_alert_threshold_cny: llm.balance_alert_threshold_cny,
    })
    if (res.data?.llm_settings) {
      Object.assign(llm, res.data.llm_settings)
    }
    alert('LLM 配置已保存: 模型=' + (res.data?.llm_settings?.model || llm.model))
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
      Promise.resolve(null),  // status now via WS stream channel agent.status
      api.get('/api/v1/agent/equity-interventions').catch(() => null),
      api.get('/api/v1/agent/llm-stats').catch(() => null),
      api.get('/api/v1/agent/scope-options').catch(() => null),
    ])
    if (s) status.value = s.data
    if (i) interventions.value = i.data?.items || []
    if (st) {
      stats.value = st.data
      Object.assign(llm, { model: st.data.model, streaming: st.data.streaming, available_models: st.data.available_models,
        balance_alert_threshold_cny: st.data.balance?.alert_threshold_cny ?? llm.balance_alert_threshold_cny })
    }
    if (so) { scopeOpts.value = so.data; if (so.data.current_scope) Object.assign(scope, so.data.current_scope) }
  } catch (e) { console.error(e) }
}

const editingCaps = ref(null)
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
  loadRelayStations()
  timer = setInterval(() => { refresh(); loadTargets(); loadLlmHealth(); loadRelayStations() }, 15000)
})
onUnmounted(() => clearInterval(timer))
</script>
// v2
