<template>
  <div class="space-y-4 max-w-6xl">
    <!-- LLM 健康状态 -->
    <div v-if="llmHealth" class="bg-dark-100 rounded-xl p-4 border" :class="circuitBorderClass">
      <div class="flex items-center justify-between">
        <h3 class="font-semibold text-sm flex items-center gap-2">
          LLM 服务健康
          <span class="px-2 py-0.5 rounded text-[10px]" :class="circuitBadgeClass">
            {{ circuitLabel }}
          </span>
        </h3>
        <span class="flex items-center gap-2">
          <button v-if="circuitState !== 'closed'" @click="resetCircuit" :disabled="resettingCircuit"
            class="text-xs px-3 py-1.5 border rounded font-semibold transition disabled:opacity-40"
            :class="circuitState === 'open'
              ? 'bg-danger/20 text-danger border-danger/40 hover:bg-danger/30'
              : 'bg-warning/20 text-warning border-warning/40 hover:bg-warning/30'">
            {{ resettingCircuit ? '恢复中…' : '手动恢复熔断器' }}
          </button>
          <button @click="loadLlmHealth" class="text-xs text-primary hover:underline">刷新</button>
        </span>
      </div>

      <!-- Circuit state visual bar -->
      <div class="mt-3 mb-1">
        <div class="flex items-center gap-2 text-[10px] mb-1">
          <span class="text-text-tertiary">熔断器状态:</span>
          <div class="flex items-center gap-1">
            <span class="w-2 h-2 rounded-full" :class="circuitState === 'closed' ? 'bg-success' : 'bg-dark-300'"></span>
            <span :class="circuitState === 'closed' ? 'text-success font-semibold' : 'text-text-tertiary'">关闭</span>
          </div>
          <span class="text-text-tertiary">→</span>
          <div class="flex items-center gap-1">
            <span class="w-2 h-2 rounded-full" :class="circuitState === 'half_open' ? 'bg-warning animate-pulse' : 'bg-dark-300'"></span>
            <span :class="circuitState === 'half_open' ? 'text-warning font-semibold' : 'text-text-tertiary'">半开</span>
          </div>
          <span class="text-text-tertiary">→</span>
          <div class="flex items-center gap-1">
            <span class="w-2 h-2 rounded-full" :class="circuitState === 'open' ? 'bg-danger animate-pulse' : 'bg-dark-300'"></span>
            <span :class="circuitState === 'open' ? 'text-danger font-semibold' : 'text-text-tertiary'">熔断</span>
          </div>
        </div>
        <div class="h-1.5 bg-dark-300 rounded-full overflow-hidden">
          <div class="h-full rounded-full transition-all duration-500"
            :class="circuitState === 'open' ? 'bg-danger' : circuitState === 'half_open' ? 'bg-warning' : 'bg-success'"
            :style="{ width: circuitState === 'open' ? '100%' : circuitState === 'half_open' ? '60%' : failureBarWidth + '%' }">
          </div>
        </div>
        <div class="flex justify-between text-[9px] text-text-tertiary mt-0.5">
          <span>0 失败</span>
          <span>阈值 {{ llmHealth.failure_threshold || '--' }}</span>
        </div>
      </div>

      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3 mt-2 text-xs">
        <div>
          <div class="text-text-tertiary">主模型</div>
          <div class="font-mono font-semibold">{{ llmHealth.primary_model || llmHealth.model || '--' }}</div>
        </div>
        <div>
          <div class="text-text-tertiary">降级模型</div>
          <div class="font-mono text-warning">{{ llmHealth.fallback_model || '--' }}</div>
        </div>
        <div>
          <div class="text-text-tertiary">5分钟内失败</div>
          <div class="font-mono" :class="(llmHealth.recent_failures || 0) > (llmHealth.failure_threshold || 5) * 0.6 ? 'text-danger' : 'text-text-primary'">
            {{ llmHealth.recent_failures ?? 0 }} / {{ llmHealth.failure_threshold ?? '--' }}
          </div>
        </div>
        <div>
          <div class="text-text-tertiary">熔断策略</div>
          <div class="text-[10px]">{{ llmHealth.failure_threshold || '--' }}次/{{ llmHealth.failure_window_s || '--' }}s → 冷却{{ llmHealth.current_cooldown_s || 120 }}s</div>
        </div>
        <div>
          <div class="text-text-tertiary">退避策略</div>
          <div class="text-[10px]">{{ llmHealth.consecutive_trips || 0 }}次连续触发 · 冷却{{ llmHealth.current_cooldown_s || 60 }}s</div>
          <div class="text-[10px] text-text-tertiary">60s→120s→240s→480s 指数退避</div>
        </div>
      </div>

      <!-- Circuit open/half_open alert banner -->
      <div v-if="circuitState === 'open'" class="mt-3 bg-danger/10 border border-danger/30 rounded-lg p-3 flex items-center justify-between">
        <div>
          <div class="text-danger text-xs font-semibold">⚠ 熔断中（第{{ llmHealth.consecutive_trips || 1 }}次触发）</div>
          <div class="text-danger/80 text-[10px] mt-0.5">所有 LLM 调用返回 noop · 冷却 {{ llmHealth.current_cooldown_s || 120 }}s 后自动探测恢复</div>
        </div>
        <button @click="resetCircuit" :disabled="resettingCircuit"
          class="px-4 py-2 bg-danger text-white rounded font-semibold text-xs hover:bg-danger/80 disabled:opacity-40 shrink-0">
          {{ resettingCircuit ? '恢复中…' : '立即恢复' }}
        </button>
      </div>
      <div v-else-if="circuitState === 'half_open'" class="mt-3 bg-warning/10 border border-warning/30 rounded-lg p-3 flex items-center justify-between">
        <div>
          <div class="text-warning text-xs font-semibold">⏳ 半开状态 — 探测恢复中</div>
          <div class="text-warning/80 text-[10px] mt-0.5">正在发送探测请求验证 LLM 可用性，若失败将重新熔断</div>
        </div>
        <button @click="resetCircuit" :disabled="resettingCircuit"
          class="px-4 py-2 bg-warning text-dark-300 rounded font-semibold text-xs hover:bg-warning/80 disabled:opacity-40 shrink-0">
          {{ resettingCircuit ? '恢复中…' : '强制恢复' }}
        </button>
      </div>
      <div v-if="resetStatus" class="mt-2 text-xs px-3 py-1.5 rounded" :class="resetStatus.startsWith('✅') ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'">
        {{ resetStatus }}
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

          <!-- Model config -->
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

    <!-- 生效配置审计视图 (只读) -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold flex items-center gap-2">
          生效配置
          <span class="text-[10px] text-text-tertiary font-normal px-1.5 py-0.5 bg-dark-200 rounded">只读 · 修改请走提案</span>
        </h3>
        <div class="flex items-center gap-2">
          <button @click="loadConfigAudit" class="px-3 py-1 bg-dark-200 text-text-secondary rounded text-xs hover:bg-dark-300">刷新</button>
          <router-link to="/proposals" class="px-3 py-1 bg-primary text-dark-300 rounded text-xs hover:bg-primary-hover font-semibold">+ 新建提案修改配置</router-link>
        </div>
      </div>

      <div v-if="configLoading" class="text-text-tertiary text-sm py-6 text-center">加载中…</div>

      <!-- Global config -->
      <div v-else>
        <div class="text-xs text-text-tertiary mb-2 font-semibold">全局基线配置</div>
        <div class="space-y-2 mb-4">
          <div v-for="item in globalConfig" :key="item.key"
            class="bg-dark-200 rounded-lg p-3 border border-border-primary overflow-hidden">
            <div class="flex items-center justify-between mb-2 cursor-pointer" @click="toggleConfigKey(item.key)">
              <div class="flex items-center gap-2">
                <span class="text-text-tertiary text-xs">{{ expandedConfigKeys[item.key] ? '▼' : '▶' }}</span>
                <span class="font-mono text-primary font-semibold text-sm">{{ configKeyLabel(item.key) }}</span>
                <span class="text-[10px] text-text-tertiary px-1.5 py-0.5 bg-dark-300 rounded">{{ countFields(item.value) }}</span>
              </div>
              <div class="flex items-center gap-3 text-[10px] text-text-tertiary">
                <span v-if="item.source_proposal_id" class="flex items-center gap-1">
                  来源: <router-link :to="'/proposals'" class="text-primary hover:underline font-mono" @click.stop>提案 #{{ item.source_proposal_id }}</router-link>
                </span>
                <span v-else class="text-text-tertiary">初始配置</span>
                <span v-if="item.updated_at">{{ fmtAuditTime(item.updated_at) }}</span>
              </div>
            </div>
            <div v-if="expandedConfigKeys[item.key]" class="mt-1">
              <div v-if="isSensitiveKey(item.key)" class="text-[10px] text-warning bg-warning/10 rounded px-2 py-1 mb-2">敏感配置，部分字段已脱敏</div>
              <table v-if="typeof item.value === 'object' && item.value !== null && !Array.isArray(item.value)" class="w-full text-xs">
                <tbody>
                  <tr v-for="(sv, sk) in item.value" :key="sk" class="border-b border-dark-300">
                    <td class="py-1 pr-3 text-text-tertiary font-mono whitespace-nowrap align-top w-48">{{ sk }}</td>
                    <td class="py-1 font-mono text-text-primary break-all">
                      <span v-if="isScalar(sv)">{{ maskSensitive(item.key, sk, sv) }}</span>
                      <div v-else-if="Array.isArray(sv)" class="space-y-0.5">
                        <span class="text-text-tertiary text-[10px]">[{{ sv.length }} 项]</span>
                        <div v-for="(av, ai) in sv.slice(0, 5)" :key="ai" class="bg-dark-300 rounded px-2 py-0.5 text-[10px] break-all">
                          {{ typeof av === 'object' ? summarizeObj(av) : maskSensitive(item.key, sk, av) }}
                        </div>
                        <div v-if="sv.length > 5" class="text-text-tertiary text-[10px]">… 还有 {{ sv.length - 5 }} 项</div>
                      </div>
                      <div v-else-if="typeof sv === 'object' && sv !== null" class="bg-dark-300 rounded px-2 py-1">
                        <div v-for="(ssv, ssk) in sv" :key="ssk" class="flex gap-2 text-[10px]">
                          <span class="text-text-tertiary shrink-0">{{ ssk }}:</span>
                          <span class="text-text-primary break-all">{{ maskSensitive(item.key, ssk, isScalar(ssv) ? ssv : summarizeObj(ssv)) }}</span>
                        </div>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-else-if="Array.isArray(item.value)" class="space-y-1">
                <div v-for="(av, ai) in item.value.slice(0, 10)" :key="ai" class="bg-dark-300 rounded px-2 py-1.5 text-[10px] font-mono break-all">
                  <div v-if="typeof av === 'object' && av !== null">
                    <div v-for="(fv, fk) in av" :key="fk" class="flex gap-2">
                      <span class="text-text-tertiary shrink-0">{{ fk }}:</span>
                      <span class="text-text-primary break-all">{{ maskSensitive(item.key, fk, isScalar(fv) ? fv : summarizeObj(fv)) }}</span>
                    </div>
                  </div>
                  <span v-else>{{ av }}</span>
                </div>
                <div v-if="item.value.length > 10" class="text-text-tertiary text-[10px]">… 还有 {{ item.value.length - 10 }} 项</div>
              </div>
              <div v-else class="text-xs font-mono text-text-primary break-all">{{ formatConfigVal(item.value) }}</div>
            </div>
          </div>
          <div v-if="!globalConfig.length" class="text-text-tertiary text-sm py-3 text-center">无全局配置</div>
        </div>

        <!-- Per-target overrides -->
        <div v-if="targetConfigs.length">
          <div class="text-xs text-text-tertiary mb-2 font-semibold">目标级覆盖配置</div>
          <div class="space-y-2">
            <div v-for="item in targetConfigs" :key="item.target_id + '-' + item.key"
              class="bg-dark-200 rounded-lg p-3 border border-warning/20 overflow-hidden">
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                  <span class="text-[10px] px-1.5 py-0.5 bg-warning/20 text-warning rounded font-semibold">覆盖</span>
                  <span class="font-semibold text-sm">{{ item.target_label }}</span>
                  <span class="font-mono text-primary text-xs">{{ configKeyLabel(item.key) }}</span>
                </div>
                <div class="flex items-center gap-3 text-[10px] text-text-tertiary">
                  <span v-if="item.source_proposal_id" class="flex items-center gap-1">
                    来源: <router-link :to="'/proposals'" class="text-primary hover:underline font-mono">提案 #{{ item.source_proposal_id }}</router-link>
                  </span>
                  <span v-if="item.updated_at">{{ fmtAuditTime(item.updated_at) }}</span>
                </div>
              </div>
              <table v-if="typeof item.value === 'object' && item.value !== null && !Array.isArray(item.value)" class="w-full text-xs">
                <tbody>
                  <tr v-for="(sv, sk) in item.value" :key="sk" class="border-b border-dark-300">
                    <td class="py-1 pr-3 text-text-tertiary font-mono whitespace-nowrap align-top w-48">{{ sk }}</td>
                    <td class="py-1 font-mono text-text-primary break-all">
                      <span v-if="isScalar(sv)">{{ sv }}</span>
                      <div v-else class="bg-dark-300 rounded px-2 py-1 text-[10px]">
                        <div v-for="(ssv, ssk) in sv" :key="ssk" class="flex gap-2">
                          <span class="text-text-tertiary shrink-0">{{ ssk }}:</span>
                          <span class="text-text-primary break-all">{{ isScalar(ssv) ? ssv : summarizeObj(ssv) }}</span>
                        </div>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="text-xs font-mono text-text-primary break-all">{{ formatConfigVal(item.value) }}</div>
            </div>
          </div>
        </div>

        <div class="mt-3 text-[10px] text-text-tertiary bg-dark-200 rounded px-3 py-2">
          配置变更须通过「提议中心」创建提案 → 审批通过 → 自动写入 agent_active_config / agent_target_config → config_loader 5s TTL 热加载生效。直接修改配置已禁用以防止绕过审批。
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import { useWsStream } from '@/stores/wsStream.js'

