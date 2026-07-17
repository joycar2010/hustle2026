<template>
  <!-- V6.2 ValueCell(帧 u9Uw0 七态):真0≠无值≠未接入,视觉可区分(§6.2 八态契约) -->
  <span class="vc" :class="cls" :title="hint">{{ text }}</span>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({
  value: [Number, String],
  state: String,            // 九态: PRESENT/ZERO/NOT_APPLICABLE/NOT_CONNECTED/NOT_YET_AVAILABLE/WAITING_INPUT/STALE/UNDER_REVIEW/ERROR
  suffix: { type: String, default: '' },
  dp: { type: Number, default: 2 },
  reason: { type: String, default: '' },   // 机器原因码/人话原因,进悬停提示
})
const CN = { NOT_APPLICABLE: '—', NOT_CONNECTED: '未接入', NOT_YET_AVAILABLE: '待产生',
             WAITING_INPUT: '待计算', STALE: '已过期', UNDER_REVIEW: '核对中', ERROR: '暂不可得' }
const fmt = (v) => {
  const n = Number(v)
  // 字符串值(如上市时间 2017-08)原样显示,不做 Number 化(NaN 冒充数字=裸N/A同罪)
  if (typeof v === 'string' && (Number.isNaN(n) || v.trim() === '' || /[^0-9.eE+-]/.test(v))) return v
  return n.toLocaleString(undefined, { maximumFractionDigits: props.dp })
}
const text = computed(() => {
  if (props.value != null && props.state !== 'STALE' && props.state !== 'ERROR')
    return fmt(props.value) + props.suffix
  if (props.state === 'STALE' && props.value != null)
    return fmt(props.value) + props.suffix + '⌛'
  return CN[props.state] || '—'
})
const cls = computed(() => ({
  NOT_CONNECTED: 'nc', NOT_YET_AVAILABLE: 'wait', WAITING_INPUT: 'wait', STALE: 'stale',
  UNDER_REVIEW: 'review', ERROR: 'err', NOT_APPLICABLE: 'na',
}[props.state] || ''))
const hint = computed(() => {
  const base = {
    NOT_CONNECTED: '数据源未接入,不显示假数据', NOT_YET_AVAILABLE: '等待产生/结算',
    WAITING_INPUT: '需要产品/路线/金额后计算', STALE: '数据更新延迟,显示最后值',
    UNDER_REVIEW: '账目核对中', ERROR: '数据源暂时故障',
  }[props.state] || ''
  return props.reason ? (base ? `${base} · ${props.reason}` : props.reason) : base
})
</script>
<style scoped>
.vc{font-variant-numeric:tabular-nums;font-weight:700;color:var(--mix-t1,#EAECEF);white-space:nowrap}
.vc.na,.vc.nc{color:var(--mix-t3,#5E6673);font-weight:400}
.vc.wait{color:#F0B90B;font-weight:400}
.vc.stale,.vc.err{color:#F6465D}
.vc.review{color:#F0B90B}
</style>
