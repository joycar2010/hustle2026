<template>
  <!-- V6.2 REV4 批B §6A:StrategyHierarchyTable——今日工作与策略工作台共用的父子二级表。
       两级=币种/经济组合父行(GroupRow) + 账户腿子行(AccountLegRow,展开态与列表视图共用);
       预设=任务精简(today)/策略完整(strategy)只换列,同一 WorkItem/generation/allowed_actions;
       聚合全部来自服务端 legagg(§6A.13),前端只渲染;子行无独立开平仓入口。 -->
  <div class="wt">
    <div class="wtbar">
      <span class="seg">
        <a :class="{on:preset!=='strategy'}" @click="$emit('update:preset','today')">任务精简</a>
        <a :class="{on:preset==='strategy'}" @click="$emit('update:preset','strategy')">策略完整</a>
      </span>
      <span class="pchips">
        <i v-for="p in productList" :key="p" class="pc" :class="{on:product===p||(p==='全部'&&!product)}"
           @click="$emit('update:product', p==='全部'?'':p)">{{ p }}</i>
      </span>
      <span v-if="product==='C3.S'" class="legchip" :class="{warn:legacyDiff>0}">
        与旧坑位页差异 {{ legacyDiff==null?'…':legacyDiff }} 项 ·
        <a @click.stop="$router.push('/mix/slots')">旧页(仍权威写)→</a>
        <a @click.stop="$router.push('/mix/legacy')">对比→</a>
      </span>
      <span class="fill"></span>
      <span class="note">{{ preset==='strategy' ? (product ? product+' 专业列' : '全部策略=通用核心列;选单一产品展开专业列(§6A.5A)') : '任务优先:阶段/风险/下一步' }}</span>
    </div>
    <div class="wtscroll">
      <!-- ═ 任务精简预设(原深表格列) ═ -->
      <template v-if="preset!=='strategy'">
        <div class="wthead wtrow">
          <span class="c-exp"></span>
          <span class="c-stage">阶段</span><span class="c-sym">币种</span><span class="c-prod">产品</span>
          <span class="c-src">来源</span><span class="c-ctl">控制</span><span class="c-route">路线</span>
          <span class="c-cap r">投入</span><span class="c-ev r">预计/确认收益</span>
          <span class="c-rs">研判</span><span class="c-risk">风险</span>
          <span class="c-next">下一步</span><span class="c-act">主操作</span>
        </div>
        <template v-for="w in sorted" :key="w.work_item_id">
          <div class="wtrow" :class="{sel:selId===w.work_item_id, bad:w.workflow_stage==='RECONCILING'}" @click="$emit('open', w)">
            <span class="c-exp" @click.stop="w.account_legs?.length && $emit('toggle', w.work_item_id)">
              <i v-if="w.account_legs?.length" class="expbtn" :class="{on:expanded[w.work_item_id]}">{{ expanded[w.work_item_id]?'▾':'▸' }}</i></span>
            <span class="c-stage"><i class="st" :class="w.workflow_stage">{{ w.stage_detail || STAGE_CN[w.workflow_stage] || w.workflow_stage }}</i></span>
            <span class="c-sym"><b @click.stop="$emit('openAsset', w.symbol)" style="cursor:pointer;color:var(--mix-gold,#F0B90B);font-weight:800">{{ w.symbol }}</b></span>
            <span class="c-prod" :class="'px-'+String(w.strategy_code||'').split('.')[0].toLowerCase()">{{ w.strategy_code }}</span>
            <span class="c-src">{{ SRC_CN[w.source] || w.source }}</span>
            <span class="c-ctl">{{ CTL_CN[w.automation_mode] || w.automation_mode || '—' }}</span>
            <span class="c-route ell" :title="w.route||''"><template v-for="(rv,ri) in String(w.route||'—').split('↔')" :key="ri"><i v-if="ri" style="color:var(--mix-t3);font-style:normal">↔</i><span :class="'vx-'+rv">{{ rv }}</span></template></span>
            <span class="c-cap r"><ValueCell :value="w.capital_reserved" :state="w.data_state?.capital_reserved" suffix=" U" :dp="0"/></span>
            <span class="c-ev r">
              <ValueCell :value="w.expected_net_return" :state="w.data_state?.expected_net_return" suffix="bps/日" :dp="1"/>
              <template v-if="w.confirmed_pnl!=null"> · <ValueCell :value="w.confirmed_pnl" suffix="U" :dp="1"/></template>
            </span>
            <span class="c-rs"><i v-if="w.research_status && w.research_status!=='NOT_REQUIRED'" class="rs" :class="w.research_status">{{ RS_CN[w.research_status]||w.research_status }}</i><i v-else class="rs dim">—</i></span>
            <span class="c-risk" :class="'rk-'+((w.risk_protection_state&&w.risk_protection_state!=='NORMAL')?w.risk_protection_state:(w.risk_status?.level||''))"
                  :title="(w.risk_protection_state&&w.risk_protection_state!=='NORMAL')?('点差保护(shadow) 预算余'+(w.hard_loss_budget_remaining??'—')+'U'):(w.risk_status?.reason||'')">
