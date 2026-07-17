<template>
  <!-- V6.1 §2:账户与平台=账户/币种路由 页签(合并原 账户与托管 + 标的与路由;旧URL保留)。
       日常账户行优先;托管权限探针等专家诊断留在账户页内部折叠层。 -->
  <div class="acctplat">
    <el-tabs v-model="tab" class="ap-tabs">
      <el-tab-pane label="账户" name="accounts">
        <MixAccounts v-if="tab==='accounts' || touched.accounts"/>
      </el-tab-pane>
      <el-tab-pane label="币种与路由" name="coins">
        <MixCoins v-if="tab==='coins' || touched.coins"/>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import MixAccounts from './MixAccounts.vue'
import MixCoins from './MixCoins.vue'
const tab = ref('accounts')
const touched = ref({ accounts: true, coins: false })
watch(tab, t => { touched.value[t] = true })
</script>
<style scoped>
.acctplat{height:100%;display:flex;flex-direction:column;min-height:0}
.ap-tabs{flex:1;display:flex;flex-direction:column;min-height:0}
.ap-tabs :deep(.el-tabs__content){flex:1;overflow:auto;min-height:0}
.ap-tabs :deep(.el-tabs__header){margin:0 0 4px;padding:0 8px}
</style>
