<template>
  <!-- PATCH-02 §7:独立墙状态脚注+整页 STALE——墙订阅与主控台同一 generation 快照,
       过期时保留最后数据但整页醒目标注,绝不伪装实时。 -->
  <div class="wfoot">
    <span class="dot" :class="{on:wsOn && !stale}"></span>
    <b>{{ title }}</b>
    <span>PROD · gen {{ snap?.generation ?? '—' }}</span>
    <span>数据截至 {{ ago }}</span>
    <span>{{ wsOn ? 'WS 实时' : '轮询兜底' }}</span>
    <span class="fill"></span>
    <span class="ro">只读墙 · 无交易能力</span>
  </div>
  <div v-if="stale" class="wstale">
    <b><FIcon name="warn" :size="15"/> 数据已过期</b>
    <p>最后快照 {{ (snap?.as_of||'').replace('T',' ').slice(0,19) }} UTC · 以下为最后已知数据,非实时</p>
  </div>
</template>
<script setup>
import { watch } from 'vue'
import { useV6Snapshot } from '../../composables/useV6'
defineProps({ title: { type: String, default: '' } })
const emit = defineEmits(['gen'])
const { snap, stale, ago, wsOn } = useV6Snapshot()
watch(() => snap.value?.generation, (g, old) => { if (g != null && g !== old) emit('gen', g) })
defineExpose({ snap, stale })
</script>
<style scoped>
.wfoot{position:fixed;left:0;right:0;bottom:0;z-index:50;display:flex;align-items:center;gap:14px;
  height:26px;padding:0 14px;background:#0B0E11;border-top:1px solid #2B3139;
  font-size:10.5px;color:#B7BDC6}
.wfoot b{color:#EAECEF}
.wfoot .fill{flex:1}
.wfoot .ro{color:#5E6673}
.dot{width:7px;height:7px;border-radius:50%;background:#F6465D}
.dot.on{background:#0ECB81}
.wstale{position:fixed;left:0;right:0;top:0;z-index:60;background:#F6465DE0;color:#fff;
  text-align:center;padding:10px 0}
.wstale b{font-size:15px}
.wstale p{margin:2px 0 0;font-size:11px;opacity:.9}
</style>
