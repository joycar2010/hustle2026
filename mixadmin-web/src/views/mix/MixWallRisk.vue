<template>
  <div class="wall3" v-if="authed">
    <RiskStatusBar />
    <div class="main">
      <!-- 列1·保证金与ADL(JyEvC,w560) -->
      <div class="col c1">
        <div class="card">
          <div class="chd2"><b>保证金压力</b><span class="grow" /><span class="dimtxt">逐venue账户</span></div>
          <div class="mhead"><span>账户</span><span class="r">权益U</span><span class="r">敞口U</span><span class="r">距强平%</span><span>模式</span></div>
          <div v-for="v in venues" :key="v.venue" class="mrow" :class="{bad: (minLiq(v.venue) ?? 999) < 25}">
            <span><b>{{ v.venue }}</b> <i class="dimtxt">Tier {{ v.tier || '—' }}</i></span>
            <span class="r">{{ n(v.equity) }}</span>
            <span class="r">{{ n(v.exposure_notional) }}</span>
            <span class="r">{{ minLiq(v.venue) ?? 'N/A' }}</span>
            <span :class="'m-'+v.mode">{{ v.mode }}</span>
          </div>
          <div class="cfoot">距强平=该所持仓腿 dist_liq 最小值 · 告警线 25%</div>
        </div>
        <div class="card">
          <div class="chd2"><b>ADL 面板</b><span class="grow" /><span class="dimtxt">≥4 档预警</span></div>
          <div v-if="!adlRows.length" class="dimtxt pad">无带 ADL 档位的持仓腿</div>
          <div v-for="(a,i) in adlRows" :key="i" class="lrow">
            <b>{{ a.symbol }}</b><span class="dimtxt">{{ a.venue }}</span>
            <span class="grow" />
            <span :class="{bad: a.adl >= 4}">ADL {{ a.adl }}</span>
          </div>
        </div>
        <div class="card fill2">
          <div class="chd2"><b>减险建议</b><span class="grow" /><span class="dimtxt">减险=立即执行类</span></div>
          <div v-if="!suggests.length" class="dimtxt pad">无建议(策略/修复面全静)</div>
          <div v-for="(s2,i) in suggests" :key="i" class="lrow">
            <span class="pri" :class="s2.lvl">{{ s2.tag }}</span><span>{{ s2.txt }}</span>
          </div>
        </div>
      </div>

      <!-- 列2·残腿与RECON(UL4Lb) -->
      <div class="col c2">
        <div class="card urgent" :class="{quiet: !urgentRows.length}">
          <div class="chd2"><b>紧急残腿处理</b><span class="grow" />
            <span class="cnt" :class="urgentRows.length ? 'p0' : 'okc'">{{ urgentRows.length }}</span></div>
          <div v-if="!urgentRows.length" class="dimtxt pad">无残腿 · 全组合两腿对称</div>
          <div v-for="(u,i) in urgentRows" :key="i" class="ulist">
            <b class="bad">{{ u.symbol }}</b> {{ u.recon }}
            <div class="dimtxt">单腿操作唯一入口:此处确认方向后收敛;绝不在持仓表行内平单腿</div>
          </div>
        </div>
        <div class="card fill2">
          <div class="chd2"><b>RECON 对账</b><span class="grow" /><span class="dimtxt">期望腿 vs 实盘快照</span></div>
          <div class="mhead"><span>组合</span><span>产品</span><span class="r">净Delta U</span><span>状态</span></div>
          <div v-for="(r,i) in pfRows" :key="i" class="mrow" :class="{bad: r.recon!=='ok'}">
            <span><b>{{ r.symbol }}</b></span>
            <span><i class="pbadge">{{ r.product }}</i></span>
            <span class="r">{{ r.net_delta_usdt ?? 'N/A' }}</span>
            <span :class="r.recon==='ok' ? 'up' : 'bad'">{{ r.recon==='ok' ? '✓ 0差异' : '⚠ '+r.recon }}</span>
          </div>
          <div v-if="!pfRows.length" class="dimtxt pad">无在管组合</div>
        </div>
        <div class="card">
          <div class="chd2"><b>冻结与干预历史</b><span class="grow" /><span class="dimtxt">模式转变(近10)</span></div>
          <div v-if="!transitions.length" class="dimtxt pad">无记录</div>
          <div v-for="(t,i) in transitions.slice(0,10)" :key="i" class="lrow">
            <b>{{ t.venue }}</b>
            <span class="mch sm" :class="'m2-'+t.before_mode">{{ t.before_mode }}</span>→
            <span class="mch sm" :class="'m2-'+t.after_mode">{{ t.after_mode }}</span>
            <span class="dimtxt">{{ String(t.reason||'').split('|')[0].slice(0,30) }} · {{ (t.recorded_at||'').slice(5,16) }}</span>
          </div>
        </div>
      </div>

      <!-- 列3·NAV与资金(u8ld44,w500) -->
      <div class="col c3">
        <div class="card">
          <div class="chd2"><b>NAV bridge</b><span class="grow" /><span class="dimtxt">三口径分离</span></div>
          <div class="kv"><span>Accounting NAV(账面)</span><b>{{ n(nav.accounting_nav_usdt) }} U</b></div>
          <div class="kv"><span>− 情景 haircut(受限折价)</span><b :class="{bad:(nav.trapped_usdt||0)>0}">{{ n(nav.trapped_usdt) }} U</b></div>
          <div class="kv"><span>= Risk-adjusted NAV</span><b>{{ n(nav.risk_adjusted_nav_usdt) }} U</b></div>
          <div class="kv"><span>− 保证金预留</span><b>{{ n(nav.reservation_usdt) }} U</b></div>
          <div class="kv"><span>− 运营缓冲</span><b>{{ n(nav.operational_buffer_usdt) }} U</b></div>
          <div class="kv tot"><span>= Available Equity(可部署)</span><b>{{ n(nav.available_equity_usdt) }} U</b></div>
          <div class="cfoot">同一笔 trapped 只扣一次;冻结资产不删除只折价(V5 §11.2)</div>
        </div>
        <div class="card">
          <div class="chd2"><b>逐所权益</b></div>
          <div v-for="v in venues" :key="v.venue" class="lrow">
            <b>{{ v.venue }}</b>
            <span class="grow" />
            <span :class="{bad: (v.trapped_usdt||0)>0}">{{ n(v.equity) }} U{{ (v.trapped_usdt||0)>0 ? ` (折价 ${v.trapped_usdt})` : '' }}</span>
          </div>
        </div>
        <div class="card fill2">
          <div class="chd2"><b>资金流水</b><span class="grow" /><span class="dimtxt">提现事实(近20)</span></div>
          <div v-if="!flows.length" class="dimtxt pad">窗口内无提现记录</div>
          <div v-for="(f,i) in flows" :key="i" class="lrow">
            <b>{{ f.venue }}</b><span>{{ f.asset }} {{ f.amount }}</span>
            <span class="mch sm" :class="f.status==='CONFIRMED' ? 'okc2' : f.status==='PENDING' ? 'pend' : 'failc'">{{ f.status }}</span>
            <span class="grow" /><span class="dimtxt">{{ (f.initiated_at||'').slice(5,16) }}</span>
          </div>
          <div class="cfoot">允许动作=查事实/停新增/工单/标审核/证据包;禁止重复提现/换IP重试(V5 §14.4)</div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="gate">屏3 · 风控与账务<br /><small>URL 需携带 ?token=(只读墙令牌,后端校验)</small></div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const route = useRoute()
