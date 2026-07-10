<template>
  <div class="card"><h3>活跃路由</h3>
    <el-table :data="rows" size="small" empty-text="无活跃路由">
      <el-table-column prop="symbol" label="币" /><el-table-column prop="engine" label="引擎" />
      <el-table-column prop="venues" label="venue" /><el-table-column prop="target" label="目标U" />
      <el-table-column prop="by" label="来源" />
      <el-table-column label="操作" width="120"><template #default="s"><el-button size="small" type="danger" plain @click="off(s.row)">平仓(off)</el-button></template></el-table-column>
    </el-table></div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const rows = ref([])
async function load() { const o = await api.overview(); rows.value = o.routes_active || [] }
async function off(r) {
  try {
    await ElMessageBox.confirm('将 ' + r.symbol + ' 路由置 off(引擎平掉该配对)', '确认', { type: 'warning' })
    const [vl, vs] = r.venues.split('/')
    await api.routeOff({ symbol: r.symbol, engine: 'dualperp', venue_long: vl, market_long: 'perp', venue_short: vs, market_short: 'perp', target_notional_usdt: 0, state: 'off', reason: 'admin off' })
    ElMessage.success('已置off'); setTimeout(load, 1500)
  } catch (e) { if (e && e.status === 403) ElMessage.error('需 OPERATOR') }
}
onMounted(load)
</script>
