<template>
  <div class="riskbar" :class="{ stale: d.stale }">
    <!-- 行1(设计qx5QC):环境章+平台模式+三源新鲜度+策略页签(权威状态点)+工作区页签+操作员+时钟+冻结 -->
    <div class="r1">
      <span class="envchip prod">PROD</span>
      <span class="envchip">CORE_POOL</span>
      <span class="maintchip" :class="maintCls" :title="maint.banner || ''" @click="$router.push('/mix/maintenance')">
        网站维护 {{ maintLabel }}</span>
      <span class="modechip" :class="modeCls(d.worst_mode)">
        平台模式 {{ d.worst_mode || 'STALE' }}<i v-if="d.worst_mode==='NORMAL'">·已核验</i>
        <i v-else-if="d.stale">·数据超龄 fail-closed</i>
      </span>
      <span class="kv">行情 <b>N/A</b> · 账本 <b :class="{bad: d.stale}">{{ d.age_sec == null ? 'N/A' : d.age_sec + 's' }}</b> · 三源对账 <b>N/A</b></span>
      <span class="sep">┃</span>
      <span class="kv dim2">策略</span>
      <span v-for="s in stratTabs" :key="s.code" class="stag" :class="{off: s.dot==='off'}"
            :title="`${s.code} ${s.name} · ${s.modeText}`" @click="$router.push('/mix/strategy/'+s.code)">
        <i class="dot" :class="s.dot"></i>{{ s.ccode }}
      </span>
      <span class="sep">┃</span>
      <span class="wtab" :class="{on: tab==='lab'}" @click="openWall('market')">机会与LAB</span>
      <span class="wtab" :class="{on: tab==='exec'}" @click="$router.push('/mix/dashboard')">持仓与执行</span>
      <span class="wtab" :class="{on: tab==='risk'}" @click="$router.push('/mix/venuerisk')">风控与账务</span>
      <span class="grow" />
      <span class="kv"><FIcon name="gear" :size="12"/> <b>{{ opName }}</b></span>
      <span class="kv clock"><b>{{ clock }}</b></span>
      <el-button size="small" type="danger" plain @click="freezeAll">冻结新增风险</el-button>
    </div>
    <!-- 行2:七项风险摘要 + 受限venue文字告示(V5 §14.1) -->
    <div class="r2">
      <span class="p0chip" :class="{hot: p0Count>0}">P0待办 <b>{{ p0Count }}</b></span>
      <span class="item">受限账户 <b :class="{bad: d.restricted_accounts>0}">{{ n(d.restricted_accounts) }}</b></span>
      <span class="item">受限权益 <b :class="{bad: d.restricted_equity_usdt>0}">{{ n(d.restricted_equity_usdt) }}U</b></span>
      <span class="item">风险调整可用权益 <b>{{ n(d.nav?.available_equity_usdt) }}U</b></span>
      <span class="item">NAV折价 <b :class="{bad: (d.nav?.trapped_usdt||0)>0}">{{ n(d.nav?.trapped_usdt) }}U</b></span>
      <span class="item">最老pending提现 <b :class="{bad: (d.oldest_pending?.age_sec||0)>21600}">
        {{ d.oldest_pending?.age_sec ? fmtAge(d.oldest_pending.age_sec) + '·' + d.oldest_pending.venue : '无' }}</b></span>
      <span class="item">24h提现成功率 <b>{{ d.wd_24h?.rate == null ? 'N/A(无样本)' : d.wd_24h.rate + '%' }}</b></span>
      <span class="item">未复核条款 <b :class="{warn2: (d.unreviewed_terms||[]).length>0}">{{ (d.unreviewed_terms||[]).length }}</b></span>
      <span class="item">最高Incident <b :class="{bad: !!d.top_incident}">{{ d.top_incident ? d.top_incident.venue + '·' + d.top_incident.title : '无' }}</b></span>
      <span v-if="notice" class="notice" :class="modeCls(notice.mode)">
        {{ notice.venue }} · {{ notice.mode }} — {{ short(notice.reason) }} · 暴露 {{ n(notice.equity) }}U · 新开仓已禁止
      </span>
      <span class="grow" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../api/mix'