const wsStore = useWsStream()
wsStore.subscribe('agent.llm-stats')

const llmHealth = ref(null)
const stats = ref(null)
const relayStations = ref([])
const expandedRelay = ref(null)
const showAddRelay = ref(false)
const resettingCircuit = ref(false)
const globalConfig = ref([])
const targetConfigs = ref([])
const configLoading = ref(false)

const newRelay = reactive({
  name: '', api_base: 'https://api.chesspnt.com', llm_base_url: '', llm_api_key: '',
  chesspnt_username: '', chesspnt_password: '',
})

watch(() => wsStore.channels['agent.llm-stats'], (v) => {
  if (v) stats.value = { ...(stats.value || {}), balance: v }
})

const balanceColor = computed(() => {
  const b = stats.value?.balance?.balance_usd
  if (b == null) return 'text-text-primary'
  if (b < 3) return 'text-danger'
  if (b < 15) return 'text-warning'
  return 'text-success'
})

function fmtInt(n) { return n != null ? Number(n).toLocaleString() : '--' }

const resetStatus = ref('')

const circuitState = computed(() => {
  const h = llmHealth.value
  if (!h) return 'closed'
  if (h.circuit_state) return h.circuit_state
  if (h.circuit_open === true) return 'open'
  if (h.circuit_open === false) return 'closed'
  return 'unknown'
})

