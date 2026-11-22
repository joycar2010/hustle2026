<template>
  <div class="status-panel text-xs">
    <!-- 顶部健康总览灯阵 -->
    <div class="px-2 py-1.5 border-b border-[#2b3139] flex items-center gap-x-3 gap-y-1 flex-wrap">
      <span v-for="h in healthDots" :key="h.key" class="flex items-center gap-1" :title="h.title">
        <span :class="['w-1.5 h-1.5 rounded-full', h.cls]"></span>
        <span class="text-[10px] text-gray-400">{{ h.label }}</span>
      </span>
      <button @click="refreshAll" class="ml-auto text-[10px] text-gray-500 hover:text-[#f0b90b] transition-colors" title="立即刷新">↻ 刷新</button>
    </div>

    <!-- 固定高度内部滚动区 -->
    <div class="status-scroll scrollbar-hide">

      <!-- ───────── 自动策略进程 ───────── -->
      <div class="sec">
        <div class="sec-h">
          <span :class="['dot', anyStrategyRunning ? 'bg-[#0ecb81] pulse' : 'bg-gray-600']"></span>
          自动策略进程
          <span class="ml-auto text-[10px]" :class="anyStrategyRunning ? 'text-[#0ecb81]' : 'text-gray-500'">{{ runningCount }} 运行中</span>
        </div>

        <!-- 全局组件 -->
        <div class="grid grid-cols-2 gap-1 mb-1">
          <div class="comp">
            <span class="text-gray-400">策略管理器</span>
            <span class="flex items-center gap-1"><span :class="['dot-sm', sys.strategyManager ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>{{ sys.strategyManager ? '运行' : '停' }}</span>
          </div>
          <div class="comp">
            <span class="text-gray-400">持仓监控</span>
            <span class="flex items-center gap-1"><span :class="['dot-sm', posMonitor.active ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>{{ posMonitor.active ? '运行' : '停' }}</span>
          </div>
        </div>

        <!-- 4 进程泳道 -->
        <div v-for="slot in SLOTS" :key="slot.key" class="lane">
          <div class="flex items-center justify-between">
            <span class="flex items-center gap-1.5">
              <span :class="['dot', procDot(slot.key)]"></span>
              <span class="font-medium">{{ slot.label }}</span>
            </span>
            <span :class="['badge', procBadge(slot.key)]">{{ procText(slot.key) }}</span>
          </div>
          <!-- 阶梯堆叠条 -->
          <div v-if="proc[slot.key].running" class="mt-1">
            <div class="flex items-center gap-0.5">
              <div v-for="n in ladderCount" :key="n"
                :class="['ladder-seg', ladderSegCls(slot.key, n - 1)]"
                :title="'阶梯 ' + n"></div>
            </div>
            <!-- 触发进度条 -->
            <div class="flex items-center justify-between mt-1 text-[10px] text-gray-400">
              <span>触发 {{ proc[slot.key].trigger.current }}/{{ proc[slot.key].trigger.required || '-' }}</span>
              <span v-if="proc[slot.key].current_ladder != null">当前第 {{ proc[slot.key].current_ladder }} 阶</span>
            </div>
            <div v-if="proc[slot.key].trigger.required" class="track mt-0.5">
              <div class="fill bg-[#0ecb81]" :style="{ width: trigPct(slot.key) + '%' }"></div>
            </div>
          </div>
          <div v-else class="mt-0.5 text-[10px] text-gray-500">{{ procText(slot.key) === '失败' ? '上次执行失败' : '空闲 — 未自动执行' }}</div>
        </div>
      </div>

      <!-- ───────── 策略机制状态（图形化） ───────── -->
      <div class="sec">
        <div class="sec-h"><span class="dot bg-[#f0b90b]"></span>策略机制状态</div>

        <!-- 背离护栏：双阈值标尺 -->
        <div class="mech">
          <div class="mech-top">
            <span>背离护栏</span>
            <span :class="['badge', mech.divergence_guard?.tripped ? 'badge-red' : (mech.divergence_guard?.disabled ? 'badge-gray' : 'badge-green')]">
              {{ mech.divergence_guard?.disabled ? '已禁用' : (mech.divergence_guard?.tripped ? '软暂停' : '正常') }}
            </span>
          </div>
          <!-- 标尺：0 → trip，滑块=当前 basis_diff；recover/trip 双刻度 -->
          <div v-if="divReadable" class="gauge mt-1">
            <div class="gauge-track">
              <div class="gauge-zone-ok" :style="{ width: recoverPct + '%' }"></div>
              <div class="gauge-zone-warn" :style="{ left: recoverPct + '%', width: (tripPct - recoverPct) + '%' }"></div>
              <div class="gauge-zone-bad" :style="{ left: tripPct + '%', width: (100 - tripPct) + '%' }"></div>
              <div class="gauge-marker" :style="{ left: Math.min(100, Math.max(0, basisPct)) + '%' }"></div>
            </div>
            <div class="flex justify-between text-[9px] text-gray-500 mt-0.5">
              <span>基差 {{ fmt(mech.divergence_guard?.basis_diff) }}</span>
              <span>恢复 {{ fmt(mech.divergence_guard?.recover_threshold) }} · 触发 {{ fmt(mech.divergence_guard?.trip_threshold) }}</span>
            </div>
            <div v-if="!mech.divergence_guard?.fresh && !mech.divergence_guard?.disabled" class="text-[9px] text-[#f0b90b] mt-0.5">⚠ 数据陈旧（监控未推送）</div>
          </div>
          <div v-else class="text-[10px] text-gray-500 mt-0.5">{{ mech.divergence_guard?.note || '不可读' }}</div>
        </div>

        <!-- 停市护栏 -->
        <div class="mech">
          <div class="mech-top">
            <span>停市护栏</span>
            <span :class="['badge', mech.market_close_guard?.stopped ? 'badge-red' : 'badge-green']">
              {{ mech.market_close_guard?.stopped ? '已停（休市）' : '正常' }}
            </span>
          </div>
          <div v-if="mech.market_close_guard?.stopped && mech.market_close_guard?.affected?.length" class="text-[9px] text-gray-500 mt-0.5">
            受影响: {{ mech.market_close_guard.affected.map(slotLabel).join('、') }}
          </div>
        </div>

        <!-- 滑点保护 -->
        <div class="mech">
          <div class="mech-top">
            <span>滑点保护</span>
            <span :class="['badge', mech.slippage_guard?.paused ? 'badge-red' : 'badge-green']">
              {{ mech.slippage_guard?.paused ? ('暂停 L' + (mech.slippage_guard?.level ?? '?')) : '正常' }}
            </span>
          </div>
          <div v-if="mech.slippage_guard?.paused && mech.slippage_guard?.reason" class="text-[9px] text-gray-500 mt-0.5">{{ mech.slippage_guard.reason }}</div>
        </div>

        <!-- 紧急停止 -->
        <div class="mech">
          <div class="mech-top">
            <span>紧急停止</span>
            <span :class="['badge', mech.emergency_stop?.active ? 'badge-red' : 'badge-green']">{{ mech.emergency_stop?.active ? '已激活' : '未激活' }}</span>
          </div>
        </div>

        <!-- 心跳看门狗 -->
        <div class="mech">
          <div class="mech-top">
            <span>心跳看门狗</span>
            <span :class="['badge', mech.heartbeat_watchdog?.stale ? 'badge-red' : 'badge-green']">{{ mech.heartbeat_watchdog?.stale ? '挂死风险' : '正常' }}</span>
          </div>
          <div v-if="mech.heartbeat_watchdog?.worst_heartbeat_age_sec != null" class="text-[9px] text-gray-500 mt-0.5">
            最久心跳 {{ mech.heartbeat_watchdog.worst_heartbeat_age_sec }}s 前（阈值 120s）
          </div>
        </div>

        <!-- 撤单容差 -->
        <div class="mech">
          <div class="mech-top">
            <span>撤单容差</span>
            <span class="badge badge-gray">{{ fmt(mech.maker_cancel_tolerance?.tolerance) }}</span>
          </div>
        </div>

        <!-- 单腿防线 / 容量护栏（事件驱动，无常驻态） -->
        <div class="mech">
          <div class="mech-top">
            <span>单腿防线</span>
            <span class="badge badge-dim">事件驱动</span>
          </div>
        </div>
        <div class="mech">
          <div class="mech-top">
            <span>容量护栏</span>
            <span class="badge badge-dim">执行内部态</span>
          </div>
        </div>
      </div>

      <!-- ───────── 基础设施（简化样式） ───────── -->
      <div class="sec">
        <div class="sec-h"><span class="dot bg-[#3b82f6]"></span>基础设施</div>
        <div class="infra-grid">
          <div class="infra"><span :class="['dot-sm', wsConnected ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>WS</div>
          <div class="infra"><span :class="['dot-sm', dbBarCls]"></span>DB {{ dbPct }}%</div>
          <div class="infra"><span :class="['dot-sm', infra.redis?.connected ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>Redis</div>
          <div class="infra"><span :class="['dot-sm', feishuDot]"></span>飞书</div>
          <div class="infra"><span :class="['dot-sm', sslDot]"></span>SSL{{ infra.ssl_certificate?.days_remaining != null ? ' ' + infra.ssl_certificate.days_remaining + 'd' : '' }}</div>
          <div class="infra"><span :class="['dot-sm', sys.binance ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>Binance</div>
          <div class="infra"><span :class="['dot-sm', sys.mt5 ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>MT5</div>
          <div class="infra"><span :class="['dot-sm', sys.bybit ? 'bg-[#0ecb81]' : 'bg-[#f6465d]']"></span>Bybit</div>
        </div>

        <!-- 代理IP（简化：每账户一行徽章） -->
        <div class="mt-1">
          <div class="text-[10px] text-gray-400 mb-0.5">IPIPGO 静态IP代理 <span class="text-gray-600">({{ (infra.proxies || []).length }})</span></div>
          <div v-if="(infra.proxies || []).length" class="space-y-0.5">
            <div v-for="(p, i) in infra.proxies" :key="i" class="proxy-row">
              <span class="truncate text-gray-300" style="max-width:40%">{{ p.account_name }}</span>
              <span class="font-mono text-gray-500 truncate">{{ p.host }}:{{ p.port }}</span>
              <span :class="['badge', proxyBadge(p)]">{{ proxyText(p) }}<span v-if="p.expires_at" class="font-normal opacity-70"> {{ proxyDays(p) }}d</span></span>
            </div>
          </div>
          <div v-else class="text-[10px] text-gray-600">未配置代理 — 服务器直连</div>
        </div>
      </div>

      <div class="px-2 py-1 text-[9px] text-gray-600 text-right">实时事件驱动 · {{ lastUpdatedText }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import api from '@/services/api'
import { useMarketStore } from '@/stores/market'

const props = defineProps({
  active: { type: Boolean, default: false },
  pairCode: { type: String, default: 'XAU' },
})

const marketStore = useMarketStore()
const wsConnected = computed(() => marketStore.connected)

// ── 状态容器 ──
const sys = ref({ backend: false, strategyManager: false, positionMonitor: false, binance: false, bybit: false, mt5: false, dbPool: null, uptime: '' })
const infra = ref({ redis: null, feishu: null, ssl_certificate: null, ssl_all_certs: null, proxies: null })
const mech = ref({})
const posMonitor = ref({ monitoring: false, active: false })
const lastUpdatedAt = ref('')

// ── 自动策略进程 ──
const SLOTS = [
  { key: 'reverse_opening', label: '反向开仓' },
  { key: 'reverse_closing', label: '反向平仓' },
  { key: 'forward_opening', label: '正向开仓' },
  { key: 'forward_closing', label: '正向平仓' },
]
const SLOT_KEYS = SLOTS.map(s => s.key)
function slotLabel(k) { return (SLOTS.find(s => s.key === k) || {}).label || k }

function emptyProc() { return { running: false, status: 'idle', task_id: null, started_at: null, trigger: { current: 0, required: 0 }, current_ladder: null } }
function makeProcs() { return { reverse_opening: emptyProc(), reverse_closing: emptyProc(), forward_opening: emptyProc(), forward_closing: emptyProc() } }
const proc = ref(makeProcs())

const ladderCount = ref(3) // 阶梯段数（视觉），实际以 current_ladder 高亮

const anyStrategyRunning = computed(() => Object.values(proc.value).some(p => p.running))
const runningCount = computed(() => Object.values(proc.value).filter(p => p.running).length)

function procText(k) {
  const s = proc.value[k]?.status
  return ({ running: '运行中', completed: '已完成', failed: '失败', cancelled: '已停止' })[s] || '空闲'
}
function procDot(k) {
  const p = proc.value[k]
  if (p?.running) return 'bg-[#0ecb81] pulse'
  if (p?.status === 'failed') return 'bg-[#f6465d]'
  return 'bg-gray-600'
}
function procBadge(k) {
  const p = proc.value[k]
  if (p?.running) return 'badge-green'
  if (p?.status === 'failed') return 'badge-red'
  if (p?.status === 'completed') return 'badge-green'
  return 'badge-gray'
}
function trigPct(k) {
  const t = proc.value[k]?.trigger
  if (!t || !t.required) return 0
  return Math.min(100, Math.round((t.current / t.required) * 100))
}
function ladderSegCls(k, idx) {
  const cur = proc.value[k]?.current_ladder // 1-based
  if (cur == null) return 'seg-empty'
  if (idx < cur - 1) return 'seg-done'
  if (idx === cur - 1) return 'seg-active'
  return 'seg-empty'
}

// ── 机制：背离标尺百分比 ──
const divReadable = computed(() => mech.value.divergence_guard?.readable && !mech.value.divergence_guard?.disabled)
const tripThr = computed(() => Number(mech.value.divergence_guard?.trip_threshold) || 0.7)
const recoverThr = computed(() => Number(mech.value.divergence_guard?.recover_threshold) || 0.3)
const scaleMax = computed(() => Math.max(tripThr.value * 1.4, Math.abs(Number(mech.value.divergence_guard?.basis_diff) || 0) * 1.1, 0.1))
const tripPct = computed(() => Math.min(100, (tripThr.value / scaleMax.value) * 100))
const recoverPct = computed(() => Math.min(tripPct.value, (recoverThr.value / scaleMax.value) * 100))
const basisPct = computed(() => (Math.abs(Number(mech.value.divergence_guard?.basis_diff) || 0) / scaleMax.value) * 100)

// ── 基础设施视觉 ──
const dbPct = computed(() => {
  const d = sys.value.dbPool
  if (!d || !d.max) return 0
  return Math.round((d.active / d.max) * 100)
})
const dbBarCls = computed(() => dbPct.value >= 80 ? 'bg-[#f6465d]' : dbPct.value >= 60 ? 'bg-[#f0b90b]' : 'bg-[#0ecb81]')
const feishuDot = computed(() => {
  const s = infra.value.feishu?.status
  if (s === 'healthy') return 'bg-[#0ecb81]'
  if (s === 'not_configured') return 'bg-[#f0b90b]'
  return infra.value.feishu ? 'bg-[#f6465d]' : 'bg-gray-600'
})
const sslDot = computed(() => {
  const s = infra.value.ssl_certificate?.status
  if (s === 'healthy') return 'bg-[#0ecb81]'
  if (s === 'warning') return 'bg-[#f0b90b]'
  if (s === 'critical' || s === 'expired') return 'bg-[#f6465d]'
  return 'bg-gray-600'
})

// ── 顶部总览灯阵 ──
const healthDots = computed(() => {
  const d = []
  d.push({ key: 'strat', label: '策略', cls: anyStrategyRunning.value ? 'bg-[#0ecb81] pulse' : 'bg-gray-600', title: '自动策略进程' })
  d.push({ key: 'div', label: '背离', cls: mech.value.divergence_guard?.tripped ? 'bg-[#f6465d]' : (mech.value.divergence_guard?.disabled ? 'bg-gray-600' : 'bg-[#0ecb81]'), title: '背离护栏' })
  d.push({ key: 'slip', label: '滑点', cls: mech.value.slippage_guard?.paused ? 'bg-[#f6465d]' : 'bg-[#0ecb81]', title: '滑点保护' })
  d.push({ key: 'mkt', label: '停市', cls: mech.value.market_close_guard?.stopped ? 'bg-[#f6465d]' : 'bg-[#0ecb81]', title: '停市护栏' })
  d.push({ key: 'estop', label: '急停', cls: mech.value.emergency_stop?.active ? 'bg-[#f6465d]' : 'bg-[#0ecb81]', title: '紧急停止' })
  d.push({ key: 'wd', label: '看门狗', cls: mech.value.heartbeat_watchdog?.stale ? 'bg-[#f6465d]' : 'bg-[#0ecb81]', title: '心跳看门狗' })
  d.push({ key: 'ws', label: 'WS', cls: wsConnected.value ? 'bg-[#0ecb81]' : 'bg-[#f6465d]', title: 'WebSocket' })
  return d
})

const lastUpdatedText = computed(() => lastUpdatedAt.value ? new Date(lastUpdatedAt.value).toLocaleTimeString('zh-CN') : '—')

function fmt(v) { return (v == null || isNaN(v)) ? '-' : Number(v).toFixed(2) }

// ── 代理徽章 ──
function proxyStatusOf(p) { return p.ip_status || (p.expires_at && new Date(p.expires_at) < new Date() ? 'expired' : 'active') }
function proxyBadge(p) { return ({ active: 'badge-green', expired: 'badge-red', pending: 'badge-yellow', cancelled: 'badge-gray' })[proxyStatusOf(p)] || 'badge-green' }
function proxyText(p) { return ({ active: '正常', expired: '过期', pending: '待生效', cancelled: '取消' })[proxyStatusOf(p)] || '正常' }
function proxyDays(p) { return p.expires_at ? Math.ceil((new Date(p.expires_at) - new Date()) / 86400000) : '-' }

// ── 拉取 ──
async function fetchSystem() {
  try {
    const r = await api.get('/api/v1/system/status')
    sys.value = { ...sys.value, ...r.data }
  } catch {}
  try {
    const r = await api.get('/api/v1/monitor/status')
    const m = { ...r.data }
    if (Array.isArray(m.ssl_certificate) && m.ssl_certificate.length) {
      m.ssl_all_certs = m.ssl_certificate
      const go = m.ssl_certificate.find(c => (c.domain_names || []).includes('go.hustle2026.xyz'))
      m.ssl_certificate = go || m.ssl_certificate.reduce((b, c) => (c.days_remaining ?? 999) < (b.days_remaining ?? 999) ? c : b)
    }
    infra.value = { ...infra.value, ...m }
  } catch {}
  try {
    const r = await api.get('/api/v1/accounts/dashboard/aggregated')
    const accts = (r.data?.accounts || []).filter(a => a.proxy_config?.host)
    infra.value.proxies = accts.map(a => ({
      account_name: a.account_name || a.account_id, host: a.proxy_config.host, port: a.proxy_config.port,
      region: a.proxy_config.region, proxy_type: a.proxy_config.proxy_type, ip_status: a.proxy_config.ip_status,
      allocated_at: a.proxy_config.allocated_at, expires_at: a.proxy_config.expires_at,
    }))
  } catch { infra.value.proxies = [] }
  lastUpdatedAt.value = new Date().toISOString()
}

async function fetchProcesses() {
  try {
    const { data } = await api.get('/api/v1/strategies/execution/tasks')
    const next = makeProcs()
    for (const t of (data?.tasks || [])) {
      const st = t.strategy_type
      if (next[st]) {
        next[st].running = t.status === 'running'
        next[st].status = t.status || 'idle'
        next[st].task_id = t.task_id || null
        next[st].started_at = t.started_at || null
      }
    }
    for (const k of SLOT_KEYS) {
      const prev = proc.value[k]
      if (prev && next[k].task_id && next[k].task_id === prev.task_id) {
        next[k].trigger = prev.trigger
        next[k].current_ladder = prev.current_ladder
      }
    }
    proc.value = next
  } catch {}
  try {
    const { data } = await api.get('/api/v1/automation/position-monitor/status')
    posMonitor.value = { monitoring: !!data?.monitoring, active: !!data?.active }
  } catch {}
}

async function fetchMechanisms() {
  try {
    const { data } = await api.get(`/api/v1/strategies/mechanisms/${props.pairCode}`)
    mech.value = data?.mechanisms || {}
    // 用机制端点带回的 current_ladder_index 补充泳道（与 WS 互补）
    for (const t of (data?.running_tasks || [])) {
      const st = t.strategy_type
      if (proc.value[st] && t.current_ladder_index != null) {
        proc.value[st].current_ladder = (t.current_ladder_index | 0) + 1
      }
    }
  } catch {}
}

async function refreshAll() {
  await Promise.all([fetchSystem(), fetchProcesses(), fetchMechanisms()])
}

// ── 事件驱动：WS 推到才更新 ──
function slotFromSid(sid) {
  if (!sid) return ''
  for (const k of SLOT_KEYS) if (sid.includes(k)) return k
  return ''
}
function applyStrategyMsg(type, d) {
  if (!d) return
  const k = slotFromSid(d.strategy_id)
  if (!k) return
  const p = { ...proc.value[k] }
  switch (type) {
    case 'strategy_execution_started': p.running = true; p.status = 'running'; p.task_id = d.task_id || p.task_id; p.started_at = p.started_at || new Date().toISOString(); break
    case 'strategy_execution_completed': p.status = 'completed'; p.running = false; break
    case 'strategy_execution_error': p.status = 'failed'; p.running = false; break
    case 'strategy_stop_confirmed': p.status = 'cancelled'; p.running = false; p.trigger = { current: 0, required: 0 }; p.current_ladder = null; break
    case 'strategy_trigger_progress': if (!p.running) { p.running = true; p.status = 'running' } p.trigger = { current: d.current_count ?? 0, required: d.required_count ?? p.trigger.required ?? 0 }; break
    case 'strategy_trigger_reset': p.trigger = { current: 0, required: p.trigger.required }; break
    case 'strategy_order_executed': if (d.ladder_index != null) p.current_ladder = d.ladder_index + 1; break
    default: return
  }
  proc.value = { ...proc.value, [k]: p }
}
function applyMainMsg(m) {
  if (!m || !m.type) return
  if (m.type === 'redis_status') {
    const connected = (m.data?.connected ?? m.data?.healthy) === true
    infra.value = { ...infra.value, redis: { ...(infra.value.redis || {}), connected, error: m.data?.last_error ?? m.data?.error ?? null } }
    lastUpdatedAt.value = new Date().toISOString()
  } else if (m.type === 'mt5_connection_status') {
    sys.value = { ...sys.value, mt5: !!m.data?.healthy }
    lastUpdatedAt.value = new Date().toISOString()
  } else if (m.type === 'quote_divergence') {
    // 背离监控全局广播，实时更新标尺
    const d = m.data || {}
    mech.value = { ...mech.value, divergence_guard: { ...(mech.value.divergence_guard || {}), readable: true, tripped: !!d.diverged, disabled: !!d.disabled, basis_diff: d.diff, trip_threshold: d.trip, recover_threshold: d.recover, fresh: true } }
    lastUpdatedAt.value = new Date().toISOString()
  }
}

let stopMain = null, stopStrat = null, mechTimer = null

function startWatch() {
  refreshAll()
  stopMain = watch(() => marketStore.lastMessage, (m) => applyMainMsg(m))
  stopStrat = watch(() => marketStore.strategyMessage, (m) => { if (m && typeof m.type === 'string' && m.type.startsWith('strategy_')) applyStrategyMsg(m.type, m.data) })
  // 机制态多为 REST/Redis 快照(背离走 WS)；面板可见时低频兜底刷新机制+进程态(30s)，纯事件无法覆盖的部分
  mechTimer = setInterval(() => { fetchMechanisms(); fetchProcesses() }, 30000)
}
function stopWatch() {
  if (stopMain) { stopMain(); stopMain = null }
  if (stopStrat) { stopStrat(); stopStrat = null }
  if (mechTimer) { clearInterval(mechTimer); mechTimer = null }
}

watch(() => props.active, (a) => { a ? startWatch() : stopWatch() })
watch(() => props.pairCode, () => { if (props.active) refreshAll() })
onMounted(() => { if (props.active) startWatch() })
onUnmounted(stopWatch)
</script>

<style scoped>
.status-panel { background: #1e2329; }
.status-scroll { height: 300px; overflow-y: auto; overflow-x: hidden; }
.scrollbar-hide { scrollbar-width: none; -ms-overflow-style: none; }
.scrollbar-hide::-webkit-scrollbar { display: none; }

.sec { padding: 6px 8px; border-bottom: 1px solid #2b3139; }
.sec-h { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #e5e7eb; margin-bottom: 5px; font-size: 11px; }

.dot { width: 7px; height: 7px; border-radius: 9999px; display: inline-block; flex-shrink: 0; }
.dot-sm { width: 6px; height: 6px; border-radius: 9999px; display: inline-block; flex-shrink: 0; }
.pulse { animation: pul 1.6s ease-in-out infinite; }
@keyframes pul { 0%,100% { opacity: 1; } 50% { opacity: .4; } }

.comp { display: flex; align-items: center; justify-content: space-between; background: #252930; border: 1px solid #2b3139; border-radius: 4px; padding: 3px 6px; }
.lane { background: #252930; border: 1px solid #2b3139; border-radius: 4px; padding: 5px 6px; margin-bottom: 4px; }

.badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; white-space: nowrap; }
.badge-green { background: rgba(14,203,129,.18); color: #0ecb81; }
.badge-red { background: rgba(246,70,93,.18); color: #f6465d; }
.badge-yellow { background: rgba(240,185,11,.18); color: #f0b90b; }
.badge-gray { background: #2b3139; color: #9ca3af; }
.badge-dim { background: #252930; color: #6b7280; border: 1px solid #2b3139; }

.ladder-seg { flex: 1; height: 8px; border-radius: 2px; }
.seg-done { background: #0ecb81; }
.seg-active { background: #f0b90b; animation: pul 1.6s ease-in-out infinite; }
.seg-empty { background: #2b3139; }

.track { width: 100%; height: 4px; background: #0d1117; border-radius: 9999px; overflow: hidden; }
.fill { height: 100%; border-radius: 9999px; transition: width .3s ease; }

.mech { background: #252930; border: 1px solid #2b3139; border-radius: 4px; padding: 5px 6px; margin-bottom: 4px; }
.mech-top { display: flex; align-items: center; justify-content: space-between; color: #d1d5db; }

.gauge-track { position: relative; width: 100%; height: 6px; border-radius: 9999px; overflow: hidden; background: #0d1117; }
.gauge-zone-ok { position: absolute; top: 0; left: 0; height: 100%; background: rgba(14,203,129,.5); }
.gauge-zone-warn { position: absolute; top: 0; height: 100%; background: rgba(240,185,11,.5); }
.gauge-zone-bad { position: absolute; top: 0; height: 100%; background: rgba(246,70,93,.5); }
.gauge-marker { position: absolute; top: -2px; width: 2px; height: 10px; background: #fff; box-shadow: 0 0 3px rgba(255,255,255,.8); transition: left .3s ease; }

.infra-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
.infra { display: flex; align-items: center; gap: 4px; background: #252930; border: 1px solid #2b3139; border-radius: 4px; padding: 3px 5px; color: #d1d5db; font-size: 10px; }

.proxy-row { display: flex; align-items: center; justify-content: space-between; gap: 6px; background: #252930; border: 1px solid #2b3139; border-radius: 4px; padding: 2px 6px; font-size: 10px; }
</style>
