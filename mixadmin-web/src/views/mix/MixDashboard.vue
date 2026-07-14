<template>
  <div class="mixdash">
    <!-- 设计宪法:tlOCA 单屏版V2。数据不够的格子写 N/A,绝不改格子。 -->
    <RiskStatusBar />

    <!-- 组合安全摘要八卡(g2u09e) -->
    <div class="sumrow">
      <div v-for="c in sumCards" :key="c.k" class="scard" :class="c.cls">
        <span class="sk">{{ c.k }}</span>
        <b class="sv" :class="c.vc">{{ c.v }}</b>
        <span class="sn" :class="c.nc">{{ c.note }}</span>
      </div>
    </div>

    <!-- 中段:待办队列(P0/P1/P2 分级) | 异常/Saga(G05EKu) -->
    <div class="midrow">
      <div class="card todo">
        <div class="chd">待办队列 <span class="dimtxt">现在必须处理什么</span>
          <span class="grow" />
          <span class="cnt p0">P0 {{ todo.p0.length }}</span>
          <span class="cnt p1">P1 {{ todo.p1.length }}</span>
          <span class="cnt p2">P2 {{ todo.p2.length }}</span>
        </div>
        <div class="tlist">
          <div v-if="!todo.p0.length && !todo.p1.length && !todo.p2.length" class="dimtxt pad">无待办(Incident 全清 · 无提案)</div>
          <div v-for="(t,i) in todo.p0" :key="'p0'+i" class="tline">
            <span class="pri p0">P0·{{ t.tag }}</span><b>{{ t.title }}</b><span class="dimtxt">{{ t.sub }}</span>
            <span class="grow" /><span class="dimtxt">{{ t.age }}</span>
            <el-button size="small" type="danger" plain @click="$router.push('/mix/venuerisk')">去紧急处置 →</el-button>
          </div>
          <div v-for="(t,i) in todo.p1" :key="'p1'+i" class="tline">
            <span class="pri p1">P1·{{ t.tag }}</span><b>{{ t.title }}</b><span class="dimtxt">{{ t.sub }}</span>
            <span class="grow" /><span class="dimtxt">{{ t.age }}</span>
            <el-button size="small" text @click="$router.push('/mix/venuerisk')">查看</el-button>
          </div>
          <div v-for="(t,i) in todo.p2" :key="'p2'+i" class="tline">
            <span class="pri p2">P2·提案</span><b>{{ t.title }}</b><span class="dimtxt">{{ t.sub }}</span>
            <span class="grow" />
            <el-button size="small" text @click="openWall()">审批…</el-button>
          </div>
        </div>
        <div class="cfoot bordered">新增风险路径:DRY_RUN → COOLDOWN → WebAuthn/TOTP → ACTIVE ｜ 减仓/撤单/冻结新增/残腿收敛:立即执行</div>
      </div>
      <div class="card saga">
        <div class="chd">异常 / Saga <span class="grow" /><span class="dimtxt">双腿执行状态</span></div>
        <div class="tlist">
          <div v-if="!sagaRows.length" class="dimtxt pad">无进行中 Saga / 修复意图</div>
          <div v-for="(sg,i) in sagaRows" :key="i" class="sgline">
            <b :class="{bad: sg.bad}">{{ sg.symbol }}</b> · <span class="dimtxt">{{ sg.kind }}</span>
            <div class="steps">
              <span v-for="(st,j) in sg.steps" :key="j" class="step" :class="st.cls">{{ j+1 }} {{ st.t }}</span>
            </div>
          </div>
          <div v-if="pf.repair?.intents?.length" class="rescue">
            <b>修复意图</b>
            <span v-for="it in pf.repair.intents" :key="it.intent_id" class="dimtxt">
              {{ it.kind }} {{ it.symbol }}→撤出{{ it.venue }}(est {{ it.est_notional_usdt }}U,shadow)</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 生产持仓(WhJIi 十二列;一行=一个经济组合,点击展开) -->
    <div class="card poscard">
      <div class="chd">生产持仓 <span class="dimtxt">一行=一个经济组合 · 点击展开交易腿</span>
        <span class="grow" /><span class="dimtxt">口径:净PnL = Funding + Basis − Fee − Slippage(费后·含未实现)</span></div>
      <div class="ptbl">
        <div class="phead">
          <span class="c ow">OWNER</span><span class="c pd">产品</span><span class="c sy">标的</span>
          <span class="c rt">路由</span><span class="c sg">Saga状态</span><span class="c cf">下一现金流</span>
          <span class="c pn">净PnL</span><span class="c dl">净Delta</span><span class="c mb">保证金缓冲</span>
          <span class="c xc">退出成本</span><span class="c rc">RECON</span><span class="c op2">操作</span>
        </div>
        <div v-if="!pf.rows?.length" class="dimtxt pad">无在管组合(exec-manager 空配置)</div>
        <template v-for="(r,i) in pf.rows" :key="i">
          <div class="prow2" :class="{bad: r.recon!=='ok', open: expanded===i}" @click="expanded = expanded===i ? -1 : i">
            <span class="c ow">{{ r.owner }}</span>
            <span class="c pd"><i class="pbadge">{{ r.product }}</i></span>
            <span class="c sy"><b>{{ r.symbol }}</b></span>
            <span class="c rt">{{ r.route }}</span>
            <span class="c sg"><i class="sdot" :class="sagaCls(r)"></i>{{ sagaText(r) }}</span>
            <span class="c cf">{{ r.next_cashflow ? '净差 ' + r.next_cashflow.net_daily_pct + '%/d' : 'N/A' }}</span>
            <span class="c pn">{{ r.net_pnl == null ? 'N/A' : r.net_pnl + ' U' }}</span>
            <span class="c dl" :class="{ok: Math.abs(r.net_delta_usdt||0) < 25}">{{ r.net_delta_usdt == null ? 'N/A' : (r.net_delta_usdt>=0?'+':'') + r.net_delta_usdt + ' U' }}</span>
            <span class="c mb">{{ r.margin_buffer == null ? 'N/A' : r.margin_buffer }}</span>
            <span class="c xc">{{ r.exit_cost == null ? 'N/A' : r.exit_cost }}</span>
            <span class="c rc" :class="{bad: r.recon!=='ok'}">{{ r.recon==='ok' ? '✓ 0 差异' : '⚠ ' + r.recon }}</span>
            <span class="c op2"><el-button size="small" text @click.stop="$router.push('/mix/strategies')">详情</el-button></span>
          </div>
          <div v-if="expanded===i" class="drawer">
            <div class="dcol">
              <div class="dh">腿明细</div>
              <div v-for="(lg,j) in r.legs" :key="j" class="dline">
                <b>{{ lg.venue }}</b> {{ (lg.amt||0) >= 0 ? '多' : '空' }} {{ lg.amt }}
                <span class="dimtxt"> mark {{ lg.mark ?? 'N/A' }} · venue {{ lg.mode ?? 'N/A' }}</span>
              </div>
            </div>
            <div class="dcol">
              <div class="dh">FUNDING 现金流</div>
              <div class="dline">{{ r.next_cashflow ? '本组合净差 ' + r.next_cashflow.net_daily_pct + '%/d(空腿收−多腿付)' : 'N/A(资金费日历待接)' }}</div>
              <div class="dh">净收益拆分(开仓以来)</div>
              <div class="dline dimtxt">Funding N/A · Basis N/A · Fee N/A · Slippage N/A(逐组合账本待接)</div>
            </div>
            <div class="dcol">
              <div class="dh">退出 & THESIS</div>
              <div class="dline dimtxt">退出深度/预计滑点 N/A ｜ 信号:{{ r.signal || 'N/A' }}</div>
              <div class="dline"><el-button size="small" plain disabled title="两步确认流程接入中">平仓…(两步确认:两腿报价+费用+滑点+净收益)</el-button></div>
            </div>
          </div>
        </template>
      </div>
      <div class="cfoot bordered">平仓统一两步确认,提交前展示两腿实时报价/费用/预计滑点/最终净收益 ｜ 单腿操作仅在「风控与账务」紧急残腿处理 ｜ 数据缺失一律显示 N/A,绝不使用哨兵值</div>
    </div>

    <!-- 通过硬闸的机会 · Top10(z5ijRp) -->
    <div class="card opprow">
      <div class="chd">通过硬闸的机会 · Top {{ opps.length }}
        <span class="dimtxt">硬闸 = 风调E>0 · 数据新鲜 · 容量>0 ｜ shadow 候选</span>
        <span class="grow" />
        <el-link @click="openWall()">其余 {{ oppSkipped }} 个候选 → 机会台(屏1·机会与LAB)→</el-link>
      </div>
      <div class="oppstrip">
        <div v-if="!opps.length" class="dimtxt pad">本轮无过闸候选</div>
        <div v-for="o in opps" :key="o.symbol" class="opp" :class="{blocked: o.blocked}">
          <div class="ohd"><b class="osym">{{ o.symbol }}</b><i class="pbadge">C2.H</i></div>
          <b class="obps" :class="(o.risk_adjusted_e_bps??0)>0 ? 'up' : 'down'">
            {{ o.risk_adjusted_e_bps != null ? (o.risk_adjusted_e_bps>0?'+':'') + o.risk_adjusted_e_bps + ' bps' : 'N/A' }}</b>
          <span class="dimtxt">{{ o.venue_long }}⟶{{ o.venue_short }} · 容量 {{ o.target_notional_usdt ?? 'N/A' }}U</span>
          <span class="ogates" v-if="!o.blocked">闸 {{ (o.risk_adjusted_e_bps??0)>0?'✓':'✗' }}E ✓鲜 {{ (o.target_notional_usdt||0)>0?'✓':'✗' }}容 <span class="dimtxt">借N/A</span></span>
          <span class="ogates bad" v-else>⛔ {{ o.venue_long_mode }}/{{ o.venue_short_mode }} 受限·无开仓入口</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const rs = ref({}); const ov = ref({}); const opps = ref([]); const oppSkipped = ref(0)
