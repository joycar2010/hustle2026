<template>
  <!-- V6.2 R2 自动运行状态条(§4.1):紧凑事实带,不做大卡片。
       只读监督;控制动作 R4 才接统一 typed command。源不可达=如实降级,不编数。 -->
  <div v-if="sum" class="autostrip" :class="{warn: hasWarn}">
    <span class="seg"><i>自动回路</i><b>{{ nTotal }}</b></span>
    <span class="seg"><i>真钱writer</i><b class="hot">{{ nNewRisk }}</b></span>
    <span class="seg"><i>shadow/只读</i><b>{{ nSafe }}</b></span>
    <span class="sep">|</span>
    <span class="seg"><i>相位环</i>
      <b :class="phaseArmed ? 'hot' : ''">{{ phaseArmed ? 'ARMED' : (phaseArmed === null ? '未知' : '未武装') }}</b>
      <i v-if="phaseLastTs" class="ts">最近 {{ ago(phaseLastTs) }}</i>
    </span>
    <span class="seg" v-if="c3s"><i>C3.S影子环</i><b>{{ c3sLine }}</b></span>
    <span class="sep">|</span>
    <span class="seg"><i>发布一致性</i>
      <b :class="driftCls">{{ driftText }}</b>
    </span>
    <span class="fill"></span>
    <a class="more" @click="drawer = true">回路详情 →</a>

    <el-drawer v-model="drawer" title="自动回路监督(只读 · R0 审计登记册)" size="720px" :append-to-body="true">
      <div class="drawbody">
        <div class="note">登记册=2026-07-26 R0 逐行审计;TEMP_OBSERVATION 源不作审计权威;控制动作未开放(R4 走统一命令)。</div>
        <table class="ltab">
          <thead><tr><th>回路</th><th>机器</th><th>产品</th><th>身份</th><th>风险类</th><th>阶段</th><th>节奏</th></tr></thead>
          <tbody>
            <tr v-for="l in loops" :key="l.loop_id" :class="{sel: tlId===l.loop_id, hot: l.risk_class==='NEW_RISK'}"
                @click="loadTl(l.loop_id)">
              <td><b>{{ l.display_name }}</b><i class="lid">{{ l.loop_id }}</i></td>
              <td>{{ l.machine }}</td>
              <td>{{ l.product_code }}</td>
              <td>{{ l.principal_kind }}</td>
              <td><span class="chip" :class="riskCls(l.risk_class)">{{ l.risk_class }}</span></td>
              <td>{{ l.runtime_stage }}</td>
              <td>{{ l.schedule }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="tlId" class="tl">
          <div class="tlhd"><b>{{ tlId }} 时间线</b>
            <span class="chip" :class="tlGrade==='AUDIT_TABLE'?'ok':'dim'">{{ tlGrade==='AUDIT_TABLE'?'审计表':'临时观测' }}</span>
          </div>
          <div v-if="tlNote" class="note">{{ tlNote }}</div>
          <pre v-for="(e,i) in tlEvents" :key="i" class="ev">{{ evLine(e) }}</pre>
          <div v-if="!tlEvents.length" class="note">暂无 C 侧可读事件(B 侧事实流为 R2 后续)</div>
        </div>
        <div class="chain" v-if="tlLoop">
          <i>执行链(R0 审计)</i><span>{{ tlLoop.chain_note }}</span>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { mixApi } from '../../api/mix'

const sum = ref(null)
const loops = ref([])
const drawer = ref(false)
const tlId = ref('')
const tlEvents = ref([])
const tlGrade = ref('')
const tlNote = ref('')
let timer = null

async function load () {
  try {
    sum.value = await mixApi.automationSummary()
  } catch (e) { /* 401 全局接管;其余保持旧值 */ }
}
async function loadLoops () {
  try { loops.value = (await mixApi.automationLoops()).loops || [] } catch (e) {}
}
async function loadTl (id) {
  tlId.value = id
  tlEvents.value = []; tlGrade.value = ''; tlNote.value = ''
  try {
    const r = await mixApi.automationTimeline(id, 30)
    tlEvents.value = r.events || []
    tlGrade.value = r.evidence_grade || ''
    tlNote.value = r.note || r.error || ''
  } catch (e) { tlNote.value = '时间线拉取失败' }
}
onMounted(() => { load(); loadLoops(); timer = setInterval(load, 30000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

const nTotal = computed(() => loops.value.length || (sum.value?.counts || []).reduce((a, c) => a + (c.n || 0), 0))
const nNewRisk = computed(() => loops.value.filter(l => l.risk_class === 'NEW_RISK').length)
const nSafe = computed(() => loops.value.filter(l => l.risk_class === 'READ_ONLY').length)
const phaseArmed = computed(() => {
  const k = sum.value?.phase_autopilot?.armed_redis_key
  if (k == null) return null
  return String(k) === '1'
})
const phaseLastTs = computed(() => sum.value?.phase_autopilot?.last_log_ts || null)
const c3s = computed(() => sum.value?.c3s_autopilot_last_cycle || null)
const c3sLine = computed(() => {
  if (!c3s.value) return '—'
  return `候选${c3s.value.n_candidates ?? '—'}/信号${c3s.value.n_signal ?? '—'}/would-open${c3s.value.n_v6_open ?? '—'}`
})
const drift = computed(() => sum.value?.release_drift || null)
const driftText = computed(() => {
  if (!drift.value) return '未知'
  if (drift.value.clean) return '源码一致'
  const c = drift.value.counts || {}
  return `漂移 P0:${c.P0 || 0} P1:${c.P1 || 0} OPS:${c.OPS || 0}`
})
const driftCls = computed(() => !drift.value ? 'dim' : (drift.value.clean ? 'ok' : (drift.value.counts?.P0 ? 'bad' : 'wn')))
const hasWarn = computed(() => (drift.value && !drift.value.clean && drift.value.counts?.P0 > 0))
const tlLoop = computed(() => loops.value.find(l => l.loop_id === tlId.value) || null)

function ago (ts) {
  const t = typeof ts === 'number' ? ts * (ts > 2e10 ? 1 : 1000) : Date.parse(ts)
  if (!t || isNaN(t)) return String(ts).slice(0, 16)
  const s = Math.max(0, (Date.now() - t) / 1000)
  if (s < 90) return Math.round(s) + 's前'
  if (s < 5400) return Math.round(s / 60) + 'm前'
  return Math.round(s / 3600) + 'h前'
}
function riskCls (r) { return r === 'NEW_RISK' ? 'red' : (r === 'READ_ONLY' ? 'ok' : 'wn') }
function evLine (e) {
  if (e == null) return ''
  if (typeof e === 'string') return e
  const ts = e.ts ? (typeof e.ts === 'number' ? new Date(e.ts * (e.ts > 2e10 ? 1 : 1000)).toISOString().slice(5, 19) : String(e.ts).slice(5, 19)) : ''
  const rest = Object.entries(e).filter(([k]) => k !== 'ts').map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ')
  return `${ts}  ${rest}`.slice(0, 220)
}
</script>

<style scoped>
.autostrip{display:flex;align-items:center;gap:10px;padding:4px 12px;background:#181A20;border-bottom:1px solid #2B3139;font-size:12px;color:#B7BDC6;flex-wrap:wrap}
.autostrip.warn{border-bottom-color:#F6465D}
.seg{display:inline-flex;align-items:center;gap:5px}
.seg i{color:#848E9C;font-style:normal}
.seg b{color:#EAECEF;font-weight:600}
.seg b.hot{color:#F0B90B}
.seg b.ok{color:#0ECB81}.seg b.wn{color:#F0B90B}.seg b.bad{color:#F6465D}.seg b.dim{color:#848E9C}
.seg .ts{color:#5E6673;font-style:normal;margin-left:2px}
.sep{color:#2B3139}
.fill{flex:1}
.more{color:#F0B90B;cursor:pointer;font-size:12px}
.drawbody{padding:0 4px;font-size:12px;color:#B7BDC6}
.note{color:#848E9C;margin:6px 0;line-height:1.5}
.ltab{width:100%;border-collapse:collapse}
.ltab th{color:#848E9C;text-align:left;padding:4px 6px;border-bottom:1px solid #2B3139;font-weight:400}
.ltab td{padding:5px 6px;border-bottom:1px solid #22262E;cursor:pointer}
.ltab tr.sel td{background:#22262E}
.ltab td b{color:#EAECEF;display:block}
.ltab .lid{color:#5E6673;font-style:normal;font-size:11px}
.chip{padding:0 6px;border-radius:3px;font-size:11px}
.chip.red{background:rgba(246,70,93,.15);color:#F6465D}
.chip.ok{background:rgba(14,203,129,.15);color:#0ECB81}
.chip.wn{background:rgba(240,185,11,.15);color:#F0B90B}
.chip.dim{background:#22262E;color:#848E9C}
.tl{margin-top:10px}
.tlhd{display:flex;gap:8px;align-items:center;color:#EAECEF;margin-bottom:4px}
.ev{margin:0;padding:2px 6px;border-left:2px solid #2B3139;color:#B7BDC6;font-size:11px;white-space:pre-wrap;word-break:break-all}
.chain{margin-top:10px;color:#848E9C}
.chain i{font-style:normal;color:#5E6673;margin-right:6px}
</style>
