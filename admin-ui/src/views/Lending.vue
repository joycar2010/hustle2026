<template>
  <div class="card"><h3>借贷三率净差(日化%)</h3>
    <el-table :data="rows" size="small">
      <el-table-column prop="coin" label="币" />
      <el-table-column label="净差"><template #default="s"><span class="pos mono">{{ fmt(s.row.net_daily_pct, 3) }}</span></template></el-table-column>
      <el-table-column label="资金费"><template #default="s">{{ fmt(s.row.funding_abs, 3) }}</template></el-table-column>
      <el-table-column label="理财"><template #default="s">{{ fmt(s.row.earn, 3) }}</template></el-table-column>
      <el-table-column label="借币"><template #default="s">{{ fmt(s.row.borrow, 3) }}</template></el-table-column>
    </el-table></div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { fmt } from '../lib'
const rows = ref([])
onMounted(async () => { const o = await api.overview(); rows.value = (o.lending && o.lending.top) || [] })
</script>
