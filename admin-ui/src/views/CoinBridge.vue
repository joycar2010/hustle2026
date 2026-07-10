<template>
  <div class="card"><h3>coin 借币业务(只读桥接)</h3>
    <el-alert title="coin 引擎原地运行,此为旁车只读视图;操作合并见后续里程碑" type="info" :closable="false" style="margin-bottom:12px" />
    <el-table :data="rows" size="small" empty-text="coin 无在场仓位">
      <el-table-column prop="symbol" label="币" /><el-table-column prop="status" label="状态" />
      <el-table-column prop="borrow_qty" label="借币量" /><el-table-column prop="futures_long_qty" label="合约多" />
      <el-table-column prop="hedge_account" label="对冲账户" />
    </el-table></div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
onMounted(async () => { try { const d = await api.coinPositions(); rows.value = d.positions || [] } catch (e) {} })
</script>