<template v-if="w.risk_protection_state&&w.risk_protection_state!=='NORMAL'"><FIcon name="shield" :size="10"/>{{ PROT_CN[w.risk_protection_state]||w.risk_protection_state }}</template><template v-else>{{ w.risk_status?.level==='NORMAL' ? '正常' : (w.risk_status?.level||'—') }}</template></span>
            <span class="c-next ell" :title="w.next_action||''">{{ w.next_action || '—' }}</span>
            <span class="c-act" @click.stop>
              <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                             :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                             :state="rowState[w.work_item_id]||''" @run="(a)=>$emit('run', w, a)"/>
            </span>
          </div>
          <LegRows v-if="expanded[w.work_item_id] && w.account_legs?.length" :w="w"/>
        </template>
      </template>
      <!-- ═ 策略完整预设(§6A.5A 六语义区顺序:身份流程/仓位债务/点差退出/费率现金流/保证金风险/时间动作) ═ -->
      <template v-else>
        <div class="wthead wtrow strat">
          <span class="c-exp"></span>
          <span class="c-stage">阶段</span><span class="c-sym">币种/产品</span><span class="c-ctl">控制</span>
          <span class="c-route">路线</span>
          <span class="s-num r">规模U</span><span class="s-num r">净Δ</span>
          <template v-if="product==='C3.S'">
            <span class="s-num r">借币量</span><span class="s-num r">利率%/d</span><span class="s-wide r">点差 开→现%</span>
          </template>
          <template v-else-if="isC2">
            <span class="s-num r">多费率%/d</span><span class="s-num r">空费率%/d</span><span class="s-num r">持仓差U</span>
          </template>
          <span class="s-num r">费差%/d</span>
          <span class="s-num r">退出盈亏U</span><span class="s-num r">已确认U</span>
          <span class="s-num r">预算余U</span><span class="s-wide r">最差强平%</span>
          <span class="c-risk">风险</span><span class="c-next">下一时间/步</span><span class="c-act">主操作</span>
        </div>
        <template v-for="w in sorted" :key="w.work_item_id">
          <div class="wtrow strat" :class="{sel:selId===w.work_item_id, bad:w.workflow_stage==='RECONCILING'}" @click="$emit('open', w)">
            <span class="c-exp" @click.stop="w.account_legs?.length && $emit('toggle', w.work_item_id)">
              <i v-if="w.account_legs?.length" class="expbtn" :class="{on:expanded[w.work_item_id]}">{{ expanded[w.work_item_id]?'▾':'▸' }}</i></span>
            <span class="c-stage"><i class="st" :class="w.workflow_stage">{{ w.stage_detail || STAGE_CN[w.workflow_stage] || w.workflow_stage }}</i></span>
            <span class="c-sym"><b @click.stop="$emit('openAsset', w.symbol)" style="cursor:pointer;color:var(--mix-gold,#F0B90B);font-weight:800">{{ w.symbol }}</b><i class="sub">{{ w.strategy_code }}</i></span>
            <span class="c-ctl">{{ CTL_CN[w.automation_mode] || '—' }}</span>
            <span class="c-route ell" :title="w.route||''"><template v-for="(rv,ri) in String(w.route||'—').split('↔')" :key="ri"><i v-if="ri" style="color:var(--mix-t3);font-style:normal">↔</i><span :class="'vx-'+rv">{{ rv }}</span></template></span>
            <span class="s-num r amtx">{{ nf(w.capital_reserved,0) }}</span>
            <span class="s-num r">{{ nf(ge(w).net_delta,2) }}</span>
            <template v-if="product==='C3.S'">
              <span class="s-num r">{{ nf(ge(w).borrowed_qty,2) }}</span>
              <span class="s-num r">{{ nf(ge(w).interest_daily_pct,3) }}</span>
              <span class="s-wide r">{{ ge(w).spread_open_pct!=null ? nf(ge(w).spread_open_pct,2)+'→'+nf(ge(w).spread_close_pct,2) : '—' }}</span>
            </template>
            <template v-else-if="isC2">
              <span class="s-num r" :class="cls0(ge(w).funding_long_daily_pct)">{{ nf(ge(w).funding_long_daily_pct,3) }}</span>
              <span class="s-num r" :class="cls0(ge(w).funding_short_daily_pct)">{{ nf(ge(w).funding_short_daily_pct,3) }}</span>
              <span class="s-num r">{{ nf(ge(w).notional_gap_usdt,1) }}</span>
            </template>
            <span class="s-num r" :class="cls0(ge(w).gap_now_pct)">{{ nf(ge(w).gap_now_pct,3) }}</span>
            <span class="s-num r" :class="cls0(ge(w).closeout_pnl_net)">{{ nf(ge(w).closeout_pnl_net,2) }}</span>
            <span class="s-num r" :class="cls0(w.confirmed_pnl)">{{ nf(w.confirmed_pnl,2) }}</span>
            <span class="s-num r">{{ nf(ge(w).budget_remaining,2) }}</span>
            <span class="s-wide r" :class="liqCls(ge(w).margin_min_dist_liq_pct)">{{ ge(w).margin_min_dist_liq_pct!=null ? nf(ge(w).margin_min_dist_liq_pct,0)+'('+(ge(w).margin_worst_venue||'?')+')' : '—' }}</span>
            <span class="c-risk" :class="'rk-'+((w.risk_protection_state&&w.risk_protection_state!=='NORMAL')?w.risk_protection_state:(w.risk_status?.level||''))">
