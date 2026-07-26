<template>
  <div class="wall1" v-if="authed">
    <RiskStatusBar />
    <div class="main">
      <!-- 机会台(of2aN,w520) -->
      <div class="card opplist">
        <div class="chd2"><b>机会台</b><span class="grow" /><span class="dimtxt">shadow 候选 · {{ opps.length }} 过闸 / {{ skipped }} 未过</span></div>
        <div class="sub">硬闸 = 风调E&gt;0 · 数据新鲜 · 容量&gt;0 ｜ 排序:风调E净期望</div>
        <div class="thead"><span class="c1">币</span><span class="c2">产品</span><span class="c3">E bps/日</span><span class="c4">容量U</span><span class="c5">路由</span><span class="c6">闸</span></div>
        <div class="tbody">
          <div v-if="!opps.length" class="dimtxt pad">本轮无过闸候选</div>
          <div v-for="o in opps" :key="o.symbol" class="orow" :class="{sel: sel===o.symbol, blocked: o.blocked}" @click="pick(o)">
            <span class="c1"><b>{{ o.symbol }}</b></span>
            <span class="c2"><i class="pbadge">C2.H</i></span>
            <span class="c3" :class="(o.risk_adjusted_e_bps??0)>0?'up':'down'">{{ bps(o) }}</span>
            <span class="c4">{{ o.target_notional_usdt ?? 'N/A' }}</span>
            <span class="c5"><b :class="'vx-'+o.venue_long">{{ o.venue_long }}</b>⟶<b :class="'vx-'+o.venue_short">{{ o.venue_short }}</b></span>
            <span class="c6"><FIcon :name="o.blocked?'block':'check'" :size="12"/></span>
          </div>
          <div class="fold" v-if="skipped">未过硬闸 {{ skipped }} 项(容量/E/新鲜度/policy 不达标)</div>
        </div>
        <div class="cfoot">ⓘ 机会不直接开仓:仅可「生成开仓提案」进入屏2 待办 P2 审批(DRY_RUN→冷却→TOTP)</div>
      </div>

      <!-- 标的分析(dOuhZ) -->
      <div class="card analysis">
        <div class="chd2"><b>标的分析</b><span class="seltxt">{{ sel || '—' }}</span><span class="grow" />
          <el-button size="small" @click="openAiCoin">AiCoin 研判 →</el-button>
          <el-button size="small" type="warning" plain disabled title="提案链下批接入">生成开仓提案(→屏2 P2)</el-button>
        </div>
        <div class="minis">
          <div class="mini"><span>E 净期望(风调)</span><b :class="(cur?.risk_adjusted_e_bps??0)>0?'up':'down'">{{ cur ? bps(cur) + ' bps/日' : 'N/A' }}</b></div>
          <div class="mini"><span>容量(硬闸口径)</span><b>{{ cur?.target_notional_usdt != null ? cur.target_notional_usdt + ' U' : 'N/A' }}</b></div>
          <div class="mini"><span>信号半衰期</span><b>N/A</b><span class="dimtxt">E历史采样待接</span></div>
          <div class="mini"><span>建议持仓 / charge</span><b>{{ cur?.target_notional_usdt != null ? cur.target_notional_usdt + ' U' : 'N/A' }}</b><span class="dimtxt">charge {{ cur?.risk_charge_bps ?? 'N/A' }} bps</span></div>
        </div>
        <div class="chart">
          <div class="chd3">逐所资金费(按结算周期日化 %/d)</div>
          <div class="bars">
            <div v-for="r in va" :key="r.venue" class="barcol" :title="`${r.venue} ${r.funding_daily_pct ?? 'N/A'}%/d`">
              <div class="barwrap"><div class="bar" :class="(r.funding_daily_pct||0)>=0?'pos':'neg'"
                :style="{height: barH(r.funding_daily_pct)}"></div></div>
              <span class="bl" :class="'vx-'+r.venue">{{ r.venue.slice(0,4) }}</span>
              <span class="bv" :class="(r.funding_daily_pct||0)>=0?'up':'down'">{{ r.funding_daily_pct ?? '—' }}</span>
            </div>
          </div>
        </div>
        <div class="vtable">
          <div class="chd3">多所量价 / OI / 资金费</div>
          <div class="vhead"><span>Venue</span><span>模式</span><span class="r">中价</span><span class="r">点差bps</span><span class="r">资金费%/d</span><span class="r">周期h</span><span class="r">OI</span><span>新鲜</span></div>
          <div v-for="r in va" :key="r.venue" class="vrow" :class="{stale: !r.fresh}">
            <span><b :class="'vx-'+r.venue">{{ r.venue }}</b></span>
            <span :class="'m-'+r.mode">{{ r.mode }}</span>
            <span class="r">{{ r.mid ?? 'N/A' }}</span>
            <span class="r">{{ r.spread_bps ?? 'N/A' }}</span>
            <span class="r" :class="(r.funding_daily_pct||0)>=0?'up':'down'">{{ r.funding_daily_pct ?? 'N/A' }}</span>
            <span class="r">{{ r.interval_h ?? 'N/A' }}</span>
            <span class="r">N/A</span>
            <span><template v-if="r.fresh"><FIcon name="check" :size="11"/></template><template v-else>STALE</template></span>
          </div>
        </div>
      </div>

      <!-- 右列(kP5MU,w440):Funding日历 + LAB -->
      <div class="rcol">
        <div class="card fcal">
          <div class="chd2"><b>Funding 日历</b><span class="grow" /><span class="dimtxt">在管组合逐结算</span></div>
          <div v-if="!cal.length" class="dimtxt pad">无在管组合</div>
          <div v-for="c in cal" :key="c.symbol" class="crow">
            <b>{{ c.symbol }}</b><i class="pbadge">{{ c.product }}</i>
            <span class="dimtxt">{{ Math.floor(c.next_cashflow.in_min/60) }}h{{ c.next_cashflow.in_min%60 }}m 后</span>
            <span class="grow" />
            <b :class="(c.next_cashflow.est_usdt ?? c.next_cashflow.net_daily_pct) >= 0 ? 'up' : 'down'">
              {{ c.next_cashflow.est_usdt != null ? (c.next_cashflow.est_usdt>=0?'+':'') + c.next_cashflow.est_usdt + ' U' : c.next_cashflow.net_daily_pct + '%/d' }}</b>
          </div>
          <div class="ctotal" v-if="cal.length"><span>合计(下一周期估)</span><b :class="calTotal>=0?'up':'down'">{{ calTotal>=0?'+':'' }}{{ calTotal }} U</b></div>
        </div>
        <div class="card lab">
          <div class="chd2"><b>LAB</b><span class="dimtxt">HOUSE_RND · shadow 决策账</span></div>
          <div v-if="!labRows.length" class="dimtxt pad">无 shadow 持有(engine-lending)</div>
          <div v-for="l in labRows" :key="l.coin" class="crow">
            <b>{{ l.coin }}</b><i class="pbadge lab2">C3.R·shadow</i>
            <span class="grow" /><span class="dimtxt">净差 {{ l.net_daily_pct ?? 'N/A' }}%/d</span>
          </div>
          <div class="cfoot">LAB 战绩不进 CORE_POOL 账;晋级须专场验收</div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="gate">屏1 · 机会与LAB<br /><small>URL 需携带 ?token=(只读墙令牌,后端校验)</small></div>
  <WallStatus v-if="authed" title="屏1 · 机会墙" @gen="load"/>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import WallStatus from '../../components/v62/WallStatus.vue'
