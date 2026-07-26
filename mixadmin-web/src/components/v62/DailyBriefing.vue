<template>
  <!-- V6.2 R3 每日开班简报(§4.3):每天首次进入自动出现一次(localStorage 去重,单操作员规模)。
       无待办不庆祝;所有事实来自已加载快照+automation summary,不编数。 -->
  <el-dialog v-model="open" title="今日值守简报" width="480px" :close-on-click-modal="false"
             :append-to-body="true" class="brief">
    <div class="bd">
      <div class="fact"><i>能不能开新仓</i>
        <b :class="canOpen ? 'ok' : 'bad'">{{ canOpen ? '可以(闸全绿)' : '受限' }}</b>
        <span v-if="!canOpen && blockReason" class="why">{{ blockReason }}</span></div>
      <div class="fact"><i>自动回路</i>
        <b :class="autoCls">{{ autoText }}</b></div>
      <div class="fact"><i>发布一致性</i>
        <b :class="driftOk===null ? 'dim' : (driftOk ? 'ok' : 'bad')">{{ driftOk===null ? '未知' : (driftOk ? '源码一致' : '发现漂移') }}</b></div>
      <div class="fact col"><i>最先处理({{ topItems.length }})</i>
        <div v-if="topItems.length" class="tops">
          <div v-for="w in topItems" :key="w.work_item_id" class="ti" @click="go(w)">
            <b>{{ w.symbol }}</b> · {{ w.strategy_code }} · {{ w.stage_detail || w.next_action || w.workflow_stage }}
          </div>
        </div>
        <b v-else class="ok calm">当前无人工待办,自动回路按规则运行</b></div>
      <div class="fact"><i>下一关键时间</i><b>{{ nextDeadline || '—' }}</b></div>
    </div>
    <template #footer>
      <el-button v-if="topItems.length" type="warning" @click="goTop">带我处理最高优先级</el-button>
      <el-button @click="close">稍后处理</el-button>
      <el-button text @click="close">查看全部(已在本页)</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { mixApi } from '../../api/mix'

const props = defineProps({
  snap: { type: Object, default: null },
  canOpen: { type: Boolean, default: false },
})
const emit = defineEmits(['open-item'])

const open = ref(false)
const sum = ref(null)
const KEY = 'mix_briefing_seen_' + new Date().toISOString().slice(0, 10)
let fired = false

// 等快照真到位才弹(不用空数据装正常);当天只弹一次
watch(() => props.snap, async (s) => {
  if (fired || !s) return
  fired = true
  try {
    if (localStorage.getItem(KEY)) return
    try { sum.value = await mixApi.automationSummary() } catch (e) {}
    open.value = true
    localStorage.setItem(KEY, '1')
  } catch (e) { /* localStorage 不可用=不弹 */ }
}, { immediate: true })

const items = computed(() => props.snap?.work_items || [])
const topItems = computed(() => {
  const sev = w => (w.severity === 'P0' || w.risk_status?.level === 'P0') ? 0
    : (w.workflow_stage === 'ABNORMAL' || w.blocking_reason) ? 1
      : (w.workflow_stage === 'PENDING_APPROVAL' || w.research_status === 'PENDING') ? 2 : 9
  return items.value.map(w => [sev(w), w]).filter(x => x[0] < 9)
    .sort((a, b) => a[0] - b[0]).slice(0, 3).map(x => x[1])
})
const blockReason = computed(() => props.snap?.blocking_reason || props.snap?.risk_mode || '')
const driftOk = computed(() => {
  const d = sum.value?.release_drift
  return d ? !!d.clean : null
})
const autoText = computed(() => {
  const p = sum.value?.phase_autopilot
  if (!p) return '状态未知'
  const armed = String(p.armed_redis_key) === '1'
  const ts = p.last_log_ts
  let fresh = false
  if (ts) {
    const t = typeof ts === 'number' ? ts * (ts > 2e10 ? 1 : 1000) : Date.parse(ts)
    fresh = t && (Date.now() - t) < 3 * 3600 * 1000
  }
  if (armed && fresh) return '正常(ARMED,近3小时有轮次)'
  if (armed) return 'ARMED 但近3小时无留痕,需关注'
  return '未武装(shadow/暂停)'
})
const autoCls = computed(() => autoText.value.startsWith('正常') ? 'ok' : (autoText.value.includes('需关注') ? 'wn' : 'dim'))
const nextDeadline = computed(() => {
  const ds = items.value.map(w => w.next_deadline).filter(Boolean).sort()
  return ds.length ? String(ds[0]).slice(5, 16) : ''
})

function close () { open.value = false }
function go (w) { close(); emit('open-item', w) }
function goTop () { if (topItems.value[0]) go(topItems.value[0]) }
</script>

<style scoped>
.bd{font-size:13px;color:#B7BDC6}
.fact{display:flex;align-items:baseline;gap:8px;padding:6px 0;border-bottom:1px solid #22262E}
.fact.col{flex-direction:column;align-items:stretch}
.fact i{color:#848E9C;font-style:normal;min-width:96px}
.fact b{color:#EAECEF;font-weight:600}
.fact b.ok{color:#0ECB81}.fact b.bad{color:#F6465D}.fact b.wn{color:#F0B90B}.fact b.dim{color:#848E9C}
.fact b.calm{font-weight:400}
.why{color:#F6465D;font-size:12px}
.tops{margin-top:4px}
.ti{padding:5px 8px;background:#181A20;border:1px solid #2B3139;border-radius:4px;margin-bottom:4px;cursor:pointer}
.ti b{color:#F0B90B}
.ti:hover{border-color:#F0B90B}
</style>
