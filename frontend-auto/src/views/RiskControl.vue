<template>
  <div class="space-y-4 max-w-6xl">
    <!-- Risk Overview Panel -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold flex items-center gap-2">
          风险概览
          <span class="px-2 py-0.5 rounded text-[10px] font-mono" :class="overallRiskClass">{{ overallRiskLabel }}</span>
        </h3>
        <span class="text-[10px] text-text-tertiary">自动刷新 15s</span>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        <div class="bg-dark-200 rounded-lg p-3 border-l-4" :class="status?.kill_switch ? 'border-danger' : 'border-success'">
          <div class="text-[10px] text-text-tertiary">紧急停机</div>
          <div class="font-bold text-sm" :class="status?.kill_switch ? 'text-danger animate-pulse' : 'text-success'">{{ status?.kill_switch ? '已停机' : '正常' }}</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-3 border-l-4" :class="riskLlm.borderClass">
          <div class="text-[10px] text-text-tertiary">LLM 熔断</div>
          <div class="font-bold text-sm" :class="riskLlm.textClass">{{ riskLlm.label }}</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-3 border-l-4" :class="riskEquity.borderClass">
          <div class="text-[10px] text-text-tertiary">净资产</div>
          <div class="font-bold text-sm" :class="riskEquity.textClass">{{ riskEquity.label }}</div>
        </div>
        <div class="bg-dark-200 rounded-lg p-3 border-l-4" :class="riskRate.borderClass">
          <div class="text-[10px] text-text-tertiary">频次水位</div>
          <div class="font-bold text-sm" :class="riskRate.textClass">{{ riskRate.label }}</div>
        </div>
      </div>
      <div v-if="riskAlerts.length" class="space-y-1">
        <div v-for="(a, i) in riskAlerts" :key="i" class="flex items-center gap-2 px-3 py-1.5 rounded text-xs"
          :class="a.level === 'critical' ? 'bg-danger/10 text-danger' : a.level === 'warning' ? 'bg-warning/10 text-warning' : 'bg-blue-900/20 text-blue-400'">
          <span class="font-bold text-[10px] uppercase">{{ a.level }}</span>
          <span>{{ a.message }}</span>
          <span class="ml-auto text-[10px] text-text-tertiary font-mono">{{ a.source }}</span>
        </div>
      </div>
      <div v-else class="text-[10px] text-success text-center py-1">✓ 无活跃告警</div>
    </div>

    <!-- Per-Target Health Dashboard -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <h3 class="font-semibold mb-3">目标健康一览</h3>
      <div v-if="!targetStore.comparison.length" class="text-text-tertiary text-sm text-center py-4">加载中…</div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <div v-for="t in targetStore.comparison" :key="t.target_id"
          class="bg-dark-200 rounded-lg p-3 border-l-4"
          :class="healthBorder(t.alert_level)">
          <div class="flex items-center justify-between mb-2">
            <div>
              <span class="font-semibold text-sm">{{ t.username }}</span>
              <span class="font-mono text-primary text-xs ml-1">{{ t.pair_code }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="font-mono font-bold text-lg" :class="healthColor(t.health_score)">{{ t.health_score }}</span>
              <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold" :class="alertBadge(t.alert_level)">{{ alertLbl(t.alert_level) }}</span>
            </div>
          </div>
          <div class="h-2 bg-dark-300 rounded-full overflow-hidden mb-2">
            <div class="h-full rounded-full transition-all" :class="healthBarColor(t.health_score)" :style="{width: t.health_score + '%'}"></div>
          </div>
          <div class="grid grid-cols-3 gap-2 text-[10px]">
            <div>
              <span class="text-text-tertiary">偏差</span>
              <div class="font-mono font-bold" :class="t.match_deviation_pct > 10 ? 'text-danger' : t.match_deviation_pct > 5 ? 'text-warning' : 'text-text-primary'">{{ t.match_deviation_pct }}%</div>
            </div>
            <div>
              <span class="text-text-tertiary">频率/h</span>
              <div class="font-mono font-bold">{{ t.freq_per_hour }}</div>
            </div>
            <div>
              <span class="text-text-tertiary">拦截率</span>
              <div class="font-mono font-bold" :class="t.total_24h && t.rejected_24h / t.total_24h > 0.7 ? 'text-danger' : ''">
                {{ t.total_24h ? ((t.rejected_24h / t.total_24h) * 100).toFixed(0) + '%' : '--' }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Global Control Bar -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <div class="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h3 class="font-semibold mb-2">运行模式</h3>
          <div class="flex gap-2">
            <button v-for="m in modes" :key="m.key" @click="setMode(m.key)"
              :disabled="modeCooldown > 0"
              class="px-4 py-3 rounded-lg border-2 text-left transition min-w-[120px]"
              :class="status?.mode === m.key ? 'border-primary bg-primary/10' : 'border-border-primary hover:bg-dark-200 disabled:opacity-40'">
              <div class="font-bold text-sm">{{ m.label }}</div>
              <div class="text-[10px] text-text-tertiary mt-0.5">{{ m.desc }}</div>
            </button>
          </div>
          <div v-if="modeCooldown > 0" class="text-[10px] text-warning mt-1">冷却中 {{ modeCooldown }}s</div>
        </div>
        <div class="text-right">
          <h3 class="font-semibold mb-2">紧急停机</h3>
          <button @click="toggleKill" :disabled="killCooldown > 0"
            class="px-8 py-3 rounded-lg font-bold text-base transition disabled:opacity-40"
            :class="status?.kill_switch ? 'bg-success text-dark-300' : 'bg-danger text-white'">
            {{ status?.kill_switch ? '解除停机' : '立即停机' }}
          </button>
          <div v-if="killCooldown > 0" class="text-[10px] text-warning mt-1">冷却中 {{ killCooldown }}s</div>
          <div v-if="status?.kill_switch" class="text-danger text-xs mt-1 animate-pulse">⚠ 已停机：所有决策被拒</div>
        </div>
      </div>
    </div>

    <!-- Agent Scope Matrix -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold">智能体作用域矩阵</h3>
        <span class="text-xs text-text-tertiary">每行 = 独立执行目标</span>
      </div>
      <div class="bg-dark-200 rounded p-3 mb-3 grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div>
          <div class="text-xs text-text-tertiary mb-1">用户</div>
          <select v-model="newTarget.user_id" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none">
            <option :value="null">选择用户…</option>
            <option v-for="u in scopeOpts.users || []" :key="u.user_id" :value="u.user_id">{{ u.username }} · {{ u.role }}</option>
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
          <div class="text-xs text-text-tertiary mb-1">优先级</div>
          <input v-model.number="newTarget.priority" type="number" step="1" min="0" class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
        </div>
        <div class="flex items-end">
          <button @click="addTarget" :disabled="!newTarget.user_id || !newTarget.pair_code"
            class="w-full px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover disabled:opacity-40">添加目标</button>
        </div>
      </div>

      <div v-if="!targets.length" class="text-text-tertiary text-sm py-4 text-center">尚无目标</div>
      <table v-else class="w-full text-xs">
        <thead class="text-text-tertiary">
          <tr class="text-left border-b border-border-primary">
            <th class="py-2">ID</th><th>用户</th><th>产品对</th><th>优先级</th><th>启用</th><th>健康</th><th>24h决策</th><th>最后决策</th><th>操作</th>
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
            <td><span class="font-mono font-bold" :class="healthColor(compMap[t.id]?.health_score)">{{ compMap[t.id]?.health_score ?? '--' }}</span></td>
            <td class="font-mono text-text-tertiary">{{ targetMeta[t.id]?.count_24h ?? '--' }}</td>
            <td class="font-mono text-text-tertiary text-[10px]">{{ targetMeta[t.id]?.last_decision ? dayjs(targetMeta[t.id].last_decision).fromNow() : '--' }}</td>
            <td>
              <button @click="editCaps(t)" class="px-2 py-0.5 bg-primary/20 text-primary rounded text-[10px] hover:bg-primary/30 mr-1">风控</button>
              <button @click="removeTarget(t)" class="px-2 py-0.5 bg-danger/20 text-danger rounded text-[10px] hover:bg-danger/30">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Enhanced editingCaps panel -->
      <div v-if="editingCaps" class="mt-3 bg-dark-200 rounded-lg p-4 border border-border-primary">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-sm font-semibold">风控参数 · #{{ editingCaps.target_id }} <span class="text-primary font-mono">{{ editingCaps.pair_code }}</span></h4>
          <button @click="editingCaps = null" class="text-xs text-text-tertiary hover:text-text-primary">✕</button>
        </div>

        <!-- Section 1: Position Caps -->
        <div class="mb-4">
          <div class="text-[10px] text-text-tertiary uppercase tracking-wider mb-2 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-primary"></span>
            仓位限制
          </div>
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div v-for="cap in capFields" :key="cap.key">
              <div class="text-xs text-text-tertiary mb-1">{{ cap.label }} <span class="ml-1">(全局: {{ ((editingCaps.global_caps?.[cap.key] || cap.default) * 100).toFixed(0) }}%)</span></div>
              <input v-model.number="editingCaps[cap.key]" :type="'number'" :step="cap.step" :min="cap.min" :max="cap.max"
                class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
              <div class="h-1.5 bg-dark-300 rounded-full mt-1 overflow-hidden">
                <div class="h-full bg-primary/60 rounded-full" :style="{ width: Math.min(100, (editingCaps[cap.key] / (editingCaps.global_caps?.[cap.key] || cap.default)) * 100) + '%' }"></div>
              </div>
              <div class="text-[9px] text-text-tertiary mt-0.5">覆盖比: {{ ((editingCaps[cap.key] / (editingCaps.global_caps?.[cap.key] || cap.default)) * 100).toFixed(0) }}%</div>
            </div>
          </div>
        </div>

        <!-- Section 2: Rate Limits -->
        <div class="mb-4 pt-3 border-t border-border-primary">
          <div class="text-[10px] text-text-tertiary uppercase tracking-wider mb-2 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-warning"></span>
            频次限制
          </div>
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div v-for="rl in rateLimitFields" :key="rl.key">
              <div class="text-xs text-text-tertiary mb-1">{{ rl.label }} <span class="ml-1">(全局: {{ editingCaps.global_caps?.[rl.key] ?? rl.default }}{{ rl.unit }})</span></div>
              <input v-model.number="editingCaps[rl.key]" :type="'number'" :step="rl.step" :min="rl.min" :max="rl.max"
                class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
              <div class="h-1.5 bg-dark-300 rounded-full mt-1 overflow-hidden">
                <div class="h-full bg-warning/60 rounded-full" :style="{ width: Math.min(100, (editingCaps[rl.key] / (editingCaps.global_caps?.[rl.key] || rl.default)) * 100) + '%' }"></div>
              </div>
              <div class="text-[9px] text-text-tertiary mt-0.5">覆盖比: {{ ((editingCaps[rl.key] / (editingCaps.global_caps?.[rl.key] || rl.default)) * 100).toFixed(0) }}%</div>
            </div>
          </div>
        </div>

        <!-- Section 3: Equity Guard -->
        <div class="mb-4 pt-3 border-t border-border-primary">
          <div class="text-[10px] text-text-tertiary uppercase tracking-wider mb-2 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-danger"></span>
            净资产守卫
          </div>
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div v-for="eg in equityGuardFields" :key="eg.key">
              <div class="text-xs text-text-tertiary mb-1">{{ eg.label }} <span class="ml-1">(全局: {{ ((editingCaps.global_caps?.[eg.key] || eg.default) * 100).toFixed(0) }}%)</span></div>
              <input v-model.number="editingCaps[eg.key]" :type="'number'" :step="eg.step" :min="eg.min" :max="eg.max"
                class="w-full bg-dark-300 border border-border-primary rounded px-3 py-2 text-sm font-mono focus:border-primary outline-none">
              <div class="h-1.5 bg-dark-300 rounded-full mt-1 overflow-hidden">
                <div class="h-full rounded-full" :class="eg.barClass" :style="{ width: Math.min(100, (editingCaps[eg.key] / (editingCaps.global_caps?.[eg.key] || eg.default)) * 100) + '%' }"></div>
              </div>
              <div class="text-[9px] text-text-tertiary mt-0.5">
                覆盖比: {{ ((editingCaps[eg.key] / (editingCaps.global_caps?.[eg.key] || eg.default)) * 100).toFixed(0) }}%
                <span v-if="eg.hint" class="ml-1 text-text-tertiary">· {{ eg.hint }}</span>
              </div>
            </div>
          </div>
        </div>

        <button @click="saveTargetCaps" class="mt-3 px-4 py-2 bg-primary text-dark-300 font-semibold rounded hover:bg-primary-hover text-sm">保存风控参数</button>
        <span class="text-[10px] text-text-tertiary ml-2">5 秒内热加载生效</span>
      </div>
    </div>

    <!-- Intervention Records -->
    <div class="bg-dark-100 rounded-xl p-5 border border-border-primary">
      <h3 class="font-semibold mb-3">净资产干预记录</h3>
      <div v-if="!interventions.length" class="text-text-tertiary text-sm py-4 text-center">无记录</div>
      <table v-else class="w-full text-xs">
        <thead class="text-text-tertiary">
          <tr class="text-left"><th class="py-1">触发时间</th><th>账户</th><th>状态</th><th>占比</th><th>强减%</th><th>解除</th><th>操作</th></tr>
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
              <button v-if="!i.resolved_at" @click="ackIntervention(i.account_id)" class="px-2 py-0.5 bg-blue-600 text-white rounded text-[10px]">确认</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { useWsStream } from '@/stores/wsStream.js'
import { useTargetStore } from '@/stores/targetStore.js'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const wsStore = useWsStream()
wsStore.subscribe('agent.status')
const targetStore = useTargetStore()
const status = ref(null)
watch(() => wsStore.channels['agent.status'], (v) => { if (v) status.value = { ...(status.value || {}), ...v } }, { deep: true })

const interventions = ref([])
const scopeOpts = ref({ users: [], pair_codes: [] })
const targets = ref([])
const targetMeta = ref({})
const newTarget = ref({ user_id: null, pair_code: null, priority: 0 })
const editingCaps = ref(null)
const modeCooldown = ref(0)
const killCooldown = ref(0)
let modeTimer = null, killTimer = null

const compMap = computed(() => {
  const m = {}
  for (const t of targetStore.comparison) m[t.target_id] = t
  return m
})

const modes = [
  { key: 'shadow', label: 'Shadow', desc: '只观察记录，不下单。' },
  { key: 'semi', label: '半自动', desc: '入 pending 需审批后执行。' },
  { key: 'auto', label: '全自动', desc: 'Guard 通过即执行。' },
  { key: 'off', label: '已停机', desc: '关闭 LLM 决策。' },
]

const capFields = [
  { key: 'single_trade_pct', label: '单笔上限 %', step: 0.01, min: 0.01, max: 1, default: 0.1 },
  { key: 'total_position_pct', label: '总持仓上限 %', step: 0.05, min: 0.05, max: 2, default: 0.5 },
  { key: 'daily_volume_pct', label: '日内累计上限 %', step: 0.5, min: 0.5, max: 20, default: 5.0 },
]

const rateLimitFields = [
  { key: 'max_decisions_per_min', label: '每分钟最大决策数', step: 1, min: 1, max: 60, default: 10, unit: '' },
  { key: 'max_trades_per_hour', label: '每小时最大交易数', step: 1, min: 1, max: 200, default: 30, unit: '' },
  { key: 'cooldown_after_loss_s', label: '亏损后冷却 (秒)', step: 5, min: 0, max: 3600, default: 120, unit: 's' },
]

const equityGuardFields = [
  { key: 'warn_ratio', label: '警告阈值', step: 0.01, min: 0.5, max: 1, default: 0.90, barClass: 'bg-warning/60', hint: '低于此值触发告警' },
  { key: 'critical_ratio', label: '危险阈值', step: 0.01, min: 0.3, max: 1, default: 0.80, barClass: 'bg-orange-500/60', hint: '低于此值升级干预' },
  { key: 'force_reduce_ratio', label: '强减阈值', step: 0.01, min: 0.1, max: 1, default: 0.70, barClass: 'bg-danger/60', hint: '低于此值自动强减' },
]

function fmtTime(t) { return dayjs(t).format('MM-DD HH:mm:ss') }
function stateBadge(s) {
  return ({ NORMAL: 'bg-success/20 text-success', WARNING: 'bg-warning/20 text-warning', ESCALATING: 'bg-orange-900/30 text-orange-300', FORCED_REDUCE: 'bg-danger/20 text-danger', RESOLVED: 'bg-dark-200 text-text-tertiary' })[s] || 'bg-dark-200 text-text-tertiary'
}
function healthColor(score) {
  if (score == null) return 'text-text-tertiary'
  if (score >= 80) return 'text-success'
  if (score >= 50) return 'text-warning'
  return 'text-danger'
}
function healthBarColor(score) {
  if (score >= 80) return 'bg-success'
  if (score >= 50) return 'bg-warning'
  return 'bg-danger'
}
function healthBorder(level) {
  return ({ critical: 'border-danger', warning: 'border-warning', normal: 'border-success' })[level] || 'border-border-primary'
}
function alertBadge(level) {
  return ({ critical: 'bg-danger/20 text-danger', warning: 'bg-warning/20 text-warning', normal: 'bg-success/20 text-success' })[level] || ''
}
function alertLbl(level) {
  return ({ critical: '危险', warning: '警告', normal: '正常' })[level] || level
}

function startCooldown(type) {
  const ref_ = type === 'mode' ? modeCooldown : killCooldown
  ref_.value = 60
  const t = setInterval(() => { ref_.value--; if (ref_.value <= 0) clearInterval(t) }, 1000)
  if (type === 'mode') { clearInterval(modeTimer); modeTimer = t } else { clearInterval(killTimer); killTimer = t }
}

async function setMode(m) {
  if (modeCooldown.value > 0) return
  const activeCount = targets.value.filter(t => t.enabled).length
  if (!confirm(`切换为 [${m}]？\n当前 ${activeCount} 个目标运行中`)) return
  try { await api.post('/api/v1/agent/mode', { mode: m }); await refresh(); startCooldown('mode') }
  catch (e) { alert('切换失败: ' + (e.response?.data?.detail || e.message)) }
}
async function toggleKill() {
  if (killCooldown.value > 0) return
  const next = !status.value?.kill_switch
  if (!confirm(next ? '⚠ 立即停机所有决策？' : '解除停机？')) return
  try { await api.post('/api/v1/agent/kill', { on: next }); await refresh(); startCooldown('kill') }
  catch (e) { alert('操作失败: ' + (e.response?.data?.detail || e.message)) }
}

async function loadTargets() {
  try {
    const r = await api.get('/api/v1/agent/scope/targets')
    targets.value = r.data?.items || []
    for (const t of targets.value) {
      try {
        const sr = await api.get('/api/v1/agent/decisions/stats?window=24h&target_id=' + t.id)
        targetMeta.value[t.id] = { count_24h: sr.data?.total || 0, last_decision: null }
      } catch { targetMeta.value[t.id] = { count_24h: 0, last_decision: null } }
    }
  } catch {}
}
async function addTarget() {
  if (!newTarget.value.user_id || !newTarget.value.pair_code) return
  try {
    await api.post('/api/v1/agent/scope/targets', { user_id: newTarget.value.user_id, pair_code: newTarget.value.pair_code, priority: newTarget.value.priority || 0 })
    newTarget.value = { user_id: null, pair_code: null, priority: 0 }
    await loadTargets()
  } catch (e) { alert('添加失败: ' + (e.response?.data?.detail || e.message)) }
}
async function removeTarget(t) {
  if (!confirm('删除目标 #' + t.id + '？')) return
  try { await api.delete('/api/v1/agent/scope/targets/' + t.id); await loadTargets() }
  catch (e) { alert('删除失败: ' + (e.response?.data?.detail || e.message)) }
}
async function toggleTarget(t, enabled) {
  try { await api.post('/api/v1/agent/scope/targets/' + t.id + '/toggle', { enabled }); await loadTargets() }
  catch (e) { alert('切换失败'); await loadTargets() }
}
async function editCaps(t) {
  try {
    const r = await api.get('/api/v1/agent/scope/targets/' + t.id + '/caps')
    editingCaps.value = {
      target_id: t.id,
      pair_code: t.pair_code,
      single_trade_pct: r.data.caps?.single_trade_pct ?? 0.10,
      total_position_pct: r.data.caps?.total_position_pct ?? 0.50,
      daily_volume_pct: r.data.caps?.daily_volume_pct ?? 5.0,
      max_decisions_per_min: r.data.caps?.max_decisions_per_min ?? 10,
      max_trades_per_hour: r.data.caps?.max_trades_per_hour ?? 30,
      cooldown_after_loss_s: r.data.caps?.cooldown_after_loss_s ?? 120,
      warn_ratio: r.data.caps?.warn_ratio ?? 0.90,
      critical_ratio: r.data.caps?.critical_ratio ?? 0.80,
      force_reduce_ratio: r.data.caps?.force_reduce_ratio ?? 0.70,
      global_caps: r.data.global_caps || {},
    }
  } catch (e) { alert('加载失败: ' + (e.response?.data?.detail || e.message)) }
}
async function saveTargetCaps() {
  if (!editingCaps.value) return
  try {
    await api.post('/api/v1/agent/scope/targets/' + editingCaps.value.target_id + '/caps', {
      single_trade_pct: editingCaps.value.single_trade_pct,
      total_position_pct: editingCaps.value.total_position_pct,
      daily_volume_pct: editingCaps.value.daily_volume_pct,
      max_decisions_per_min: editingCaps.value.max_decisions_per_min,
      max_trades_per_hour: editingCaps.value.max_trades_per_hour,
      cooldown_after_loss_s: editingCaps.value.cooldown_after_loss_s,
      warn_ratio: editingCaps.value.warn_ratio,
      critical_ratio: editingCaps.value.critical_ratio,
      force_reduce_ratio: editingCaps.value.force_reduce_ratio,
    })
    alert('已保存，5秒内热加载生效')
    editingCaps.value = null
  } catch (e) { alert('保存失败: ' + (e.response?.data?.detail || e.message)) }
}
async function ackIntervention(aid) {
  if (!confirm('确认取消自动强减？') ) return
  try { await api.post('/api/v1/agent/equity-ack', { account_id: aid }); await refresh() }
  catch (e) { alert('确认失败: ' + (e.response?.data?.detail || e.message)) }
}

async function refresh() {
  try {
    const [s, i, so] = await Promise.all([
      api.get('/api/v1/agent/status').catch(() => null),
      api.get('/api/v1/agent/equity-interventions').catch(() => null),
      api.get('/api/v1/agent/scope-options').catch(() => null),
    ])
    if (s) status.value = s.data
    if (i) interventions.value = i.data?.items || []
    if (so) scopeOpts.value = so.data
  } catch {}
}

const riskData = ref({})
async function loadRiskData() {
  try {
    const [llm, rate] = await Promise.all([
      api.get('/api/v1/agent/llm-health').catch(() => null),
      api.get('/api/v1/agent/rate-buckets').catch(() => null),
    ])
    riskData.value = { llm: llm?.data, rate: rate?.data }
  } catch {}
}

const riskLlm = computed(() => {
  const s = riskData.value?.llm
  if (!s) return { label: '--', borderClass: 'border-dark-300', textClass: 'text-text-tertiary' }
  const open = s.circuit_open === true || s.circuit_state === 'open'
  if (open) return { label: '已熔断', borderClass: 'border-danger', textClass: 'text-danger animate-pulse' }
  if ((s.fail_rate || 0) > 0.1) return { label: '异常', borderClass: 'border-warning', textClass: 'text-warning' }
  return { label: '正常', borderClass: 'border-success', textClass: 'text-success' }
})
const riskEquity = computed(() => {
  const active = interventions.value.filter(i => !i.resolved_at)
  if (active.some(i => i.state === 'FORCED_REDUCE')) return { label: '强减中', borderClass: 'border-danger', textClass: 'text-danger animate-pulse' }
  if (active.some(i => i.state === 'ESCALATING')) return { label: '升级中', borderClass: 'border-warning', textClass: 'text-warning' }
  if (active.length) return { label: '告警', borderClass: 'border-warning', textClass: 'text-warning' }
  return { label: '正常', borderClass: 'border-success', textClass: 'text-success' }
})
const riskRate = computed(() => {
  const r = riskData.value?.rate
  if (!r?.buckets) return { label: '--', borderClass: 'border-dark-300', textClass: 'text-text-tertiary' }
  const maxRatio = Math.max(...r.buckets.map(b => b.used / b.effective_cap))
  if (maxRatio > 0.9) return { label: '接近上限', borderClass: 'border-danger', textClass: 'text-danger' }
  if (maxRatio > 0.6) return { label: '中等', borderClass: 'border-warning', textClass: 'text-warning' }
  return { label: '正常', borderClass: 'border-success', textClass: 'text-success' }
})
const overallRiskClass = computed(() => {
  if (status.value?.kill_switch) return 'bg-danger/20 text-danger'
  if (riskLlm.value.textClass.includes('danger') || riskEquity.value.textClass.includes('danger')) return 'bg-danger/20 text-danger'
  if (riskLlm.value.textClass.includes('warning') || riskEquity.value.textClass.includes('warning') || riskRate.value.textClass.includes('warning')) return 'bg-warning/20 text-warning'
  return 'bg-success/20 text-success'
})
const overallRiskLabel = computed(() => {
  if (status.value?.kill_switch) return 'CRITICAL'
  if (riskLlm.value.textClass.includes('danger') || riskEquity.value.textClass.includes('danger')) return 'HIGH'
  if (riskLlm.value.textClass.includes('warning') || riskEquity.value.textClass.includes('warning') || riskRate.value.textClass.includes('warning')) return 'MEDIUM'
  return 'LOW'
})
const riskAlerts = computed(() => {
  const list = []
  if (status.value?.kill_switch) list.push({ level: 'critical', message: '紧急停机已激活，所有决策被拒绝', source: 'kill_switch' })
  if (riskLlm.value.label === '已熔断') list.push({ level: 'critical', message: 'LLM 熔断器打开，无法生成决策', source: 'circuit_breaker' })
  if (riskEquity.value.label === '强减中') list.push({ level: 'critical', message: '净资产干预：强制减仓进行中', source: 'equity' })
  if (riskEquity.value.label === '升级中') list.push({ level: 'warning', message: '净资产干预正在升级', source: 'equity' })
  if (riskRate.value.label === '接近上限') list.push({ level: 'warning', message: '频次水位接近上限，即将触发限速', source: 'rate_limit' })
  if ((riskData.value?.llm?.fail_rate || 0) > 0.1 && riskLlm.value.label !== '已熔断') list.push({ level: 'warning', message: 'LLM 失败率 > 10%', source: 'llm' })
  const mode = status.value?.mode
  if (mode === 'off') list.push({ level: 'info', message: '运行模式已关闭', source: 'mode' })
  if (mode === 'shadow') list.push({ level: 'info', message: 'Shadow 模式：仅观察不执行', source: 'mode' })
  return list
})

let timer
onMounted(() => {
  refresh(); loadTargets(); loadRiskData(); targetStore.loadComparison()
  timer = setInterval(() => { refresh(); loadRiskData(); targetStore.loadComparison() }, 15000)
})
onUnmounted(() => { clearInterval(timer); clearInterval(modeTimer); clearInterval(killTimer) })
</script>