const circuitLabel = computed(() => {
  return ({ closed: '正常', open: '已熔断', half_open: '半开探测中', unknown: '未知' })[circuitState.value] || circuitState.value
})

const circuitBorderClass = computed(() => {
  return ({ open: 'border-danger', half_open: 'border-warning', closed: 'border-border-primary' })[circuitState.value] || 'border-border-primary'
})

const circuitBadgeClass = computed(() => {
  return ({
    open: 'bg-danger/20 text-danger animate-pulse',
    half_open: 'bg-warning/20 text-warning animate-pulse',
    closed: 'bg-success/20 text-success',
  })[circuitState.value] || 'bg-dark-300 text-text-tertiary'
})

const failureBarWidth = computed(() => {
  const h = llmHealth.value
  if (!h || !h.failure_threshold) return 0
  return Math.min(100, ((h.recent_failures || 0) / h.failure_threshold) * 100)
})

async function loadLlmHealth() {
  try {
    const r = await api.get('/api/v1/agent/llm-health')
    llmHealth.value = r.data
  } catch (e) { console.error('LLM health:', e) }
}

async function resetCircuit() {
  resettingCircuit.value = true
  resetStatus.value = ''
  try {
    const r = await api.post('/api/v1/agent/llm-health/reset')
    if (r.data?.ok) {
      resetStatus.value = '✅ 熔断器已重置，LLM 服务恢复正常'
      await loadLlmHealth()
    } else {
      resetStatus.value = '❌ 重置失败: ' + (r.data?.error || '未知错误')
    }
  } catch (e) {
    resetStatus.value = '❌ 重置失败: ' + (e.response?.data?.detail || e.message)
  }
  finally {
    resettingCircuit.value = false
    setTimeout(() => { resetStatus.value = '' }, 8000)
  }
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

async function loadStats() {
  try {
    const r = await api.get('/api/v1/agent/llm-stats')
    stats.value = r.data
  } catch {}
}

const expandedConfigKeys = ref({})

const SENSITIVE_FIELDS = ['cookie', 'token', 'api_key', 'llm_api_key', 'password', 'secret', 'chesspnt_password', 'session_id', 'access_token', 'auth']
const SENSITIVE_CONFIG_KEYS = ['chesspnt_auth', 'relay_sessions']

const CONFIG_KEY_LABELS = {
  position_caps: '持仓限额',
  rate_limits: '频次限制',
  symbols: '交易标的',
  spread_modes: '点差模式',
  equity_guard: '净资产守卫',
  llm_settings: 'LLM 设置',
  relay_stations: '中转站配置',
  relay_sessions: '中转站会话',
  chesspnt_auth: '认证凭据',
  no_profit_alert: '无盈利告警',
  time_windows: '时间窗口',
}

function toggleConfigKey(key) {
  expandedConfigKeys.value[key] = !expandedConfigKeys.value[key]
}

function configKeyLabel(key) {
  return CONFIG_KEY_LABELS[key] || key
}

function countFields(val) {
  if (Array.isArray(val)) return val.length + ' 项'
  if (typeof val === 'object' && val !== null) return Object.keys(val).length + ' 项'
  return '值'
}

function isSensitiveKey(key) {
  return SENSITIVE_CONFIG_KEYS.includes(key)
}

function isScalar(v) {
  return v === null || v === undefined || typeof v !== 'object'
}

function maskSensitive(configKey, fieldKey, val) {
  if (val === null || val === undefined) return 'null'
  const fk = String(fieldKey).toLowerCase()
  const isSensField = SENSITIVE_FIELDS.some(s => fk.includes(s))
  const isSensConfig = SENSITIVE_CONFIG_KEYS.includes(configKey)
  if ((isSensField || isSensConfig) && typeof val === 'string' && val.length > 12) {
    return val.slice(0, 6) + '••••••' + val.slice(-4)
  }
  return String(val)
}

function summarizeObj(obj) {
  if (obj === null || obj === undefined) return 'null'
  if (typeof obj !== 'object') return String(obj)
  if (Array.isArray(obj)) return '[' + obj.length + ' 项]'
  const keys = Object.keys(obj)
  if (keys.length <= 3) return '{' + keys.map(k => k + ': ' + (isScalar(obj[k]) ? obj[k] : '…')).join(', ') + '}'
  return '{' + keys.slice(0, 2).map(k => k + ': ' + (isScalar(obj[k]) ? obj[k] : '…')).join(', ') + ', … +' + (keys.length - 2) + '}'
}

function formatConfigVal(v) {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'number') return String(v)
  if (Array.isArray(v)) return '[' + v.length + ' 项]'
  if (typeof v === 'object') return '{' + Object.keys(v).length + ' 项}'
  return String(v)
}

function fmtAuditTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch { return t }
}

async function loadConfigAudit() {
  configLoading.value = true
  try {
    const r = await api.get('/api/v1/agent/config-audit')
    globalConfig.value = r.data?.global || []
    targetConfigs.value = r.data?.targets || []
  } catch {
    try {
      const r = await api.get('/api/v1/agent/config')
      const raw = r.data || {}
      globalConfig.value = Object.entries(raw).map(([key, value]) => ({
        key, value, source_proposal_id: null, updated_at: null, updated_by: null,
      }))
      targetConfigs.value = []
    } catch {}
  }
  finally { configLoading.value = false }
}

let timer
onMounted(() => {
  loadLlmHealth(); loadRelayStations(); loadStats(); loadConfigAudit()
  timer = setInterval(() => { loadLlmHealth(); loadRelayStations(); loadStats() }, 15000)
})
onUnmounted(() => clearInterval(timer))
</script>