import { STRATEGY_META as META } from '../components/PositionTable/types'

const d = ref({ stale: true })
const maint = ref({ state: 'NORMAL' })
const strats = ref([])
const M_LABEL = { NORMAL: '正常', ANNOUNCED: '已公告', DRAINING: '排空中', DRAIN_BLOCKED: '排空受阻', MAINTENANCE: '维护中', RECOVERY_CHECK: '恢复检查' }
const maintLabel = computed(() => M_LABEL[maint.value.state] || maint.value.state)
const maintCls = computed(() => ({ NORMAL: 'ok', ANNOUNCED: 'watch', DRAINING: 'nonew',
  DRAIN_BLOCKED: 'red', MAINTENANCE: 'red', RECOVERY_CHECK: 'recov' }[maint.value.state] || 'ok'))
const opName = ref('operator')
const clock = ref('')
let timer = null; let clkTimer = null
const route = useRoute()
const tab = computed(() => (route.path.includes('venuerisk') || route.path.includes('venue/') ? 'risk'
  : route.path.includes('dashboard') || route.path.includes('slots') ? 'exec' : ''))
const SEV = { FROZEN: 6, QUARANTINED: 6, EXIT_ONLY: 5, REDUCE_ONLY: 4, NO_NEW_RISK: 3 }
const notice = computed(() => (d.value.venues || []).filter(v => SEV[v.mode])[0] || null)
const p0Count = computed(() => (d.value.incidents || []).filter(i => i.severity === 'fatal').length
  + (d.value.restricted_accounts || 0) + ((d.value.nav?.trapped_usdt || 0) > 0 ? 1 : 0))
// 策略页签权威状态点:●=armed会真实下单 ○=SHADOW不下单 –=未启用(设计规约:一个策略一个权威状态)
const stratTabs = computed(() => strats.value.map(s => ({
  code: s.code, name: s.name, ccode: META[s.code]?.ccode || s.code,
  dot: s.mode === 'armed' ? 'armed' : s.mode === 'shadow' ? 'shadow' : 'off',
  modeText: s.mode === 'armed' ? '● 会真实下单' : s.mode === 'shadow' ? '○ SHADOW·不下单' : '未启用',
})))
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
const short = s => String(s || '').split('|')[0].slice(0, 42)
const fmtAge = s => (s >= 3600 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 60) + 'm')
const modeCls = m => ({ NORMAL: 'ok', WATCH: 'watch', NO_NEW_RISK: 'nonew', REDUCE_ONLY: 'red',
  EXIT_ONLY: 'red', FROZEN: 'quar', QUARANTINED: 'quar', RECOVERY_WATCH: 'recov' }[m] || 'unknown')

function openWall(w) { window.open(`/wall/${w}?token=${localStorage.getItem('mix_token') || ''}`) }
async function load() {
  try { d.value = await mixApi.riskSummary() } catch (e) { d.value = { stale: true } }
  try { strats.value = await mixApi.strategies() } catch (e) { /* 页签降级 */ }
  try { maint.value = await mixApi.maintStatus() } catch (e) { /* */ }
}
async function freezeAll() {
  try {
    await ElMessageBox.confirm('对全局追加 NO_NEW_RISK 覆盖(减险动作,立即生效;恢复须显式 NORMAL 覆盖+审计)?', '冻结新增风险', { type: 'warning', confirmButtonText: '冻结' })
    await mixApi.riskOverrideAdd({ scope_type: 'GLOBAL', scope_key: 'GLOBAL', mode: 'NO_NEW_RISK', reason: '操作员手动冻结(状态条)' })
    ElMessage.success('已追加全局 NO_NEW_RISK,risk-ledger ≤30s 合并生效')
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '失败') }
}
function tick() {
  const dd = new Date()
  clock.value = dd.toTimeString().slice(0, 8) + ' UTC' + (dd.getTimezoneOffset() <= 0 ? '+' : '-') + Math.abs(dd.getTimezoneOffset() / 60)
}
onMounted(async () => {
  load(); timer = setInterval(load, 10000); tick(); clkTimer = setInterval(tick, 1000)
  try { const w = await mixApi.whoami(); opName.value = 'operator@' + (w?.operator || w?.username || 'ops') } catch (e) { /* 保持默认 */ }
})
onUnmounted(() => { timer && clearInterval(timer); clkTimer && clearInterval(clkTimer) })
</script>

