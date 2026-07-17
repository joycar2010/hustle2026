<template>
  <!-- REV4 批C §6B:P3 账户与保证金汇总——全局事实带(连续指标带非卡片墙)+平台父行+账户子行。
       交互式与外接墙共用本组件(wall=true 只读注);数据=/operator/risk-control 单一快照;
       venue 原始风险口径与统一口径并列(§6B.3),未接入=—+注,绝不冒充。 -->
  <div class="rat">
    <div class="factband" v-if="snap">
      <span class="f"><i>组合权益</i><b>{{ nf(g.portfolio_equity_usdt,0) }} U</b></span>
      <span class="f"><i>总名义</i><b>{{ nf(g.gross_notional_usdt,0) }} U</b></span>
      <span class="f"><i>净Δ</i><b :class="cls0(g.net_delta_usdt)">{{ nf(g.net_delta_usdt,0) }} U</b></span>
      <span class="f"><i>有效杠杆</i><b>{{ nf(g.effective_leverage,2) }}x</b></span>
      <span class="f" :title="g.margin_utilization_note"><i>IM/MM占用</i><b class="dim">未接入</b></span>
      <span class="f"><i>最差强平</i><b :class="liqCls(g.worst_liquidation?.d)">{{ g.worst_liquidation ? nf(g.worst_liquidation.d,0)+'%('+g.worst_liquidation.venue+'·'+(g.worst_liquidation.symbol||'')+')' : '—' }}</b></span>
      <span class="f"><i>受限资本</i><b :class="g.restricted_capital_usdt>0?'wr':''">{{ nf(g.restricted_capital_usdt,0) }} U</b></span>
      <span class="f"><i>过期账户</i><b :class="g.stale_accounts>0?'dn':''">{{ g.stale_accounts }}</b></span>
      <span class="f"><i>保护越线</i><b :class="g.protection_hot>0?'wr':''">{{ g.protection_hot }}</b></span>
      <span class="fill"></span>
      <span class="asof">{{ ago }}s 前 · riskctl-v1</span>
    </div>
    <div class="tblwrap" v-if="snap">
      <div class="thead trow">
        <span class="c-acct">平台 / 账户</span><span class="c-mode">模式</span>
        <span class="c-num r">权益U</span><span class="c-num r">浮盈U</span>
        <span class="c-num r">名义U</span><span class="c-num r">杠杆</span>
        <span class="c-wide r">最差强平%·币</span><span class="c-num r">ADL</span>
        <span class="c-raw">原始口径(该所定义)</span><span class="c-age r">数据</span>
      </div>
      <template v-for="v in snap.venues" :key="v.venue">
        <div class="trow vrow" :title="'公式 '+(v.formula?.version||'')+':'+(v.formula?.raw||'')">
          <span class="c-acct"><b>{{ v.venue }}</b><i class="sub" v-if="v.cap_usdt">帽 {{ nf(v.cap_usdt,0) }}U{{ v.cap_utilization_pct!=null ? ' · 用'+v.cap_utilization_pct+'%' : '' }}</i></span>
          <span class="c-mode"><i class="mode" :class="'m-'+v.mode" :title="v.mode_reason||''">{{ MODE_CN[v.mode]||v.mode }}</i></span>
          <span class="c-num r"><b>{{ nf(v.equity_usdt,0) }}</b></span>
          <span class="c-num r"></span>
          <span class="c-num r"><b>{{ nf(v.gross_notional,0) }}</b></span>
          <span class="c-num r"><b>{{ v.equity_usdt ? nf(v.gross_notional/v.equity_usdt,2)+'x' : '—' }}</b></span>
          <span class="c-wide r" :class="liqCls(v.min_dist_liq_pct)"><b>{{ v.min_dist_liq_pct!=null ? nf(v.min_dist_liq_pct,0)+'%·'+(v.min_dist_symbol||'') : '—' }}</b></span>
          <span class="c-num r"></span>
          <span class="c-raw ell">
            <template v-if="v.raw_margin">杠杆账户风险值 {{ (v.raw_margin.margin_accounts||[]).map(x=>x.account.replace('margin:','')+'='+fmtMl(x.margin_level)).join(' ') || '—' }}
              <template v-if="v.raw_margin.master_futures_liq_pct!=null"> · 主合约爆率{{ nf(v.raw_margin.master_futures_liq_pct,1) }}%</template></template>
            <template v-else>{{ v.formula?.raw || '—' }}</template>
          </span>
          <span class="c-age r"></span>
        </div>
        <div v-for="a in v.accounts" :key="v.venue+a.account" class="trow arow" :class="{ghost:a.data_state==='STALE'}">
          <span class="c-acct sub2">└ {{ a.account }}</span>
          <span class="c-mode"></span>
          <span class="c-num r">{{ nf(a.equity_usdt,1) }}</span>
          <span class="c-num r" :class="cls0(a.upnl_usdt)">{{ nf(a.upnl_usdt,2) }}</span>
          <span class="c-num r">{{ nf(a.gross_notional,1) }}</span>
          <span class="c-num r">{{ nf(a.effective_leverage,2) }}</span>
          <span class="c-wide r" :class="liqCls(a.min_dist_liq_pct)">{{ a.min_dist_liq_pct!=null ? nf(a.min_dist_liq_pct,0)+'%·'+(a.worst_symbol||'') : (a.position_count? '—' : '无仓') }}</span>
          <span class="c-num r">{{ a.adl_max ?? '—' }}</span>
          <span class="c-raw"></span>
          <span class="c-age r" :class="{dn:a.data_state==='STALE'}">{{ a.age_sec!=null ? a.age_sec+'s' : '—' }}{{ a.data_state==='STALE'?'·过期':'' }}</span>
        </div>
      </template>
      <div v-if="!snap.venues?.length" class="empty">暂无账户快照(account-snapshot 未上报)</div>
    </div>
    <div class="ft" v-if="snap">
      各所"风险率"分子/分母/安全方向定义不同(悬停平台行看公式注册表);统一口径=权益/名义/有效杠杆/最差强平距离,
      IM/MM 保证金占用未接入(PLANNED)。{{ wall ? '外接墙只读,不发命令。' : '冻结新增/减险→风险事件页操作。' }}
      过期账户=快照>180s 或上报失败,fail-closed 按不可信处理。
    </div>
    <div v-if="err" class="empty">账户风险快照不可达:{{ err }}</div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { mixApi } from '../../api/mix'

