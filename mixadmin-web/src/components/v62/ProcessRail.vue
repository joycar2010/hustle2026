<template>
  <!-- V6.2 ProcessRail(帧 eTSxn 五态):机会→审批→执行→持有→退出与还币→核对;异常置顶红 -->
  <div class="rail">
    <template v-for="(s,i) in steps" :key="s.key">
      <div class="step" :class="s.state" @click="$emit('pick', s.key)">
        <b>{{ s.label }}<i v-if="s.count!=null" class="n">{{ s.count }}</i></b>
        <span>{{ STCN[s.state] }}{{ s.note ? ' · '+s.note : '' }}</span>
      </div>
      <span v-if="i<steps.length-1" class="arr">›</span>
    </template>
  </div>
</template>
<script setup>
defineProps({ steps: { type: Array, required: true } })
// steps: [{key,label,count,state:'todo|current|done|error|blocked',note?}]
defineEmits(['pick'])
const STCN = { todo: '未开始', current: '当前', done: '完成', error: '异常', blocked: '受阻' }
</script>
<style scoped>
.rail{display:flex;align-items:center;gap:4px;width:100%}
.step{flex:1;min-width:0;height:44px;border-radius:6px;border:1px solid var(--mix-border,#2B3139);
  background:var(--mix-panel,#12151A);display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:1px;cursor:pointer;overflow:hidden;transition:border-color .12s}
.step b{font-size:11px;color:var(--mix-t3,#5E6673);display:flex;gap:5px;align-items:center;white-space:nowrap}
.step span{font-size:8.5px;color:var(--mix-t3,#5E6673);white-space:nowrap}
.step .n{font-style:normal;font-size:9px;background:var(--mix-card2,#20242C);border-radius:7px;padding:0 6px}
.step.done{background:#0ECB810F}.step.done b{color:#0ECB81}
.step.current{background:#F0B90B1F;border-color:#F0B90B4D}.step.current b{color:#F0B90B}
.step.error{background:#F6465D14;border-color:#F6465D66}.step.error b{color:#F6465D}
.step.error .n{background:#F6465D26;color:#F6465D}
.step.blocked{background:#FF8A3D14;border-color:#FF8A3D66}.step.blocked b{color:#FF8A3D}
.step:hover{border-color:#F0B90B}
.arr{color:var(--mix-t3,#5E6673);flex:none;font-size:12px}
@media (max-width:760px){ .step span{display:none} .step{height:36px} }
</style>
