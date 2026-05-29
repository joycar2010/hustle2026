<template>
  <div class="min-h-screen bg-[#0a0a12] text-[#e5e7eb] p-4">
    <div class="max-w-6xl mx-auto space-y-3">
      <!-- Toolbar -->
      <div class="flex items-center gap-2 flex-wrap">
        <label class="text-[10px] text-[#6b7280]">开始:</label>
        <input
          type="datetime-local"
          v-model="startInput"
          class="bg-[#1a1a22] border border-[#2d2d3d] rounded px-2 py-1 text-xs text-[#e5e7eb] focus:outline-none focus:border-[#fcd535]"
        />
        <label class="text-[10px] text-[#6b7280]">结束:</label>
        <input
          type="datetime-local"
          v-model="endInput"
          class="bg-[#1a1a22] border border-[#2d2d3d] rounded px-2 py-1 text-xs text-[#e5e7eb] focus:outline-none focus:border-[#fcd535]"
        />

        <div class="flex rounded border border-[#2d2d3d]">
          <button
            v-for="iv in INTERVALS"
            :key="iv.value"
            @click="intervalSec = iv.value; fetchData()"
            :class="[
              'px-2 py-1 text-[10px] border-r border-[#2d2d3d] last:border-0 transition-colors',
              intervalSec === iv.value
                ? 'bg-[#fcd535] text-black font-medium'
                : 'text-[#6b7280] hover:bg-[#1e1e2e] hover:text-[#e5e7eb]'
            ]"
          >
            {{ iv.label }}
          </button>
        </div>

        <button
          @click="fetchData"
          :disabled="loading"
          class="px-3 py-1 bg-[#fcd535] text-black rounded text-[10px] font-medium hover:bg-[#e5c230] disabled:opacity-50"
        >
          {{ loading ? '加载中...' : '查询' }}
        </button>

        <span v-if="dataPointCount > 0" class="text-[10px] text-[#6b7280]">
          {{ dataPointCount }} 个数据点
        </span>
      </div>

      <!-- Legend (static) -->
      <div class="flex items-center gap-4 text-[10px] font-mono">
        <span class="flex items-center gap-1">
          <span class="w-3 h-0.5 bg-[#22c55e] inline-block"></span>
          <span class="text-[#6b7280]">正向开仓点差</span>
        </span>
        <span class="flex items-center gap-1">
          <span class="w-3 h-0.5 bg-[#ef4444] inline-block"></span>
          <span class="text-[#6b7280]">反向开仓点差</span>
        </span>
      </div>

      <!-- Range Statistics -->
      <div v-if="rangeStats.count > 0" class="flex items-center gap-3 text-[10px] font-mono flex-wrap bg-[#111118] rounded px-3 py-2 border border-[#2d2d3d]">
        <span class="text-[#6b7280]">可视区间</span>
        <span class="text-[#9ca3af]">{{ rangeStats.startTime }} ~ {{ rangeStats.endTime }}</span>
        <span class="text-[#6b7280]">|</span>
        <span class="text-[#6b7280]">正向</span>
        <span class="text-[#22c55e]">高 {{ rangeStats.fwdMax.toFixed(2) }}</span>
        <span class="text-[#ef4444]">低 {{ rangeStats.fwdMin.toFixed(2) }}</span>
        <span class="text-[#e5e7eb]">均 {{ rangeStats.fwdAvg.toFixed(2) }}</span>
        <span class="text-[#6b7280]">|</span>
        <span class="text-[#6b7280]">反向</span>
        <span class="text-[#22c55e]">高 {{ rangeStats.revMax.toFixed(2) }}</span>
        <span class="text-[#ef4444]">低 {{ rangeStats.revMin.toFixed(2) }}</span>
        <span class="text-[#e5e7eb]">均 {{ rangeStats.revAvg.toFixed(2) }}</span>
        <span class="text-[#6b7280]">| {{ rangeStats.count }} 点</span>
      </div>

      <!-- Chart + Floating Tooltip -->
      <div class="rounded border border-[#2d2d3d] overflow-hidden relative" ref="chartWrap">
        <div ref="chartContainer" class="w-full" :style="{ height: chartHeight + 'px' }"></div>
        <!-- Floating tooltip -->
        <div
          v-show="tooltip.show"
          class="spread-tooltip"
          :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
        >
          <div class="tt-time">{{ tooltip.time }}</div>
          <div class="tt-row">
            <span class="tt-dot" style="background:#22c55e"></span>
            <span class="tt-label">正向</span>
            <span class="tt-val" style="color:#22c55e">{{ tooltip.fwd }}</span>
          </div>
          <div class="tt-row">
            <span class="tt-dot" style="background:#ef4444"></span>
            <span class="tt-label">反向</span>
            <span class="tt-val" style="color:#ef4444">{{ tooltip.rev }}</span>
          </div>
        </div>
      </div>

      <!-- Usage Hint -->
      <div class="text-[10px] text-[#4b5563] text-center">
        拖拽平移 · 滚轮缩放 · 缩放到目标时段后查看区间统计（最高/最低/均值）
      </div>
    </div>

    <!-- ── 滑点保护事件审计 (审计专用, 不可操作) ───────────────────── -->
    <div class="mt-4 bg-[#0a0a12] rounded border border-[#2d2d3d] p-3">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-sm font-semibold text-[#fcd535]">滑点保护事件</h3>
        <div class="flex items-center gap-2">
          <select v-model="slipPairFilter" @change="loadSlippageEvents" class="text-xs bg-[#1a1a22] border border-[#2d2d3d] rounded px-2 py-0.5 text-[#e5e7eb]">
            <option value="">全部产品对</option>
            <option v-for="p in (slipPairList || [])" :key="p" :value="p">{{ p }}</option>
          </select>
          <button @click="loadSlippageEvents" class="text-[10px] text-[#6b7280] hover:text-[#e5e7eb] px-2 py-0.5 border border-[#2d2d3d] rounded">刷新</button>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-left text-[#6b7280] border-b border-[#2d2d3d]">
              <th class="py-1.5 px-1">时间</th>
              <th class="py-1.5 px-1">产品对</th>
              <th class="py-1.5 px-1">策略</th>
              <th class="py-1.5 px-1">阈值</th>
              <th class="py-1.5 px-1">实际价差</th>
              <th class="py-1.5 px-1">滑点</th>
              <th class="py-1.5 px-1">级别</th>
              <th class="py-1.5 px-1">Binance 均价</th>
              <th class="py-1.5 px-1">MT5 均价</th>
              <th class="py-1.5 px-1">订单号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!slipEvents.length">
              <td colspan="10" class="text-center py-4 text-[#6b7280]">暂无滑点事件</td>
            </tr>
            <tr v-for="ev in slipEvents" :key="ev.id" class="border-b border-[#1a1a22]">
              <td class="py-1 px-1 text-[#6b7280]">{{ formatSlipTime(ev.created_at) }}</td>
              <td class="py-1 px-1 font-mono text-[#fcd535]">{{ ev.pair_code }}</td>
              <td class="py-1 px-1 text-[#9ca3af]">{{ ev.strategy_type }}</td>
              <td class="py-1 px-1 font-mono">{{ (ev.spread_threshold ?? 0).toFixed(3) }}</td>
              <td class="py-1 px-1 font-mono">{{ (ev.actual_spread ?? 0).toFixed(3) }}</td>
              <td class="py-1 px-1 font-mono" :class="Math.abs(ev.slippage ?? 0) > 1.2 ? 'text-[#ef4444]' : 'text-[#f0b90b]'">
                {{ (ev.slippage ?? 0).toFixed(3) }}
              </td>
              <td class="py-1 px-1">
                <span :class="ev.level === 2 ? 'bg-[#ef4444]/20 text-[#ef4444] px-1.5 rounded text-[10px]' : 'bg-[#f0b90b]/20 text-[#f0b90b] px-1.5 rounded text-[10px]'">
                  L{{ ev.level }}
                </span>
              </td>
              <td class="py-1 px-1 font-mono">{{ (ev.binance_avg_price ?? 0).toFixed(2) }}</td>
              <td class="py-1 px-1 font-mono">{{ (ev.bybit_avg_price ?? 0).toFixed(2) }}</td>
              <td class="py-1 px-1 font-mono text-[10px] text-[#6b7280] truncate max-w-[100px]">{{ ev.binance_order_id || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-2 text-[10px] text-[#6b7280]">
        L1 = 单次 |滑点| > 0.9 (10分钟无操作自动恢复) · L2 = 连续2次 |滑点| > 1.2 (需用户强制启动)
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { createChart, LineSeries, ColorType, CrosshairMode } from 'lightweight-charts'
import api from '@/services/api'

// ── 滑点保护事件审计 ───────────────────────────────
const slipEvents = ref([])
const slipPairFilter = ref('')
const slipPairList = computed(() => {
  const set = new Set()
  for (const e of slipEvents.value) if (e.pair_code) set.add(e.pair_code)
  return Array.from(set)
})

async function loadSlippageEvents() {
  try {
    const params = {}
    if (slipPairFilter.value) params.pair_code = slipPairFilter.value
    params.limit = 200
    const r = await api.get('/api/v1/strategies/slippage-events', { params })
    slipEvents.value = r.data?.events || []
  } catch (e) {
    console.error('Failed to load slippage events:', e)
    slipEvents.value = []
  }
}

function formatSlipTime(ts) {
  if (!ts) return '-'
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch { return ts }
}

const isMobile = ref(window.innerWidth < 768)
const chartHeight = computed(() => isMobile.value ? 300 : 440)

const INTERVALS = [
  { label: '1秒', value: 1 },
  { label: '5秒', value: 5 },
  { label: '10秒', value: 10 },
  { label: '30秒', value: 30 },
  { label: '1分', value: 60 },
]

function getBJLocalISO(date) {
  const bj = new Date(date.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  const y = bj.getFullYear()
  const m = String(bj.getMonth() + 1).padStart(2, '0')
  const d = String(bj.getDate()).padStart(2, '0')
  const h = String(bj.getHours()).padStart(2, '0')
  const min = String(bj.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${d}T${h}:${min}`
}

function bjSecToFull(bjSec) {
  const d = new Date(bjSec * 1000)
  const y = d.getUTCFullYear()
  const mo = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  const ss = String(d.getUTCSeconds()).padStart(2, '0')
  return `${y}-${mo}-${day} ${hh}:${mm}:${ss}`
}

function bjSecToShort(bjSec) {
  const d = new Date(bjSec * 1000)
  const mo = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  const ss = String(d.getUTCSeconds()).padStart(2, '0')
  return `${mo}-${day} ${hh}:${mm}:${ss}`
}

const now = new Date()
const startDefault = new Date(now.getTime() - (isMobile.value ? 2 : 24) * 3600000)
const startInput = ref(getBJLocalISO(startDefault))
const endInput = ref(getBJLocalISO(now))
const intervalSec = ref(5)
const loading = ref(false)
const dataPointCount = ref(0)

const tooltip = reactive({ show: false, x: 0, y: 0, time: '', fwd: '', rev: '' })

const rangeStats = ref({
  count: 0, startTime: '', endTime: '',
  fwdMax: 0, fwdMin: 0, fwdAvg: 0,
  revMax: 0, revMin: 0, revAvg: 0,
})

const chartWrap = ref(null)
const chartContainer = ref(null)
let chart = null
let forwardSeries = null
let reverseSeries = null
let fwdData = []
let revData = []

function initChart() {
  if (!chartContainer.value || chart) return
  chart = createChart(chartContainer.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#0a0a12' },
      textColor: '#9ca3af',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: '#1e1e2e' },
      horzLines: { color: '#1e1e2e' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: '#fcd535', width: 1, style: 2, labelBackgroundColor: '#fcd535' },
      horzLine: { color: '#9ca3af', width: 1, style: 2, labelBackgroundColor: '#2d2d3d' },
    },
    timeScale: {
      timeVisible: true,
      secondsVisible: true,
      borderColor: '#2d2d3d',
    },
    rightPriceScale: { borderColor: '#2d2d3d' },
    localization: {
      timeFormatter: (time) => bjSecToFull(time),
    },
    width: chartContainer.value.clientWidth,
    height: chartHeight.value,
  })

  forwardSeries = chart.addSeries(LineSeries, {
    color: '#22c55e',
    lineWidth: 1.5,
    title: '正向',
    priceLineVisible: false,
    lastValueVisible: true,
  })

  reverseSeries = chart.addSeries(LineSeries, {
    color: '#ef4444',
    lineWidth: 1.5,
    title: '反向',
    priceLineVisible: false,
    lastValueVisible: true,
  })

  chart.subscribeCrosshairMove((param) => {
    if (!param || !param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
      tooltip.show = false
      return
    }
    const fwdPoint = param.seriesData.get(forwardSeries)
    const revPoint = param.seriesData.get(reverseSeries)
    if (!fwdPoint && !revPoint) {
      tooltip.show = false
      return
    }

    tooltip.time = bjSecToFull(param.time)
    tooltip.fwd = fwdPoint ? fwdPoint.value.toFixed(2) : '—'
    tooltip.rev = revPoint ? revPoint.value.toFixed(2) : '—'

    const wrapRect = chartWrap.value.getBoundingClientRect()
    const chartRect = chartContainer.value.getBoundingClientRect()
    const mouseX = param.point.x
    const mouseY = param.point.y

    const tooltipW = 190
    const tooltipH = 70
    let tx = mouseX + 15
    let ty = mouseY - tooltipH - 10

    if (tx + tooltipW > chartRect.width) tx = mouseX - tooltipW - 15
    if (ty < 0) ty = mouseY + 15
    if (tx < 0) tx = 5

    tooltip.x = tx
    tooltip.y = ty
    tooltip.show = true
  })

  chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    computeRangeStats()
  })

  nextTick(() => {
    if (chartContainer.value) {
      const links = chartContainer.value.querySelectorAll('a[href*="tradingview"]')
      links.forEach(a => a.style.display = 'none')
    }
  })
}

function computeRangeStats() {
  if (!chart || !fwdData.length) {
    rangeStats.value = { count: 0, startTime: '', endTime: '', fwdMax: 0, fwdMin: 0, fwdAvg: 0, revMax: 0, revMin: 0, revAvg: 0 }
    return
  }
  const logicalRange = chart.timeScale().getVisibleLogicalRange()
  if (!logicalRange) return

  const startIdx = Math.max(0, Math.ceil(logicalRange.from))
  const endIdx = Math.min(fwdData.length - 1, Math.floor(logicalRange.to))
  if (startIdx > endIdx) return

  let fMax = -Infinity, fMin = Infinity, fSum = 0
  let rMax = -Infinity, rMin = Infinity, rSum = 0
  let count = 0

  for (let i = startIdx; i <= endIdx; i++) {
    const fv = fwdData[i].value
    const rv = revData[i].value
    if (fv > fMax) fMax = fv
    if (fv < fMin) fMin = fv
    fSum += fv
    if (rv > rMax) rMax = rv
    if (rv < rMin) rMin = rv
    rSum += rv
    count++
  }

  if (count === 0) return
  rangeStats.value = {
    count,
    startTime: bjSecToShort(fwdData[startIdx].time),
    endTime: bjSecToShort(fwdData[endIdx].time),
    fwdMax: fMax, fwdMin: fMin, fwdAvg: fSum / count,
    revMax: rMax, revMin: rMin, revAvg: rSum / count,
  }
}

function destroyChart() {
  if (chart) { chart.remove(); chart = null; forwardSeries = null; reverseSeries = null }
}

async function fetchData() {
  loading.value = true
  try {
    const startUTC = new Date(startInput.value + ':00+08:00')
    const endUTC = new Date(endInput.value + ':00+08:00')

    const params = new URLSearchParams({
      start_time: startUTC.toISOString(),
      end_time: endUTC.toISOString(),
      interval: String(intervalSec.value),
    })

    const token = localStorage.getItem('token')
    const resp = await fetch(`/api/v1/market/spread/chart?${params}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    dataPointCount.value = data.length

    if (!chart) { await nextTick(); initChart() }
    // Guard against initChart() failing (chart container not yet mounted)
    if (!chart || !forwardSeries || !reverseSeries) {
      console.warn('Chart not initialized yet, retry next tick')
      await nextTick()
      if (!chart) initChart()
      if (!chart || !forwardSeries || !reverseSeries) {
        console.error('Chart still null after retry — skipping setData')
        return
      }
    }

    fwdData = []
    revData = []
    for (const row of data) {
      const utcMs = new Date(row.t).getTime()
      const bjSec = Math.floor((utcMs + 8 * 3600000) / 1000)
      fwdData.push({ time: bjSec, value: row.fs })
      revData.push({ time: bjSec, value: row.rs })
    }

    fwdData.sort((a, b) => a.time - b.time)
    revData.sort((a, b) => a.time - b.time)

    forwardSeries.setData(fwdData)
    reverseSeries.setData(revData)
    chart.timeScale().fitContent()
  } catch (e) {
    console.error('Fetch spread chart failed:', e)
  } finally {
    loading.value = false
  }
}

function onResize() {
  isMobile.value = window.innerWidth < 768
  if (chart && chartContainer.value) {
    chart.applyOptions({ width: chartContainer.value.clientWidth, height: chartHeight.value })
  }
}

let resizeObs = null
onMounted(() => {
  window.addEventListener('resize', onResize)
  nextTick(() => { initChart(); fetchData(); loadSlippageEvents() })
  if (window.ResizeObserver && chartContainer.value) {
    resizeObs = new ResizeObserver(() => {
      if (chart && chartContainer.value) {
        chart.applyOptions({ width: chartContainer.value.clientWidth, height: chartHeight.value })
      }
    })
    resizeObs.observe(chartContainer.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (resizeObs) resizeObs.disconnect()
  destroyChart()
})
</script>

<style scoped>
input[type="datetime-local"]::-webkit-calendar-picker-indicator {
  filter: invert(0.7);
}
:deep(a[href*="tradingview"]) {
  display: none !important;
}

.spread-tooltip {
  position: absolute;
  z-index: 100;
  pointer-events: none;
  background: rgba(20, 20, 32, 0.95);
  border: 1px solid #2d2d3d;
  border-radius: 6px;
  padding: 8px 12px;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.6;
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
  white-space: nowrap;
}
.tt-time {
  color: #fcd535;
  font-weight: 600;
  margin-bottom: 3px;
}
.tt-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tt-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tt-label {
  color: #6b7280;
  min-width: 24px;
}
.tt-val {
  font-weight: 600;
}
</style>