<template v-if="w.risk_protection_state&&w.risk_protection_state!=='NORMAL'"><FIcon name="shield" :size="10"/>{{ PROT_CN[w.risk_protection_state]||w.risk_protection_state }}</template><template v-else>{{ w.risk_status?.level==='NORMAL' ? '正常' : (w.risk_status?.level||'—') }}</template></span>
            <span class="c-next ell" :title="(w.next_deadline||'')+' '+(w.next_action||'')">{{ (w.next_deadline||'').slice(5,16) }} {{ w.next_action || '' }}</span>
            <span class="c-act" @click.stop>
              <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                             :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                             :state="rowState[w.work_item_id]||''" @run="(a)=>$emit('run', w, a)"/>
            </span>
          </div>
          <LegRows v-if="expanded[w.work_item_id] && w.account_legs?.length" :w="w"/>
        </template>
      </template>
      <EmptyState v-if="!sorted.length" kind="none" title="当前队列无工作项" hint="点流程条其它分段查看"/>
    </div>
    <div class="wtfoot">父行聚合=服务端 legagg(最差腿口径);排序筛选只作用于父行,账户腿始终跟随;子行无独立开平仓入口(§6A.11)</div>
  </div>
</template>
<script setup>
import { computed, h, ref, watch } from 'vue'
import ValueCell from './ValueCell.vue'
import PrimaryAction from './PrimaryAction.vue'
import EmptyState from './EmptyState.vue'
import { mixApi } from '../../api/mix'

