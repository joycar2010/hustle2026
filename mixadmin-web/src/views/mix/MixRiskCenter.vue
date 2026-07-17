<template>
  <!-- V6.1 §2:风险中心=事故/平台/暂停隔离页签(合并原 平台与账户风险 + 准入与隔离;旧URL保留) -->
  <div class="riskcenter">
    <el-tabs v-model="tab" class="rc-tabs">
      <el-tab-pane label="平台与账户风险" name="venue">
        <MixVenueRisk v-if="tab==='venue' || touched.venue"/>
      </el-tab-pane>
      <el-tab-pane label="暂停与隔离" name="quarantine">
        <MixBlacklist v-if="tab==='quarantine' || touched.quarantine"/>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import MixVenueRisk from './MixVenueRisk.vue'
import MixBlacklist from './MixBlacklist.vue'
const tab = ref('venue')
const touched = ref({ venue: true, quarantine: false })
watch(tab, t => { touched.value[t] = true })
</script>
<style scoped>
.riskcenter{height:100%;display:flex;flex-direction:column;min-height:0}
.rc-tabs{flex:1;display:flex;flex-direction:column;min-height:0}
.rc-tabs :deep(.el-tabs__content){flex:1;overflow:auto;min-height:0}
.rc-tabs :deep(.el-tabs__header){margin:0 0 4px;padding:0 8px}
</style>