const props = defineProps({ wall: { type: Boolean, default: false } })
const snap = ref(null); const err = ref(''); const tick = ref(0)
const g = computed(() => snap.value?.global || {})
const ago = computed(() => {
  void tick.value
  if (!snap.value?.as_of) return '—'
  return Math.max(0, Math.floor((Date.now() - new Date(snap.value.as_of).getTime()) / 1000))
})
const MODE_CN = { NORMAL: '正常', WATCH: '观察', NO_NEW_RISK: '禁新增', REDUCE_ONLY: '只减仓', EXIT_ONLY: '只退出', FROZEN: '冻结', STALE: '过期' }
function nf(v, dp = 2) { return v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp }) }
function cls0(v) { return v == null ? '' : (Number(v) >= 0 ? 'up' : 'dn') }
function liqCls(d) { if (d == null) return ''; return d < 50 ? 'dn' : (d < 80 ? 'wr' : '') }
function fmtMl(v) { return v == null ? '—' : (Number(v) >= 999 ? '999(无负债)' : Number(v).toFixed(1)) }
async function load() {
  try { snap.value = await mixApi.v6RiskControl(); err.value = '' }
  catch (e) { err.value = typeof e?.detail === 'string' ? e.detail : '加载失败' }
}
let t1, t2
onMounted(() => { load(); t1 = setInterval(load, 30000); t2 = setInterval(() => tick.value++, 1000) })
onUnmounted(() => { clearInterval(t1); clearInterval(t2) })
</script>
<style scoped>
.rat{display:flex;flex-direction:column;gap:8px;min-height:0}
.factband{display:flex;align-items:center;gap:16px;background:var(--mix-card,#181B21);border:1px solid var(--mix-border,#262B33);
  border-radius:8px;padding:8px 14px;overflow-x:auto;white-space:nowrap}
.f{display:inline-flex;flex-direction:column;gap:1px;flex:none}
.f i{font-style:normal;font-size:8.5px;color:var(--mix-t3,#5E6673)}
.f b{font-size:12.5px;color:var(--mix-t1,#EAECEF);font-variant-numeric:tabular-nums}
.f b.dim{color:var(--mix-t3,#5E6673);font-weight:400}
.fill{flex:1}
.asof{font-size:9px;color:var(--mix-t3,#5E6673);flex:none}
.tblwrap{background:var(--mix-card,#181B21);border:1px solid var(--mix-border,#262B33);border-radius:8px;overflow:auto}
.trow{display:flex;align-items:center;gap:8px;min-width:1080px;padding:0 12px;min-height:30px;
  border-bottom:1px solid var(--mix-border,#262B33);font-size:10.5px;color:var(--mix-t2,#848E9C)}
.thead{position:sticky;top:0;z-index:2;background:var(--mix-card,#181B21);color:var(--mix-t3,#5E6673);font-size:9.5px;min-height:24px}
.trow>span{flex-shrink:0;min-width:0}
.vrow{background:var(--mix-panel,#12151A);min-height:34px}
.vrow b{color:var(--mix-t1,#EAECEF);font-size:11.5px}
.arow.ghost{opacity:.55}
.c-acct{width:150px;display:flex;flex-direction:column;line-height:1.2}
.c-acct .sub{font-style:normal;font-size:8.5px;color:var(--mix-t3,#5E6673)}
.c-acct.sub2{padding-left:10px}
.c-mode{width:58px}
.c-num{width:78px}
.c-wide{width:120px}
.c-raw{flex:1 1 220px;min-width:160px;font-size:9.5px;color:var(--mix-t3,#5E6673)}
.c-age{width:74px;font-size:9.5px}
.r{text-align:right;font-variant-numeric:tabular-nums}
.ell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mode{font-style:normal;font-size:9px;border:1px solid var(--mix-border,#262B33);border-radius:3px;padding:1px 6px}
.m-NORMAL{color:#35b57c;border-color:#35b57c55}
.m-WATCH{color:#F0B90B;border-color:#F0B90B66}
.m-NO_NEW_RISK{color:#FF8A3D;border-color:#FF8A3D66}
.m-REDUCE_ONLY,.m-EXIT_ONLY,.m-FROZEN{color:#F6465D;border-color:#F6465D66}
.m-STALE{color:#8CA3C7;border-color:#8CA3C766}
.up{color:#35b57c}.dn{color:#F6465D}.wr{color:#FF8A3D}
.ft{font-size:8.5px;color:var(--mix-t3,#5E6673);line-height:1.5;padding:0 4px}
.empty{padding:20px;text-align:center;color:var(--mix-t3,#5E6673);font-size:11px}
</style>