const authed = ref(!!route.query.token || !!localStorage.getItem('mix_token'))
if (route.query.token) localStorage.setItem('mix_token', String(route.query.token))

const rs = ref({}); const pf = ref({}); const flows = ref([])
let t1 = null
const venues = computed(() => rs.value.venues || [])
const nav = computed(() => rs.value.nav || {})
const pfRows = computed(() => pf.value.rows || [])
const transitions = computed(() => rs.value.transitions || [])
const urgentRows = computed(() => pfRows.value.filter(r => r.recon !== 'ok'))
const adlRows = computed(() => pfRows.value.flatMap(r =>
  (r.legs || []).filter(l => l.adl != null).map(l => ({ symbol: r.symbol, venue: l.venue, adl: l.adl }))))
const suggests = computed(() => {
  const out = []
  ;(pf.value.repair?.intents || []).forEach(it => out.push({
    tag: it.kind === 'RESCUE_HEDGE' ? '救援' : '撤离', lvl: 'p0',
    txt: `${it.symbol} → 撤出 ${it.venue}(est ${it.est_notional_usdt}U,shadow 提案)` }))
  pfRows.value.filter(r => String(r.saga_state).includes('RECOMMEND')).forEach(r =>
    out.push({ tag: '建议平', lvl: 'p1', txt: `${r.symbol} ${r.signal || ''}`.slice(0, 60) }))
  venues.value.filter(v => (v.trapped_usdt || 0) > 0).forEach(v =>
    out.push({ tag: '折价', lvl: 'p1', txt: `${v.venue} 受限权益 ${v.trapped_usdt}U 计入 haircut` }))
  return out
})
function minLiq(venue) {
  const ls = pfRows.value.flatMap(r => (r.legs || []).filter(l => l.venue === venue && l.dist_liq_pct != null))
  return ls.length ? Math.min(...ls.map(l => l.dist_liq_pct)) : null
}
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
async function load() {
  try {
    rs.value = await mixApi.riskSummary()
    pf.value = await mixApi.riskPortfolio()
    flows.value = (await mixApi.riskCashflows())?.rows || []
  } catch (e) { /* 状态条示 STALE */ }
}
onMounted(() => { load(); t1 = setInterval(load, 15000) })
onUnmounted(() => t1 && clearInterval(t1))
</script>