const pf = ref({}); const expanded = ref(-1)
let t1 = null
const NA = 'N/A'
const fmtAge = s => (s >= 3600 ? Math.floor(s / 3600) + 'h' : Math.floor((s || 0) / 60) + 'm')

// 待办分级:P0=fatal Incident/残腿 · P1=warn Incident · P2=开仓提案(过闸候选)
const todo = computed(() => {
  const inc = rs.value.incidents || []
  const p0 = inc.filter(i => i.severity === 'fatal').map(i => ({
    tag: i.rule === 'policy-mode' ? '受限' : '事件', title: `${i.venue} ${i.title}`,
    sub: (i.detail || '').slice(0, 60), age: '已持续 ' + fmtAge(i.age_sec) }))
  ;(pf.value.rows || []).filter(r => r.recon !== 'ok').forEach(r =>
    p0.push({ tag: '残腿', title: `${r.symbol} ${r.recon}`, sub: '单腿裸露,人工确认后收敛', age: '' }))
  const p1 = inc.filter(i => i.severity !== 'fatal').map(i => ({
    tag: i.rule === 'nav-haircut' ? '账务' : '事件', title: `${i.venue} ${i.title}`,
    sub: (i.detail || '').slice(0, 60), age: fmtAge(i.age_sec) + ' 前' }))
  const p2 = (opps.value || []).filter(o => !o.blocked).slice(0, 2).map(o => ({
    title: `开仓提案 ${o.symbol} C2.H · 风调E ${o.risk_adjusted_e_bps} bps`,
    sub: `建议名义 ${o.target_notional_usdt}U · shadow 候选,审批走 DRY_RUN 链` }))
  return { p0, p1, p2 }
})
// 八卡(宪法:格子=设计稿,数据不够 N/A 绝不换卡)
const sumCards = computed(() => {
  const nav = rs.value.nav || {}
  const vs = rs.value.venues || []
  const notional = vs.length ? vs.reduce((t, v) => t + (v.exposure_notional || 0), 0) : null
  const pnl = ov.value.pnl_today
  const p0 = todo.value.p0.length
  return [
    { k: 'CORE NAV', v: nav.accounting_nav_usdt != null ? Number(nav.accounting_nav_usdt).toLocaleString() + ' U' : NA,
      note: nav.available_equity_usdt != null ? `风调可用 ${nav.available_equity_usdt} U` : NA },
    { k: '今日净PnL(费后)', v: pnl != null ? (pnl >= 0 ? '+' : '') + Number(pnl).toFixed(2) + ' U' : NA,
      vc: pnl >= 0 ? 'up' : 'down', note: 'Funding/Basis/费 拆分 N/A(逐组合账本待接)' },
    { k: '总名义仓位', v: notional != null ? Math.round(notional).toLocaleString() + ' U' : NA,
      note: `${(pf.value.rows || []).length} 组合` },
    { k: '净Delta', v: NA, note: 'BTC当量/bps NAV N/A(净敞口源待接)' },
    { k: '最低保证金缓冲', v: NA, note: '逐组合保证金源待接 · 告警线 25%' },
    { k: 'P0 事件', v: String(p0), vc: p0 ? 'down' : '', cls: p0 ? 'hot' : '',
      note: p0 ? (rs.value.top_incident?.title || '见待办') : '无', nc: p0 ? 'down' : '' },
    { k: 'RECON 差异', v: NA, note: 'R11 逐组合差异表待接(告警在岗)' },
    { k: '下一现金流', v: NA, note: 'funding 结算日历待接' },
  ]
})
// Saga 链:manager 快照行 → 步骤化(数据有多细画多细,缺=进行中,绝不臆造)
const sagaRows = computed(() => (pf.value.rows || [])
  .filter(r => r.saga_state && r.saga_state !== 'hold' && !String(r.saga_state).startsWith('flat'))
  .map(r => ({
    symbol: r.symbol, kind: `${r.product} ${r.target === 'close' ? '平仓' : r.target === 'hold' ? '持有' : ''} Saga`,
    bad: r.recon !== 'ok',
    steps: (r.legs || []).map(lg => ({ t: `${lg.venue}腿 ${Math.abs(lg.amt||0)>1e-9 ? '✓在场' : '—'}`,
      cls: Math.abs(lg.amt||0)>1e-9 ? 'ok' : '' }))
      .concat([{ t: String(r.saga_state).slice(0, 18), cls: r.recon !== 'ok' ? 'bad' : 'run' }]),
  })))