const props = defineProps({
  items: { type: Array, default: () => [] },
  rowState: { type: Object, default: () => ({}) },
  selId: { type: String, default: '' },
  preset: { type: String, default: 'today' },      // today=任务精简 / strategy=策略完整
  product: { type: String, default: '' },          // ''=全部;单一产品才展开专业列(§6A.5A)
  expanded: { type: Object, default: () => ({}) }, // 与列表视图共用同一展开态(§6A.5B)
})
defineEmits(['open', 'run', 'update:preset', 'update:product', 'toggle'])

const STAGE_CN = { DISCOVERED: '候选', RESEARCH: '人工研判', REVIEW: '审批', RESERVED: '已批准',
                   EXECUTING: '执行中', HOLDING: '持有', EXITING: '退出', RECONCILING: '异常' }
const SRC_CN = { opener: '顾问', proposal: '提案', manager: '内核', coin: 'C3引擎', repair: '修复', research: '研判' }
const CTL_CN = { AUTO: '自动', ASSISTED: '辅助', MANUAL: '手动' }
const RS_CN = { PENDING: '待完成', COMPLETED: '已完成', EXPIRED: '已过期' }
const PROT_CN = { WATCH: '观察', NO_ADD: '禁加仓', REDUCE_REQUIRED: '需减仓', EXIT_REQUIRED: '需退出' }
const LEG_CN = { PERP_SHORT: '永续空', PERP_LONG: '永续多', SPOT_LONG: '现货多', BORROW_SPOT_SHORT: '借币空', PERP_LONG_HEDGE: '对冲多(主)' }
const ORDER = { RECONCILING: 0, RESEARCH: 1, REVIEW: 2, RESERVED: 3, EXECUTING: 4, HOLDING: 5, EXITING: 6, DISCOVERED: 7 }

const filtered = computed(() => props.product
  ? props.items.filter(w => String(w.strategy_code || '') === props.product)
  : props.items)
const sorted = computed(() => filtered.value.slice().sort((a, b) =>
  (ORDER[a.workflow_stage] ?? 9) - (ORDER[b.workflow_stage] ?? 9) || String(a.symbol).localeCompare(String(b.symbol))))
const productList = computed(() => ['全部', ...[...new Set(props.items.map(w => w.strategy_code).filter(Boolean))].sort()])
const isC2 = computed(() => String(props.product).startsWith('C2'))

function primaryOf(w) { const a = w.allowed_actions || []; return a.find(x => x.kind === 'primary') || a[0] || null }
function ge(w) { return w.group_econ || {} }
function nf(v, dp = 2) { return v == null ? '—' : Number(v).toFixed(dp) }
function cls0(v) { return v == null ? '' : (Number(v) >= 0 ? 'up' : 'dn') }
function liqCls(d) { if (d == null) return ''; return d < 50 ? 'dn' : (d < 80 ? 'wr' : '') }

// C3.S 只读镜像对比(§6A.16):差异数来自既有 legacy_compare(七维 diff),不复制对比逻辑
const legacyDiff = ref(null)
watch(() => props.product, async (p) => {
  if (p !== 'C3.S') { legacyDiff.value = null; return }
  try {
    const r = await mixApi.v6LegacyCompare()
    legacyDiff.value = (typeof r?.diff_count === 'number') ? r.diff_count : ((r?.diffs || []).length || 0)
  } catch (e) { legacyDiff.value = null }
}, { immediate: true })

