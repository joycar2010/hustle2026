<template>
  <div class="mob" v-if="authed">
    <!-- STALE 数据中断态(kLzzi):fail-closed 全屏遮罩,不缓存命令 -->
    <div v-if="rs.stale" class="stale">
      <div class="sicon">⛔</div>
      <b>数据中断 · fail-closed</b>
      <p>风险快照超龄或不可达。平板切只读;<br/>不缓存任何命令等待网络恢复后自动执行。</p>
      <p class="dim2">最后策略版本 e{{ rs.policy_epoch ?? '—' }}·v{{ rs.policy_version ?? '—' }}</p>
      <button class="mbtn" @click="load">重试连接</button>
    </div>

    <!-- 顶条 + VenueRisk 摘要条(值守主页固定) -->
    <div class="mtop">
      <b>Mix 值守</b><span class="role">operator_mobile</span>
      <span class="grow" /><span class="dim2">{{ clock }}</span>
    </div>
    <div class="vr" :class="{hot: p0>0}">
      P0/P1 {{ p0 }}/{{ p1 }} · 受限权益 {{ n(rs.restricted_equity_usdt) }}U · 最老提现 {{ rs.oldest_pending?.age_sec ? fmtAge(rs.oldest_pending.age_sec) : '无' }}
      · 受影响持仓 {{ badRows.length }} · 模式 {{ rs.worst_mode || 'N/A' }}
    </div>

    <!-- ① 待办(i85Td2 值守主页) -->
    <div class="body" v-show="tab==='todo'">
      <div class="mcard" v-for="(t,i) in todoAll" :key="i" :class="t.pri">
        <span class="pri" :class="t.pri">{{ t.pri.toUpperCase() }}</span>
        <div class="tt"><b>{{ t.title }}</b><div class="dim2">{{ t.sub }}</div></div>
      </div>
      <div v-if="!todoAll.length" class="empty">无待办 · Incident 全清</div>
    </div>

    <!-- ② 持仓(rc9an 组合详情=点行展开;F5tIL 平仓两步确认=预演) -->
    <div class="body" v-show="tab==='pos'">
      <div class="mcard col" v-for="(r,i) in pf.rows || []" :key="i" @click="exp = exp===i ? -1 : i">
        <div class="row1"><b>{{ r.symbol }}</b><i class="pb">{{ r.product }}</i>
          <span class="grow" /><span :class="r.recon==='ok' ? 'ok2' : 'bad2'">{{ r.recon==='ok' ? '✓' : '⚠' }}</span></div>
        <div class="dim2">{{ r.route }} · {{ r.saga_state }} · Δ {{ r.net_delta_usdt ?? 'N/A' }}U · 缓冲 {{ r.margin_buffer != null ? r.margin_buffer + '%' : 'N/A' }}</div>
        <div v-if="exp===i" class="det">
          <div v-for="(lg,j) in r.legs" :key="j" class="dim2">{{ lg.venue }} {{ (lg.amt||0)>=0?'多':'空' }} {{ lg.amt }} · upnl {{ lg.upnl ?? 'N/A' }}</div>
          <div class="two" v-if="closing!==i">
            <button class="mbtn w" @click.stop="closing=i">平组合…(两步确认)</button>
          </div>
          <div class="two" v-else>
            <div class="preq">
              <b>第1步 · 预演报价</b>
              <div class="dim2">两腿实时报价/费用/预计滑点/最终净收益 = N/A(预演链下批接入)</div>
            </div>
            <button class="mbtn danger" disabled title="Passkey 审批链下批接入">第2步 · Passkey 确认(未接入)</button>
            <button class="mbtn" @click.stop="closing=-1">放弃</button>
          </div>
        </div>
      </div>
      <div v-if="!(pf.rows||[]).length" class="empty">无在管组合</div>
    </div>

    <!-- ③ 风控 -->
    <div class="body" v-show="tab==='risk'">
      <div class="mcard col" v-for="v in rs.venues || []" :key="v.venue">
        <div class="row1"><b>{{ v.venue }}</b><span class="mch" :class="'m-'+v.mode">{{ v.mode }}</span>
          <span class="grow" /><span class="dim2">{{ n(v.equity) }}U</span></div>
        <div class="dim2">{{ String(v.reason||'').split('|')[0].slice(0,44) }}</div>
      </div>
      <div class="mcard col">
        <div class="row1"><b>NAV</b></div>
        <div class="dim2">账面 {{ n(rs.nav?.accounting_nav_usdt) }} · 风调 {{ n(rs.nav?.risk_adjusted_nav_usdt) }} · 可用 {{ n(rs.nav?.available_equity_usdt) }} U</div>
      </div>
      <button class="mbtn danger w" @click="freeze">冻结新增风险(减险 · 立即)</button>
    </div>

    <!-- ④ 审批(fk5UB:只审桌面 DRY_RUN 通过的 Intent;长按3s→Passkey) -->
    <div class="body" v-show="tab==='appr'">
      <div class="empty">无待审 Intent<br/><span class="dim2">只显示桌面 DRY_RUN 通过的提案(提案链下批);<br/>审批=长按3s→Passkey,平板不能发起新增风险</span></div>
      <div class="mcard col" v-for="o in oppsTop" :key="o.symbol">
        <div class="row1"><b>{{ o.symbol }}</b><i class="pb">C2.H 候选</i>
          <span class="grow" /><span class="dim2">风调E {{ o.risk_adjusted_e_bps }} bps</span></div>
        <div class="dim2">shadow 候选仅供知悉,审批须待 DRY_RUN 链</div>
      </div>
    </div>

    <!-- ⑤ 更多(Q4Bonj 角色与安全) -->
    <div class="body" v-show="tab==='more'">
      <div class="mcard col"><b>角色 operator_mobile</b>
        <div class="dim2" style="margin-top:6px">✅ 允许:查看限制原因与账户事实 / 确认 Incident / 冻结新增风险 / 审批已 DRY_RUN 的减仓与 RescueHedge / 查看客服记录与证据包状态</div>
        <div class="dim2" style="margin-top:6px">⛔ 禁止:恢复 NORMAL / 改 venue 上限·条款·mandate / 新建 API·换 IP·调拨·提现 / 在受限平台创建任何增加风险的订单</div>
      </div>
      <div class="mcard col"><b>安全</b>
        <div class="dim2" style="margin-top:6px">审批与平仓确认=Passkey(WebAuthn);数据 stale 或 C 不可达时全端只读;命令绝不离线缓存。</div>
      </div>
      <a class="mbtn w" href="/mix/dashboard" style="text-align:center;text-decoration:none">→ 桌面主控台</a>
    </div>

    <!-- 底部五页签 -->
    <div class="tabs">
      <div v-for="t in TABS" :key="t.k" class="tb" :class="{on: tab===t.k}" @click="tab=t.k">
        <span class="ti">{{ t.i }}</span>{{ t.t }}
        <i v-if="t.k==='todo' && todoAll.length" class="dot">{{ todoAll.length }}</i>
      </div>
    </div>
  </div>
  <div v-else class="gate">平板值守终端<br/><small>URL 需携带 ?token=(operator_mobile 令牌)</small></div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { mixApi } from '../../api/mix'

