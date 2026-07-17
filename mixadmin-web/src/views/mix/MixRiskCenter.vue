<template>
  <!-- V6.1 §2:风险中心=事故/平台/暂停隔离页签(合并原 平台与账户风险 + 准入与隔离;旧URL保留) -->
  <div class="riskcenter">
    <el-tabs v-model="tab" class="rc-tabs">
      <!-- REV4 批C §6B:账户与保证金汇总首屏页签(交互式P3;与 /wall/risk 同一快照) -->
      <el-tab-pane label="账户与保证金" name="margin">
        <div class="mpad"><RiskAccountTable v-if="tab==='margin' || touched.margin"/></div>
      </el-tab-pane>
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
import RiskAccountTable from '../../components/v62/RiskAccountTable.vue'
const tab = ref('margin')
const touched = ref({ margin: true, venue: false, quarantine: false })
watch(tab, t => { touched.value[t] = true })
</script>
<style scoped>
.riskcenter{height:100%;display:flex;flex-direction:column;min-height:0}
.rc-tabs{flex:1;display:flex;flex-direction:column;min-height:0}
.rc-tabs :deep(.el-tabs__content){flex:1;overflow:auto;min-height:0}
.rc-tabs :deep(.el-tabs__header){margin:0 0 4px;padding:0 8px}
.mpad{padding:4px 8px 12px}
</style>