const sagaCls = r => (r.recon !== 'ok' ? 'bad' : r.saga_state === 'hold' ? 'ok' : 'run')
const sagaText = r => (r.recon !== 'ok' ? '补偿·单腿' : r.saga_state === 'hold' ? '● 稳态' : r.saga_state)
function openWall() { window.open(`/wall/market?token=${localStorage.getItem('mix_token') || ''}`) }
async function load() {
  try {
    const [a, b, c, d] = await Promise.all([mixApi.riskSummary(), mixApi.monitor.overview(),
      mixApi.riskOpportunities(), mixApi.riskPortfolio()])
    rs.value = a; ov.value = b; opps.value = (c?.candidates || []).slice(0, 10)
    oppSkipped.value = c?.skipped_count ?? 0; pf.value = d
  } catch (e) { /* 状态条自带 STALE 表达,不装绿 */ }
}
onMounted(() => { load(); t1 = setInterval(load, 10000) })
onUnmounted(() => t1 && clearInterval(t1))
</script>

<style scoped lang="scss">
.mixdash { display: flex; flex-direction: column; gap: 10px; min-height: 100%;
  > .riskbar, > .sumrow, > .midrow, > .opprow { flex: none; }
  > .poscard { flex: 1; min-height: 220px; } }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; padding: 8px 12px; min-width: 0; }
