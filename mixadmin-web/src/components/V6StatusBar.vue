<template>
  <!-- V6·状态条(设计帧 oYozr 1:1):环境|网站状态|允许操作|最高提醒|数据截至 ‖ operator -->
  <div class="v6bar">
    <div class="l">
      <span class="chip env">{{ snap?.environment === 'DEX_LAB' ? 'LAB' : 'PROD' }}</span>
      <span class="chip" :class="siteOk ? 'ok' : 'warn'">
        <FIcon name="wifi" :size="11"/>网站：{{ siteText }}
      </span>
      <span class="chip" :class="capClass">
        <FIcon :name="{ok:'check',watch:'eye',nonew:'pause',reduce:'block',maint:'tool',stale:'clock',training:'cap'}[mode7]" :size="11"/>当前允许操作：{{ capText }}
      </span>
      <span v-if="topAlert" class="chip alert">
        <FIcon name="alert" :size="11"/>最高提醒：{{ topAlert }}
      </span>
      <span class="sep"></span>
      <span class="asof"><i>数据截至</i><b :class="{staleTxt:stale}">{{ asofText }}（{{ ago }}）</b></span>
      <span v-if="stale" class="chip alert">快照过期·已禁止新增风险(fail-closed)</span>
    </div>
    <div class="r">
      <span class="op"><FIcon name="user" :size="12"/>{{ operator || 'operator' }}<em v-if="elevNote">{{ elevNote }}</em></span>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({
  snap: Object, stale: Boolean, canOpen: Boolean, ago: String,
  operator: { type: String, default: '' }, elevNote: { type: String, default: '' },
  training: Boolean,   // N4 训练模式接入点
})
const siteOk = computed(() => ['NORMAL', 'CLOSED', undefined].includes(props.snap?.site_maintenance_state))
const siteText = computed(() => {
  const s = props.snap?.site_maintenance_state
  return ({ NORMAL: '正常', CLOSED: '正常', ANNOUNCED: '已公告维护', DRAINING: '排空中',
            DRAIN_BLOCKED: '排空阻塞', MAINTENANCE: '维护中', RECOVERY_CHECK: '恢复检查' })[s] || (s ?? 'N/A')
})
// V6.2 七态(帧 B7J44C):正常/观察/暂停新增/只减仓/维护/过期/训练
const mode7 = computed(() => {
  if (props.training) return 'training'
  if (props.stale) return 'stale'
  const s = props.snap
  const ms = s?.site_maintenance_state
  if (ms && !['NORMAL', 'CLOSED'].includes(ms)) return 'maint'
  const rc = s?.effective_capabilities?.risk_capability
  if (rc === 'REDUCE_ONLY' || rc === 'EXIT_ONLY') return 'reduce'
  if (rc === 'NO_NEW_RISK') return 'nonew'
  if (s?.top_alert || (s?.incidents || []).length) return 'watch'
  return 'ok'
})
const capText = computed(() => ({
  training: '训练模式 · 回放数据,不产生真实订单',
  stale: '受限（快照过期>90s,禁新增;减险不受影响）',
  maint: '维护排空中 · 禁新增,减险放行',
  reduce: '只允许减仓和还币',
  nonew: '暂停开新仓 · 仍可撤单/减仓/买回/还币',
  watch: '全部（观察中·期望已计风险扣减）',
  ok: '全部（正常运行）',
}[mode7.value]))
const capClass = computed(() => ({
  training: 'info', stale: 'alert2', maint: 'warn', reduce: 'alert2',
  nonew: 'warn', watch: 'watchc', ok: 'ok',
}[mode7.value]))
const topAlert = computed(() => {
  const t = props.snap?.top_alert
  return t ? `${t.severity === 'fatal' ? 'P0' : 'P1'} · ${t.title || t.venue}` : ''
})
const asofText = computed(() => {
  if (!props.snap?.as_of) return 'N/A'
  const d = new Date(props.snap.as_of)
  return d.toTimeString().slice(0, 8)
})
</script>
<style scoped>
.v6bar{min-height:40px;background:var(--mix-panel);border-bottom:1px solid var(--mix-border);
  display:flex;align-items:center;justify-content:space-between;padding:2px 14px;gap:10px;flex:none}
.l,.r{display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:700;
  padding:3px 8px;border-radius:4px;white-space:nowrap}
.chip .ico{font-size:10px;font-style:normal}
.chip.env{background:#F6465D26;color:var(--mix-red)}
.chip.ok{background:#0ECB8114;color:var(--mix-green)}
.chip.warn{background:#FF8A3D1F;color:#FF8A3D}
.chip.alert{background:#F6465D14;color:var(--mix-red);border:1px solid #F6465D66}
.chip.alert2{background:#F6465D14;color:var(--mix-red)}
.chip.watchc{background:#F0B90B14;color:var(--mix-accent)}
.chip.info{background:#4A9CFF14;color:var(--mix-blue)}
.sep{width:1px;height:16px;background:var(--mix-border)}
.asof{display:flex;gap:5px;align-items:center;font-size:10px}
.asof i{color:var(--mix-t3);font-style:normal}
.asof b{color:var(--mix-t1);font-size:10.5px}
.asof b.staleTxt{color:var(--mix-red)}
.op{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--mix-t1)}
.op i{font-style:normal;font-size:12px}
.op em{color:var(--mix-t3);font-style:normal;font-size:9.5px}
/* §8 验收:390×844 无溢出——状态条自动换行/收敛,窄屏隐藏次要 chip */
@media (max-width:760px){
  .v6bar{padding:2px 8px;gap:6px}
  .l{gap:5px}
  .sep,.r .op em{display:none}
  .chip{font-size:10px;padding:2px 6px}
}
@media (max-width:480px){
  .r{display:none}
  .asof i{display:none}
}
</style>
