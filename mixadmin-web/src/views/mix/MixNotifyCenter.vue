<template>
  <!-- V6.1 §2/§7:通知模块=原通知全功能 + 网站维护排空并入(维护是编排任务;风险权威分离不变)。 -->
  <div class="notifycenter">
    <el-tabs v-model="tab" class="nc-tabs">
      <el-tab-pane label="通知与渠道" name="notify">
        <MixNotify v-if="tab==='notify' || touched.notify"/>
      </el-tab-pane>
      <el-tab-pane label="网站维护与排空" name="maintenance">
        <MixMaintenance v-if="tab==='maintenance' || touched.maintenance"/>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import MixNotify from './MixNotify.vue'
import MixMaintenance from './MixMaintenance.vue'
const tab = ref('notify')
const touched = ref({ notify: true, maintenance: false })
watch(tab, t => { touched.value[t] = true })
</script>
<style scoped>
.notifycenter{height:100%;display:flex;flex-direction:column;min-height:0}
.nc-tabs{flex:1;display:flex;flex-direction:column;min-height:0}
.nc-tabs :deep(.el-tabs__content){flex:1;overflow:auto;min-height:0}
.nc-tabs :deep(.el-tabs__header){margin:0 0 4px;padding:0 8px}
</style>
