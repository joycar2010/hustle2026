<template>
  <div class="space-y-4">
    <!-- Target picker -->
    <div class="bg-dark-100 rounded-xl p-3 border border-border-primary flex items-center gap-3 text-sm">
      <span class="text-text-tertiary text-xs">作用域视图:</span>
      <button @click="selectedTarget = null"
        class="px-3 py-1 rounded text-xs"
        :class="selectedTarget === null ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary hover:bg-dark-300'">全部聚合</button>
      <button v-for="t in targets" :key="t.id" @click="selectedTarget = t.id"
        class="px-3 py-1 rounded text-xs"
        :class="selectedTarget === t.id ? 'bg-primary text-dark-300 font-semibold' : 'bg-dark-200 text-text-secondary hover:bg-dark-300'">
        <span class="font-semibold">{{ t.username }}</span> / <span class="font-mono">{{ t.pair_code }}</span>
      </button>
      <span v-if="targets.length === 0" class="text-text-tertiary text-xs">尚无目标 — 前往 /settings 添加</span>
      <span class="ml-auto text-[10px] text-text-tertiary">切换视图不影响后台运行，仅过滤显示</span>
    </div>

    <!-- KPI strip -->
    <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary">运行模式</div>
        <div class="font-bold text-xl mt-1" :class="modeColor">{{ modeLabel }}</div>
        <div class="text-[10px] text-text-tertiary mt-1">kill: {{ status?.kill_switch ? '已开启' : '关闭' }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary">总权益</div>
        <div class="font-mono font-bold text-xl mt-1">{{ fmt(status?.total_equity) }}</div>
        <div class="text-[10px] text-text-tertiary mt-1">A: {{ fmt(status?.a_equity) }} · B: {{ fmt(status?.b_equity) }}</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary">总持仓比</div>
        <div class="font-mono font-bold text-xl mt-1" :class="ratioColor(status?.position_ratio, 0.5)">
          {{ pct(status?.position_ratio) }}
        </div>
        <div class="text-[10px] text-text-tertiary mt-1">上限 50%</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary">日内累计</div>
        <div class="font-mono font-bold text-xl mt-1" :class="ratioColor(status?.daily_volume_ratio, 5)">
          {{ pct(status?.daily_volume_ratio) }}
        </div>
        <div class="text-[10px] text-text-tertiary mt-1">上限 500%</div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <div class="text-xs text-text-tertiary">半小时均值点差</div>
        <div class="font-mono font-bold text-xl mt-1" :class="spreadColor(status?.spread_30m_avg)">
          {{ status?.spread_30m_avg?.toFixed(2) ?? '--' }}
        </div>
        <div class="text-[10px] text-text-tertiary mt-1">{{ spreadModeLabel }}</div>
      </div>
    </div>

    <!-- Mid: leg balance + rate buckets -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary lg:col-span-2">
        <div class="flex justify-between items-center mb-3">
          <h3 class="font-semibold">双腿配平 <span v-if="balance?.target_label" class="text-[10px] text-text-tertiary font-normal">· {{ balance.target_label }}</span></h3>
          <span class="text-[10px] text-text-tertiary">5s 刷新</span>
        </div>
        <div v-if="!balance" class="text-text-tertiary text-sm py-8 text-center">加载中…</div>
        <div v-else class="space-y-2 text-sm">
          <div class="flex justify-between">
            <span class="text-text-tertiary">A 腿 <span class="font-mono text-[10px] opacity-70">{{ balance?.a_symbol || "XAUUSDT" }}</span></span>
            <span class="font-mono">{{ balance.a_size }} 张</span>
          </div>
          <div class="flex justify-between">
            <span class="text-text-tertiary">B 腿 <span class="font-mono text-[10px] opacity-70">{{ balance?.b_symbol || "XAUUSD+" }}</span></span>
            <span class="font-mono">{{ balance.b_size }} 手 × {{ balance.conversion_factor }}</span>
          </div>
          <div class="flex justify-between border-t border-border-primary pt-2">
            <span class="text-text-tertiary">偏差 (oz)</span>
            <span class="font-mono font-bold" :class="Math.abs(balance.delta) > 1 ? 'text-danger' : 'text-success'">
              {{ balance.delta?.toFixed(2) }}
            </span>
          </div>
          <div v-if="Math.abs(balance.delta) > 1" class="text-xs text-danger mt-2">
            ⚠ 单腿状态 — Codex 下次决策只允许 rebalance 補腿
          </div>
        </div>
      </div>
      <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
        <h3 class="font-semibold mb-3">频次水位</h3>
        <div v-if="!rate" class="text-text-tertiary text-sm py-8 text-center">加载中…</div>
        <div v-else class="space-y-2">
          <div v-for="b in rate.buckets" :key="b.window" class="text-xs">
            <div class="flex justify-between mb-0.5">
              <span class="text-text-tertiary">{{ b.window }}</span>
              <span class="font-mono">{{ b.used }} / {{ b.effective_cap }}</span>
            </div>
            <div class="h-1.5 bg-dark-200 rounded overflow-hidden">
              <div class="h-full" :class="bucketColor(b)" :style="{width: Math.min(100, b.used / b.effective_cap * 100) + '%'}"></div>
            </div>
          </div>
          <div class="text-[10px] text-text-tertiary mt-2">已含 {{ pct(rate.safety_margin) }} 安全水位</div>
        </div>
      </div>
    </div>

    <!-- Decision stream -->
    <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
      <div class="flex justify-between items-center mb-3">
        <h3 class="font-semibold">最近决策（实时）</h3>
        <router-link to="/decisions" class="text-xs text-primary hover:underline">查看全部 →</router-link>
      </div>
      <div v-if="decisions.length === 0" class="text-text-tertiary text-sm py-6 text-center">暂无决策</div>
      <table v-else class="w-full text-xs">
        <thead class="text-text-tertiary">
          <tr class="text-left">
            <th class="py-1">时间</th>
            <th>触发</th>
            <th>动作</th>
            <th>数量</th>
            <th>判决</th>
            <th>tokens / ms</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in decisions.slice(0, 10)" :key="d.id" class="border-t border-border-primary hover:bg-dark-200">
            <td class="py-1.5 font-mono text-text-tertiary">{{ fmtTime(d.created_at) }}</td>
            <td class="text-text-secondary">{{ d.trigger }}</td>
            <td><span class="font-mono" :class="actionColor(d.action)">{{ d.action }}</span></td>
            <td class="font-mono">{{ d.qty }}</td>
            <td>
              <span class="px-1.5 py-0.5 rounded text-[10px]" :class="verdictBadge(d.verdict)">{{ d.verdict }}</span>
            </td>
            <td class="font-mono text-text-tertiary">{{ (d.tokens_in||0)+(d.tokens_out||0) }} / {{ d.latency_ms }}</td>
            <td class="text-text-secondary truncate max-w-[280px]" :title="d.reject_reason || d.reason">
              {{ d.reject_reason || d.reason }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'

const status = ref(null)
const balance = ref(null)
const rate = ref(null)
const decisions = ref([])
const targets = ref([])
const selectedTarget = ref(null)

const modeLabel = computed(() => ({ shadow: 'Shadow', semi: '半自动', auto: '全自动', off: '已停机' })[status.value?.mode] || '--')
const modeColor = computed(() => ({ shadow: 'text-yellow-400', semi: 'text-blue-400', auto: 'text-success', off: 'text-text-tertiary' })[status.value?.mode] || 'text-text-primary')
const spreadModeLabel = computed(() => {
  const s = Math.abs(status.value?.spread_30m_avg || 0)
  if (s > 5) return '极端模式 (>5)'
  if (s > 1.5) return '中等模式 (1.5-5)'
  return '普通模式 (±1.5)'
})

function fmt(n) { return n != null ? Number(n).toFixed(2) : '--' }
function pct(n) { return n != null ? (Number(n) * 100).toFixed(1) + '%' : '--' }
function fmtTime(t) { return dayjs(t).format('HH:mm:ss') }
function ratioColor(r, cap) {
  if (r == null) return 'text-text-primary'
  const ratio = r / cap
  if (ratio > 0.8) return 'text-danger'
  if (ratio > 0.5) return 'text-warning'
  return 'text-text-primary'
}
function spreadColor(s) {
  if (s == null) return 'text-text-primary'
  const a = Math.abs(s)
  if (a > 5) return 'text-danger'
  if (a > 1.5) return 'text-warning'
  return 'text-text-primary'
}
function actionColor(a) {
  if (a === 'noop') return 'text-text-tertiary'
  if (a?.startsWith('open')) return 'text-primary'
  if (a?.startsWith('close')) return 'text-blue-400'
  if (a === 'rebalance') return 'text-yellow-400'
  return 'text-text-primary'
}
function verdictBadge(v) {
  return ({
    executed: 'bg-success/20 text-success',
    shadow: 'bg-yellow-900/30 text-yellow-400',
    pending: 'bg-blue-900/30 text-blue-400',
    rejected: 'bg-danger/20 text-danger',
    skipped: 'bg-dark-200 text-text-tertiary',
  })[v] || 'bg-dark-200 text-text-tertiary'
}
function bucketColor(b) {
  const r = b.used / b.effective_cap
  if (r > 0.8) return 'bg-danger'
  if (r > 0.5) return 'bg-warning'
  return 'bg-success'
}

async function refresh() {
  try {
    const tid = selectedTarget.value
    const qs = tid != null ? '?target_id=' + tid : ''
    const [s, b, r, d, ts] = await Promise.all([
      api.get('/api/v1/agent/status' + qs).catch(() => null),
      api.get('/api/v1/agent/leg-balance' + qs).catch(() => null),
      api.get('/api/v1/agent/rate-buckets' + qs).catch(() => null),
      api.get('/api/v1/agent/decisions?limit=10' + (tid != null ? '&target_id=' + tid : '')).catch(() => null),
      targets.value.length === 0 ? api.get('/api/v1/agent/scope/targets').catch(() => null) : Promise.resolve(null),
    ])
    if (ts) targets.value = ts.data?.items?.filter(t => t.enabled) || []
    if (s) status.value = s.data
    if (b) balance.value = b.data
    if (r) rate.value = r.data
    if (d) decisions.value = d.data?.items || []
  } catch (e) { console.error(e) }
}

let timer
import { watch as _watch } from 'vue'
_watch(selectedTarget, () => refresh())
onMounted(() => { refresh(); timer = setInterval(refresh, 5000) })
onUnmounted(() => clearInterval(timer))
</script>