import { mixApi } from '../../api/mix'

const route = useRoute()
const authed = ref(!!route.query.token || !!localStorage.getItem('mix_token'))
if (route.query.token) localStorage.setItem('mix_token', String(route.query.token))

const opps = ref([]); const skipped = ref(0); const sel = ref(''); const va = ref([])
const pfRows = ref([]); const labRows = ref([])
let t1 = null
const cur = computed(() => opps.value.find(o => o.symbol === sel.value))
const cal = computed(() => pfRows.value.filter(r => r.next_cashflow?.in_min != null)
  .sort((a, b) => a.next_cashflow.in_min - b.next_cashflow.in_min))
const calTotal = computed(() => Math.round(cal.value.reduce((t, c) => t + (c.next_cashflow.est_usdt || 0), 0) * 1000) / 1000)
const bps = o => (o.risk_adjusted_e_bps != null ? (o.risk_adjusted_e_bps > 0 ? '+' : '') + o.risk_adjusted_e_bps : 'N/A')
const maxAbs = computed(() => Math.max(0.01, ...va.value.map(r => Math.abs(r.funding_daily_pct || 0))))
const barH = v => (v == null ? '2px' : Math.max(3, Math.abs(v) / maxAbs.value * 64) + 'px')
function openAiCoin() { window.open('/mix/aicoin') }
async function pick(o) {
  sel.value = o.symbol
  try { va.value = (await mixApi.riskSymbolAnalysis(o.symbol))?.venues || [] } catch (e) { va.value = [] }
}
async function load() {
  try {
    const c = await mixApi.riskOpportunities()
    opps.value = c?.candidates || []; skipped.value = c?.skipped_count ?? 0
    if (!sel.value && opps.value.length) pick(opps.value[0])
    pfRows.value = (await mixApi.riskPortfolio())?.rows || []
    labRows.value = ((await mixApi.riskLab())?.would_hold) || []
  } catch (e) { /* 状态条示 STALE */ }
}
// PATCH-02 §7/§18:WS generation 变化驱动刷新(WallStatus @gen),REST 只留 60s 兜底——
// 消灭每墙 15s 独立轮询;墙与主控台同一 generation。
onMounted(() => { load(); t1 = setInterval(load, 60000); mixApi.uxPageview('wall') })
onUnmounted(() => t1 && clearInterval(t1))
</script>