<style scoped lang="scss">
/* V5 §14.7 模式色规范;禁止只用颜色表状态,全部配文字 */
.riskbar { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  border-radius: 8px; padding: 6px 12px; display: flex; flex-direction: column; gap: 5px;
  &.stale { border-color: #5E6673; } }
.r1, .r2 { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 11.5px; color: var(--mix-t2, #848E9C); min-width: 0; }
.grow { flex: 1; }
.sep { color: var(--mix-border, #262B33); }
.envchip { font-weight: 800; font-size: 10.5px; padding: 1px 8px; border-radius: 4px;
  background: rgba(94,102,115,.18); color: var(--mix-t1, #EAECEF);
  &.prod { background: rgba(246,70,93,.16); color: #F6465D; } }
.maintchip { font-weight: 800; font-size: 11.5px; padding: 2px 9px; border-radius: 5px; cursor: pointer;
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.watch { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.nonew { background: rgba(255,138,61,.16); color: #FF8A3D; }
  &.red { background: rgba(246,70,93,.16); color: #F6465D; }
  &.recov { background: rgba(140,163,199,.16); color: #8CA3C7; } }
.modechip { font-weight: 800; font-size: 12px; padding: 2px 10px; border-radius: 5px;
  i { font-style: normal; font-weight: 500; opacity: .85; }
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.watch { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.nonew { background: rgba(255,138,61,.16); color: #FF8A3D; }
  &.red { background: rgba(246,70,93,.16); color: #F6465D; }
  &.quar { background: #8B1E2D; color: #fff; }
  &.recov { background: rgba(140,163,199,.16); color: #8CA3C7; }
  &.unknown { background: rgba(94,102,115,.2); color: #9aa4b2; } }
.stag { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 4px;
  border: 1px solid var(--mix-border, #262B33); cursor: pointer; font-size: 10.5px; color: var(--mix-t1, #EAECEF);
  &.off { color: var(--mix-t3, #5E6673); }
  &:hover { border-color: #F0B90B66; } }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block;
  &.armed { background: #0ECB81; }
  &.shadow { background: transparent; border: 1.5px solid #4A9CFF; }
  &.off { background: transparent; border: 1.5px solid #5E6673; } }
.wtab { padding: 2px 10px; border-radius: 5px; cursor: pointer; font-size: 11.5px; color: var(--mix-t2, #848E9C);
  &.on { background: rgba(240,185,11,.15); color: #F0B90B; font-weight: 700; }
  &:hover { color: var(--mix-t1, #EAECEF); } }
.dim2 { color: var(--mix-t3, #5E6673); }
.clock b { font-variant-numeric: tabular-nums; }
.p0chip { font-weight: 800; font-size: 12px; padding: 2px 10px; border-radius: 5px;
  background: rgba(94,102,115,.18); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); }
  &.hot { background: rgba(246,70,93,.18); color: #F6465D; b { color: #F6465D; } } }
.kv b, .item b { color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums;
  &.bad { color: #F6465D; } &.warn2 { color: #F0B90B; } }
.notice { font-weight: 700; padding: 2px 10px; border-radius: 5px; max-width: 40%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.more { font-size: 11.5px; }
</style>