.chd { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.pad { padding: 10px 0; }
.up { color: #0ECB81 !important; } .down { color: #F6465D !important; } .bad { color: #F6465D; } .ok { color: #0ECB81; }

.sumrow { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 8px;
  @media (max-width: 1500px) { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.scard { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  border-radius: 10px; padding: 9px 13px; display: flex; flex-direction: column; gap: 3px; min-width: 0;
  &.hot { border-color: rgba(246,70,93,.45); } }
.sk { font-size: 10.5px; color: var(--mix-t2, #848E9C); }
.sv { font-size: 19px; font-weight: 800; color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; }
.sn { font-size: 9.5px; color: var(--mix-t3, #5E6673); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; &.down { color: #F6465D; } }

/* 竖条bug根治:两列都 minmax(0,·) 锁死,卡 overflow hidden——跑马灯/长内容撑不破列宽 */
.midrow { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 10px; min-height: 200px;
  .card { overflow: hidden; display: flex; flex-direction: column; } }
.tlist { flex: 1; min-height: 0; overflow-y: auto; }
.cnt { font-size: 10px; font-weight: 800; padding: 1px 8px; border-radius: 4px;
  &.p0 { background: rgba(246,70,93,.16); color: #F6465D; }
  &.p1 { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.p2 { background: rgba(74,156,255,.14); color: #4A9CFF; } }
.tline { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--mix-t2, #848E9C);
  padding: 5px 0; border-bottom: 1px dashed var(--mix-border, #262B33);
  b { color: var(--mix-t1, #EAECEF); white-space: nowrap; } }
.pri { flex: none; font-size: 10px; font-weight: 800; padding: 1px 7px; border-radius: 4px;
  &.p0 { background: rgba(246,70,93,.16); color: #F6465D; }
  &.p1 { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.p2 { background: rgba(74,156,255,.14); color: #4A9CFF; } }
.cfoot { font-size: 10px; color: var(--mix-t3, #5E6673);
  &.bordered { border-top: 1px solid var(--mix-border, #262B33); margin-top: 6px; padding-top: 6px; } }
.sgline { padding: 5px 0; border-bottom: 1px dashed var(--mix-border, #262B33); font-size: 11.5px; color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); } }
.steps { display: flex; gap: 6px; margin-top: 3px; flex-wrap: wrap; }
.step { font-size: 10px; padding: 1px 7px; border-radius: 4px; background: rgba(94,102,115,.15); color: var(--mix-t2, #848E9C);
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.run { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.bad { background: rgba(246,70,93,.16); color: #F6465D; } }
.rescue { margin-top: 6px; padding: 6px 8px; border: 1px solid rgba(246,70,93,.3); border-radius: 6px;
  font-size: 10.5px; display: flex; flex-direction: column; gap: 2px;
  b { color: var(--mix-t1, #EAECEF); font-size: 11px; } }

.poscard { display: flex; flex-direction: column; }
.ptbl { flex: 1; min-height: 0; overflow: auto; font-size: 11px; }
.phead, .prow2 { display: grid; align-items: center; min-width: 1180px;
  grid-template-columns: 74px 56px 96px minmax(120px,1.2fr) 110px 128px 92px 130px 92px 78px 100px 84px; }
.phead { color: var(--mix-t3, #5E6673); font-size: 10px; border-bottom: 1px solid var(--mix-border, #262B33);
  padding: 4px 0; position: sticky; top: 0; background: var(--mix-card, #181B21); z-index: 1; }
.prow2 { color: var(--mix-t2, #848E9C); padding: 7px 0; border-bottom: 1px solid var(--mix-border, #262B33);
  cursor: pointer;
  b { color: var(--mix-t1, #EAECEF); }
  &:hover, &.open { background: var(--mix-card2, #1E2329); }
  &.bad { background: rgba(246,70,93,.05); } }
.c { padding: 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbadge { font-style: normal; font-size: 9.5px; font-weight: 800; padding: 1px 6px; border-radius: 3px;
  background: rgba(240,185,11,.14); color: #F0B90B; }
.sdot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px;
  &.ok { background: #0ECB81; } &.run { background: #F0B90B; } &.bad { background: #F6465D; } }
.drawer { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; padding: 10px 16px;
  background: var(--mix-panel, #12151A); border-left: 2px solid #4A9CFF; border-bottom: 1px solid var(--mix-border, #262B33);
  font-size: 11px; color: var(--mix-t2, #848E9C); }
.dh { font-size: 10px; color: var(--mix-t3, #5E6673); margin: 4px 0 2px; font-weight: 700; }
.dline { padding: 2px 0; b { color: var(--mix-t1, #EAECEF); } }

.opprow { min-height: 118px; }
.oppstrip { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.opp { flex: none; width: 172px; background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33);
  border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 3px; font-size: 10.5px;
  color: var(--mix-t2, #848E9C);
  &.blocked { opacity: .55; border-color: rgba(246,70,93,.35); } }
.ohd { display: flex; align-items: center; justify-content: space-between; }
.osym { color: var(--mix-t1, #EAECEF); font-size: 12.5px; }
.obps { font-size: 16px; font-weight: 800; font-variant-numeric: tabular-nums; }
.ogates { font-size: 9.5px; color: var(--mix-t3, #5E6673); &.bad { color: #F6465D; } }
</style>