const route = useRoute()
const authed = ref(!!route.query.token || !!localStorage.getItem('mix_token'))
if (route.query.token) localStorage.setItem('mix_token', String(route.query.token))

const TABS = [{ k: 'todo', t: '待办', i: '◉' }, { k: 'pos', t: '持仓', i: '▤' },
  { k: 'risk', t: '风控', i: '⛨' }, { k: 'appr', t: '审批', i: '✓' }, { k: 'more', t: '更多', i: '⋯' }]
const tab = ref('todo'); const rs = ref({ stale: true }); const pf = ref({}); const opps = ref([])
const exp = ref(-1); const closing = ref(-1); const clock = ref('')
let t1 = null; let t2 = null
const p0 = computed(() => (rs.value.incidents || []).filter(i => i.severity === 'fatal').length + badRows.value.length)
const p1 = computed(() => (rs.value.incidents || []).filter(i => i.severity !== 'fatal').length)
const badRows = computed(() => (pf.value.rows || []).filter(r => r.recon !== 'ok'))
const oppsTop = computed(() => (opps.value || []).filter(o => !o.blocked).slice(0, 3))
const todoAll = computed(() => {
  const out = []
  ;(rs.value.incidents || []).forEach(i => out.push({ pri: i.severity === 'fatal' ? 'p0' : 'p1',
    title: `${i.venue} ${i.title}`, sub: (i.detail || '').slice(0, 60) }))
  badRows.value.forEach(r => out.push({ pri: 'p0', title: `${r.symbol} 残腿`, sub: '单腿裸露,桌面屏3处置' }))
  oppsTop.value.forEach(o => out.push({ pri: 'p2', title: `提案 ${o.symbol} 风调E ${o.risk_adjusted_e_bps}bps`, sub: '审批待 DRY_RUN 链' }))
  return out
})
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
const fmtAge = s => (s >= 3600 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 60) + 'm')
async function load() {
  try {
    rs.value = await mixApi.riskSummary()
    pf.value = await mixApi.riskPortfolio()
    opps.value = (await mixApi.riskOpportunities())?.candidates || []
  } catch (e) { rs.value = { ...rs.value, stale: true } }
}
async function freeze() {
  try {
    await ElMessageBox.confirm('全局追加 NO_NEW_RISK(减险,立即)?恢复须桌面显式 NORMAL 覆盖+审计', '冻结新增风险', { type: 'warning' })
    await mixApi.riskOverrideAdd({ scope_type: 'GLOBAL', scope_key: 'GLOBAL', mode: 'NO_NEW_RISK', reason: '平板值守冻结' })
    ElMessage.success('已冻结,≤30s 生效'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
onMounted(() => { load(); t1 = setInterval(load, 12000)
  const tick = () => { clock.value = new Date().toTimeString().slice(0, 8) }; tick(); t2 = setInterval(tick, 1000) })
onUnmounted(() => { t1 && clearInterval(t1); t2 && clearInterval(t2) })
</script>

<style scoped lang="scss">
.mob { min-height: 100vh; background: var(--mix-bg, #0B0E11); color: var(--mix-t2, #848E9C);
  display: flex; flex-direction: column; max-width: 834px; margin: 0 auto; position: relative; font-size: 13px; }
.gate { min-height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center;
  background: #0B0E11; color: #848E9C; font-size: 15px; }
.stale { position: fixed; inset: 0; z-index: 50; background: rgba(11,14,17,.96); display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px; text-align: center; color: var(--mix-t1, #EAECEF);
  .sicon { font-size: 40px; } p { color: var(--mix-t2, #848E9C); font-size: 12.5px; margin: 0; line-height: 1.7; } }
.mtop { display: flex; align-items: center; gap: 10px; padding: 12px 16px 8px;
  b { color: var(--mix-t1, #EAECEF); font-size: 16px; } }
.role { font-size: 10px; background: rgba(74,156,255,.14); color: #4A9CFF; border-radius: 4px; padding: 1px 8px; }
.grow { flex: 1; }
.dim2 { color: var(--mix-t3, #5E6673); font-size: 11px; }
.vr { margin: 0 16px 8px; padding: 8px 12px; border-radius: 8px; font-size: 11.5px;
  background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  &.hot { border-color: rgba(246,70,93,.45); color: #F6465D; } }
.body { flex: 1; overflow-y: auto; padding: 4px 16px 84px; display: flex; flex-direction: column; gap: 8px; }
.mcard { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px;
  padding: 11px 13px; display: flex; gap: 10px; align-items: flex-start;
  &.col { flex-direction: column; gap: 4px; }
  &.p0 { border-color: rgba(246,70,93,.4); }
  b { color: var(--mix-t1, #EAECEF); } }
.row1 { display: flex; align-items: center; gap: 8px; width: 100%; }
.pri { flex: none; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px;
  &.p0 { background: rgba(246,70,93,.16); color: #F6465D; }
  &.p1 { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.p2 { background: rgba(74,156,255,.14); color: #4A9CFF; } }
.pb { font-style: normal; font-size: 9.5px; font-weight: 800; padding: 1px 6px; border-radius: 3px;
  background: rgba(240,185,11,.14); color: #F0B90B; }
.ok2 { color: #0ECB81; } .bad2 { color: #F6465D; }
.det { width: 100%; border-top: 1px dashed var(--mix-border, #262B33); padding-top: 6px; display: flex; flex-direction: column; gap: 4px; }
.two { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.preq { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 8px 10px;
  b { font-size: 11.5px; } }
.mbtn { border: 1px solid var(--mix-border, #262B33); background: var(--mix-card2, #1E2329); color: var(--mix-t1, #EAECEF);
  border-radius: 8px; padding: 10px 14px; font-size: 12.5px; cursor: pointer;
  &.w { width: 100%; }
  &.danger { border-color: rgba(246,70,93,.5); color: #F6465D; background: rgba(246,70,93,.08); }
  &:disabled { opacity: .5; } }
.mch { font-size: 10px; font-weight: 800; padding: 1px 7px; border-radius: 4px; }
.m-NORMAL { background: rgba(14,203,129,.12); color: #35b57c; }
.m-WATCH { background: rgba(240,185,11,.14); color: #F0B90B; }
.m-NO_NEW_RISK { background: rgba(255,138,61,.16); color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { background: rgba(246,70,93,.16); color: #F6465D; }
.m-FROZEN { background: #8B1E2D; color: #fff; }
.empty { text-align: center; padding: 26px 0; color: var(--mix-t3, #5E6673); font-size: 12.5px; line-height: 1.8; }
.tabs { position: fixed; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 834px;
  display: flex; background: var(--mix-panel, #12151A); border-top: 1px solid var(--mix-border, #262B33); z-index: 40; }
.tb { flex: 1; text-align: center; padding: 10px 0 12px; font-size: 11px; color: var(--mix-t3, #5E6673);
  display: flex; flex-direction: column; gap: 2px; align-items: center; cursor: pointer; position: relative;
  .ti { font-size: 16px; }
  &.on { color: #F0B90B; } }
.dot { position: absolute; top: 6px; right: 24%; font-style: normal; background: #F6465D; color: #fff;
  font-size: 9px; border-radius: 8px; padding: 0 5px; }
</style>