// 账户腿子行(渲染函数组件:父行下全宽腿表,两预设共用;§6A.14 同一渲染块不拆散)
const LegRows = (p) => {
  const w = p.w
  const cell = (t, cls = '') => h('span', { class: cls }, t == null || t === '' ? '—' : String(t))
  return h('div', { class: 'legblock', onClick: (e) => e.stopPropagation() }, [
    h('div', { class: 'leghd2' }, ['账户/腿', '方向', '数量', '持仓U', '标记价', '浮盈U', '费率/息%/d', '强平距%', 'ADL', '事实态']
      .map(t => h('span', t))),
    ...(w.account_legs || []).map(l => h('div', { class: 'legrow2' + (l.data_state !== 'PRESENT' ? ' ghost' : '') }, [
      cell(`${l.account} · ${LEG_CN[l.role] || l.role}`),
      h('span', { class: l.side === 'LONG' ? 'up' : 'dn' }, l.side === 'LONG' ? '多' : '空'),
      cell(l.qty != null ? Number(l.qty).toLocaleString('en-US', { maximumFractionDigits: 2 }) : null, 'r'),
      cell(l.notional_usdt, 'r'), cell(l.mark, 'r'),
      cell(l.upnl != null ? Number(l.upnl).toFixed(2) : null, 'r ' + (l.upnl >= 0 ? 'up' : 'dn')),
      cell(l.funding_daily_pct ?? (l.interest_daily_pct != null ? '息' + l.interest_daily_pct : null), 'r'),
      cell((l.dist_liq_pct ?? l.liq_pct) != null ? Number(l.dist_liq_pct ?? l.liq_pct).toFixed(0) : null, 'r'),
      cell(l.adl, 'r'), cell(l.data_state === 'PRESENT' ? '直拉' : '未接入'),
    ])),
  ])
}
</script>
<style scoped>
.wt{flex:1;min-height:0;display:flex;flex-direction:column;background:var(--mix-card,#181B21);
  border:1px solid var(--mix-border,#262B33);border-radius:10px;overflow:hidden}
.wtbar{display:flex;align-items:center;gap:10px;padding:6px 12px;border-bottom:1px solid var(--mix-border,#262B33);flex:none}
.seg{display:flex;background:var(--mix-panel,#12151A);border-radius:6px;padding:2px}
.seg a{font-size:10.5px;color:var(--mix-t2,#848E9C);padding:3px 12px;border-radius:5px;cursor:pointer}
.seg a.on{background:var(--mix-card2,#1E2329);color:var(--mix-t1,#EAECEF);font-weight:700}
.pchips{display:flex;gap:4px}
.pc{font-style:normal;font-size:10px;color:var(--mix-t2,#848E9C);padding:2px 9px;border:1px solid var(--mix-border,#262B33);border-radius:5px;cursor:pointer}
.pc.on{color:var(--mix-accent,#F0B90B);background:#F0B90B14;border-color:#F0B90B4D}
.legchip{font-size:10px;color:var(--mix-t2,#848E9C);border:1px dashed var(--mix-border,#262B33);border-radius:5px;padding:2px 8px}
.legchip.warn{color:#FF8A3D;border-color:#FF8A3D66}
.legchip a{color:var(--mix-blue,#4A9CFF);cursor:pointer;margin-left:4px}
.fill{flex:1}
.note{font-size:9.5px;color:var(--mix-t3,#5E6673)}
.wtscroll{flex:1;overflow:auto}
.wtrow{display:flex;align-items:center;gap:8px;min-width:1150px;padding:0 12px;min-height:34px;
  border-bottom:1px solid var(--mix-border,#262B33);font-size:11px;color:var(--mix-t2,#848E9C);cursor:pointer}
.wtrow.strat{min-width:1330px}
.wtrow:hover{background:rgba(240,185,11,.04)}
.wtrow.sel{background:rgba(240,185,11,.08)}
.wtrow.bad{background:rgba(246,70,93,.06)}
.wthead{position:sticky;top:0;z-index:2;background:var(--mix-card,#181B21);color:var(--mix-t3,#5E6673);
  font-size:10px;min-height:26px;cursor:default}
.wtrow>span{flex-shrink:0;min-width:0}
.c-exp{width:18px;display:flex;justify-content:center}
.expbtn{font-style:normal;font-size:10px;color:var(--mix-t3,#5E6673);cursor:pointer;padding:0 3px;border-radius:3px}
.expbtn:hover,.expbtn.on{color:var(--mix-accent,#F0B90B);background:var(--mix-card2,#1E2329)}
.c-stage{width:104px}.c-sym{width:104px}.c-prod{width:52px}.c-src{width:56px}.c-ctl{width:44px}
.c-route{width:130px}.c-cap{width:84px}.c-ev{width:150px}.c-rs{width:64px}.c-risk{width:88px}
.c-next{flex:1 1 140px;min-width:120px}.c-act{width:170px;display:flex;justify-content:flex-end}
.strat .c-sym{width:118px;display:flex;flex-direction:column;line-height:1.15}
.strat .c-sym .sub{font-style:normal;font-size:8.5px;color:var(--mix-t3,#5E6673)}
.strat .c-route{width:96px}
.s-num{width:72px}.s-wide{width:96px}
/* 窄屏列瘦身:平板隐次要列,手机走 /m 专属壳 */
@media (max-width:1180px){.wtrow{min-width:0}.c-src,.c-ctl{display:none}}
@media (max-width:980px){.c-route,.c-rs{display:none}.c-ev{width:110px}}
@media (max-width:760px){.c-prod,.c-ev,.c-cap{display:none}.c-act{width:120px}.c-sym{flex:1 1 auto;min-width:80px}}
.r{text-align:right;font-variant-numeric:tabular-nums}
.ell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
b{color:var(--mix-t1,#EAECEF)}
.st{font-style:normal;font-size:10px;border:1px solid var(--mix-border,#262B33);border-radius:3px;padding:1px 6px;color:var(--mix-t2,#848E9C)}
.st.RECONCILING{color:#F6465D;border-color:#F6465D66}
.st.RESEARCH{color:#F0B90B;border-color:#F0B90B66}
.st.HOLDING,.st.EXECUTING{color:#35b57c;border-color:#35b57c55}
.st.EXITING{color:#FF8A3D;border-color:#FF8A3D66}
.rs{font-style:normal;font-size:9.5px;border:1px solid var(--mix-border,#262B33);border-radius:3px;padding:0 5px}
.rs.COMPLETED{color:#35b57c;border-color:#35b57c66}
.rs.PENDING{color:#F0B90B;border-color:#F0B90B66}
.rs.EXPIRED{color:#F6465D;border-color:#F6465D66}
.rs.dim{color:var(--mix-t3,#5E6673);border:none}
.rk-NORMAL{color:#35b57c}.rk-WATCH{color:#F0B90B}.rk-NO_NEW_RISK,.rk-NO_ADD{color:#FF8A3D}
.rk-REDUCE_ONLY,.rk-EXIT_ONLY,.rk-QUARANTINED,.rk-REDUCE_REQUIRED,.rk-EXIT_REQUIRED{color:#F6465D}
.up{color:#35b57c}.dn{color:#F6465D}.wr{color:#FF8A3D}
.wtfoot{flex:none;font-size:8.5px;color:var(--mix-t3,#5E6673);padding:4px 12px;border-top:1px solid var(--mix-border,#262B33)}
/* 腿子行块(§6A.14:与父行同一渲染块) */
:deep(.legblock){min-width:1150px;background:var(--mix-panel,#12151A);border-bottom:1px solid var(--mix-border,#262B33);padding:2px 12px 4px 30px;cursor:default}
:deep(.leghd2),:deep(.legrow2){display:grid;grid-template-columns:minmax(130px,1.5fr) 34px repeat(7,minmax(56px,1fr)) 56px;gap:4px;padding:2px 6px;align-items:center}
:deep(.leghd2){font-size:8.5px;color:var(--mix-t3,#5E6673);border-bottom:1px dashed var(--mix-border,#262B33)}
:deep(.legrow2){font-size:9.5px;color:var(--mix-t1,#EAECEF)}
:deep(.legrow2.ghost){opacity:.55}
:deep(.legrow2 span),:deep(.leghd2 span){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
:deep(.legrow2 .r){text-align:right;font-variant-numeric:tabular-nums}
:deep(.legrow2 .up){color:#35b57c}:deep(.legrow2 .dn){color:#F6465D}
</style>