<style scoped lang="scss">
.wall3 { display: flex; flex-direction: column; gap: 10px; min-height: 100vh; background: var(--mix-bg, #0B0E11); padding: 10px 16px 12px; }
.gate { min-height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center;
  background: #0B0E11; color: #848E9C; font-size: 15px; }
.main { flex: 1; display: grid; grid-template-columns: 560px minmax(0,1fr) 500px; gap: 10px; min-height: 0; }
.col { display: flex; flex-direction: column; gap: 10px; min-height: 0; min-width: 0;
  .fill2 { flex: 1; } }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px;
  display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.card.urgent { border-color: rgba(246,70,93,.4);
  .chd2 { background: rgba(246,70,93,.05); }
  &.quiet { border-color: var(--mix-border, #262B33); .chd2 { background: transparent; } } }
.chd2 { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); padding: 10px 14px 6px; display: flex; align-items: center; gap: 8px; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.pad { padding: 6px 14px 10px; }
.up { color: #0ECB81; } .bad { color: #F6465D; }
.cnt { font-size: 10.5px; font-weight: 800; padding: 1px 9px; border-radius: 4px;
  &.p0 { background: rgba(246,70,93,.16); color: #F6465D; }
  &.okc { background: rgba(14,203,129,.12); color: #35b57c; } }
.pbadge { font-style: normal; font-size: 9px; font-weight: 800; padding: 0 5px; border-radius: 3px;
  background: rgba(240,185,11,.14); color: #F0B90B; }
.mhead, .mrow { display: grid; grid-template-columns: minmax(110px,1.2fr) 76px 76px 80px 100px; align-items: center; font-size: 10.5px; padding: 0 14px; }
.mhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 22px; background: var(--mix-panel, #12151A);
  border-top: 1px solid var(--mix-border, #262B33); border-bottom: 1px solid var(--mix-border, #262B33); }
.mrow { height: 30px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); }
  &.bad { background: rgba(246,70,93,.05); } }
.r { text-align: right; padding-right: 10px; font-variant-numeric: tabular-nums; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
.lrow { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--mix-t2, #848E9C);
  padding: 4px 14px; border-bottom: 1px dashed var(--mix-border, #262B33);
  b { color: var(--mix-t1, #EAECEF); } }
.ulist { padding: 4px 14px 8px; font-size: 11.5px; color: var(--mix-t2, #848E9C); }
.pri { flex: none; font-size: 10px; font-weight: 800; padding: 1px 7px; border-radius: 4px;
  &.p0 { background: rgba(246,70,93,.16); color: #F6465D; }
  &.p1 { background: rgba(240,185,11,.14); color: #F0B90B; } }
.mch { font-weight: 800; font-size: 9.5px; padding: 0 5px; border-radius: 4px;
  &.okc2 { background: rgba(14,203,129,.12); color: #35b57c; }
  &.pend { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.failc { background: rgba(246,70,93,.16); color: #F6465D; } }
.m2-NORMAL { background: rgba(14,203,129,.12); color: #35b57c; }
.m2-WATCH { background: rgba(240,185,11,.14); color: #F0B90B; }
.m2-NO_NEW_RISK { background: rgba(255,138,61,.16); color: #FF8A3D; }
.m2-REDUCE_ONLY, .m2-EXIT_ONLY { background: rgba(246,70,93,.16); color: #F6465D; }
.m2-FROZEN { background: #8B1E2D; color: #fff; }
.kv { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--mix-t2, #848E9C);
  padding: 4px 14px;
  b { color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; }
  &.tot { border-top: 1px solid var(--mix-border, #262B33); margin-top: 4px; padding-top: 8px;
    b { color: #F0B90B; font-size: 13px; } } }
.cfoot { font-size: 10px; color: var(--mix-t3, #5E6673); padding: 6px 14px; border-top: 1px solid var(--mix-border, #262B33); margin-top: auto; }
</style>