<style scoped lang="scss">
.wall1 { display: flex; flex-direction: column; gap: 10px; min-height: 100vh; background: var(--mix-bg, #0B0E11); padding: 10px 16px 12px; }
.gate { min-height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center;
  background: #0B0E11; color: #848E9C; font-size: 15px; }
.main { flex: 1; display: grid; grid-template-columns: 520px minmax(0, 1fr) 440px; gap: 10px; min-height: 0; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px;
  display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.chd2 { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); padding: 10px 14px 4px; display: flex; align-items: center; gap: 8px; }
.chd3 { font-size: 11px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 4px; }
.sub { font-size: 10px; color: var(--mix-t3, #5E6673); padding: 0 14px 8px; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.pad { padding: 8px 14px; }
.up { color: #0ECB81 !important; } .down { color: #F6465D !important; }
.pbadge { font-style: normal; font-size: 9px; font-weight: 800; padding: 0 5px; border-radius: 3px;
  background: rgba(240,185,11,.14); color: #F0B90B; &.lab2 { background: rgba(74,156,255,.14); color: #4A9CFF; } }
.thead, .orow { display: grid; grid-template-columns: 100px 52px 76px 62px minmax(0,1fr) 40px; align-items: center; font-size: 10.5px; }
.thead { background: var(--mix-panel, #12151A); color: var(--mix-t3, #5E6673); font-size: 10px; height: 22px;
  border-top: 1px solid var(--mix-border, #262B33); border-bottom: 1px solid var(--mix-border, #262B33);
  > span { padding: 0 8px; } }
.tbody { flex: 1; overflow-y: auto; min-height: 0; }
.orow { height: 30px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C); cursor: pointer;
  > span { padding: 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  b { color: var(--mix-t1, #EAECEF); }
  &:hover { background: var(--mix-card2, #1E2329); }
  &.sel { background: var(--mix-card2, #1E2329); border-left: 2px solid #4A9CFF; }
  &.blocked { opacity: .55; } }
.fold { background: var(--mix-panel, #12151A); font-size: 10px; color: var(--mix-t3, #5E6673); padding: 5px 10px; }
.cfoot { font-size: 10px; color: var(--mix-t3, #5E6673); padding: 6px 14px; border-top: 1px solid var(--mix-border, #262B33); }
.seltxt { color: #F0B90B; font-size: 12px; }
.minis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding: 4px 16px 10px; }
.mini { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 8px 12px;
  display: flex; flex-direction: column; gap: 2px;
  span { font-size: 10px; color: var(--mix-t3, #5E6673); }
  b { font-size: 15px; color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; } }
.chart { padding: 0 16px 8px; }
.bars { display: flex; gap: 14px; align-items: flex-end; height: 108px; padding: 4px 0; }
.barcol { display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 1;
  .barwrap { height: 68px; display: flex; align-items: flex-end; }
  .bar { width: 26px; border-radius: 3px 3px 0 0; &.pos { background: #0ECB81; } &.neg { background: #F6465D; } }
  .bl { font-size: 9.5px; color: var(--mix-t3, #5E6673); }
  .bv { font-size: 10px; font-variant-numeric: tabular-nums; } }
.vtable { padding: 0 16px 12px; }
.vhead, .vrow { display: grid; grid-template-columns: 90px 100px 1fr 80px 90px 60px 50px 54px; font-size: 10.5px; align-items: center; }
.vhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 22px; border-bottom: 1px solid var(--mix-border, #262B33); }
.vrow { height: 26px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); } &.stale { opacity: .5; } }
.r { text-align: right; padding-right: 10px; font-variant-numeric: tabular-nums; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
.rcol { display: flex; flex-direction: column; gap: 10px; min-height: 0;
  .fcal { flex: 1; } .lab { height: 330px; flex: none; } }
.crow { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--mix-t2, #848E9C);
  padding: 5px 14px; border-bottom: 1px dashed var(--mix-border, #262B33);
  b { color: var(--mix-t1, #EAECEF); } }
.ctotal { display: flex; justify-content: space-between; padding: 8px 14px; font-size: 11.5px;
  border-top: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { font-variant-numeric: tabular-nums; } }
</style>
