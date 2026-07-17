<template>
  <!-- V6.2 统一工作项深表格(补丁§8):今日工作 /mix/work?view=table 的表格视图。
       与轻列表同一 WorkItem 单一事实;表头表体同滚动容器+sticky(横滚表头跟随课);
       行 min-width 兜底防 125%DPI 夹层列漂移(V6 上线四修课)。 -->
  <div class="wt">
    <div class="wtscroll">
      <div class="wthead wtrow">
        <span class="c-stage">阶段</span><span class="c-sym">币种</span><span class="c-prod">产品</span>
        <span class="c-src">来源</span><span class="c-ctl">控制</span><span class="c-route">路线</span>
        <span class="c-cap r">投入</span><span class="c-ev r">预计/确认收益</span>
        <span class="c-rs">研判</span><span class="c-risk">风险</span>
        <span class="c-next">下一步</span><span class="c-act">主操作</span>
      </div>
      <div v-for="w in sorted" :key="w.work_item_id" class="wtrow" :class="{sel:selId===w.work_item_id, bad:w.workflow_stage==='RECONCILING'}"
           @click="$emit('open', w)">
        <span class="c-stage"><i class="st" :class="w.workflow_stage">{{ w.stage_detail || STAGE_CN[w.workflow_stage] || w.workflow_stage }}</i></span>
        <span class="c-sym"><b>{{ w.symbol }}</b></span>
        <span class="c-prod">{{ w.strategy_code }}</span>
        <span class="c-src">{{ SRC_CN[w.source] || w.source }}</span>
        <span class="c-ctl">{{ CTL_CN[w.automation_mode] || w.automation_mode || '—' }}</span>
        <span class="c-route ell" :title="w.route||''">{{ w.route || '—' }}</span>
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
      <EmptyState v-if="!sorted.length" kind="none" title="当前队列无工作项" hint="点流程条其它分段查看"/>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import ValueCell from './ValueCell.vue'
import PrimaryAction from './PrimaryAction.vue'
import EmptyState from './EmptyState.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  rowState: { type: Object, default: () => ({}) },
  selId: { type: String, default: '' },
})
defineEmits(['open', 'run'])

const STAGE_CN = { DISCOVERED: '候选', RESEARCH: '人工研判', REVIEW: '审批', RESERVED: '已批准',
                   EXECUTING: '执行中', HOLDING: '持有', EXITING: '退出', RECONCILING: '异常' }
const SRC_CN = { opener: '顾问', proposal: '提案', manager: '内核', coin: 'C3引擎', repair: '修复', research: '研判' }
const CTL_CN = { AUTO: '自动', ASSISTED: '辅助', MANUAL: '手动' }
const RS_CN = { PENDING: '待完成', COMPLETED: '已完成', EXPIRED: '已过期' }
const PROT_CN = { WATCH: '观察', NO_ADD: '禁加仓', REDUCE_REQUIRED: '需减仓', EXIT_REQUIRED: '需退出' }
const ORDER = { RECONCILING: 0, RESEARCH: 1, REVIEW: 2, RESERVED: 3, EXECUTING: 4, HOLDING: 5, EXITING: 6, DISCOVERED: 7 }
const sorted = computed(() => props.items.slice().sort((a, b) =>
  (ORDER[a.workflow_stage] ?? 9) - (ORDER[b.workflow_stage] ?? 9) || String(a.symbol).localeCompare(String(b.symbol))))
function primaryOf(w) { const a = w.allowed_actions || []; return a.find(x => x.kind === 'primary') || a[0] || null }
</script>
<style scoped>
.wt{flex:1;min-height:0;display:flex;flex-direction:column;background:var(--mix-card,#181B21);
  border:1px solid var(--mix-border,#262B33);border-radius:10px;overflow:hidden}
.wtscroll{flex:1;overflow:auto}
.wtrow{display:flex;align-items:center;gap:8px;min-width:1150px;padding:0 12px;min-height:34px;
  border-bottom:1px solid var(--mix-border,#262B33);font-size:11px;color:var(--mix-t2,#848E9C);cursor:pointer}
.wtrow:hover{background:rgba(240,185,11,.04)}
.wtrow.sel{background:rgba(240,185,11,.08)}
.wtrow.bad{background:rgba(246,70,93,.06)}
.wthead{position:sticky;top:0;z-index:2;background:var(--mix-card,#181B21);color:var(--mix-t3,#5E6673);
  font-size:10px;min-height:26px;cursor:default}
.wtrow>span{flex-shrink:0;min-width:0}
.c-stage{width:104px}.c-sym{width:104px}.c-prod{width:52px}.c-src{width:56px}.c-ctl{width:44px}
.c-route{width:130px}.c-cap{width:84px}.c-ev{width:150px}.c-rs{width:64px}.c-risk{width:88px}
.c-next{flex:1 1 140px;min-width:120px}.c-act{width:170px;display:flex;justify-content:flex-end}
/* 窄屏列瘦身(B5):平板隐次要列,手机走 /m 专属壳——此表只保证平板可用。
   ≤1180 收 来源/控制;≤980 收 路线/研判;≤760 收 产品/预计收益(只留 币种/阶段/投入/风险/主操作) */
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
</style>
