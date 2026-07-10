<template>
  <div class="card"><h3>coin 借币业务(桥接 + 代理操作)</h3>
    <el-alert title="coin 引擎原地运行;状态只读桥接,启停经 gateway→coin-bridge→coin FastAPI 代理(coin 逻辑权威,全审计)" type="info" :closable="false" style="margin-bottom:12px" />
    <div style="margin-bottom:12px;display:flex;gap:10px">
      <el-button plain :loading="busy" @click="status">查询引擎状态</el-button>
      <el-button type="success" plain :loading="busy" @click="cmd('engine_start', '启动 coin 引擎')">启动引擎</el-button>
      <el-button type="danger" plain :loading="busy" @click="cmd('engine_stop', '停止 coin 引擎')">停止引擎</el-button>
    </div>
    <el-table v-if="workers.length" :data="workers" size="small" style="margin-bottom:12px">
      <el-table-column prop="scope" label="worker" width="90" /><el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="active_positions" label="在场仓" width="80" /><el-table-column prop="total_cycles" label="循环数" width="100" />
      <el-table-column prop="last_heartbeat" label="心跳" width="200" />
      <el-table-column prop="error_message" label="错误" show-overflow-tooltip />
    </el-table>
    <el-table :data="rows" size="small" empty-text="coin 无在场仓位">
      <el-table-column prop="symbol" label="币" /><el-table-column prop="status" label="状态" />
      <el-table-column prop="borrow_qty" label="借币量" /><el-table-column prop="futures_long_qty" label="合约多" />
      <el-table-column prop="hedge_account" label="对冲账户" />
    </el-table></div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const rows = ref([]); const busy = ref(false); const workers = ref([])
async function load() { try { const d = await api.coinPositions(); rows.value = d.positions || [] } catch (e) {} }
async function status() {
  busy.value = true
  try {
    const d = await api.coinCommand('engine_status')
    if (d.result && d.result.ok) { workers.value = (d.result.body && d.result.body.workers) || []; ElMessage.success('已刷新') }
    else ElMessage.warning(JSON.stringify(d.note || d.result))
  } catch (e) { if (e && e.status === 403) ElMessage.error('需 OPERATOR') }
  finally { busy.value = false }
}
async function cmd(action, label) {
  try {
    await ElMessageBox.confirm(label + '?(经 coin FastAPI 执行)', '确认', { type: 'warning' })
    busy.value = true
    const d = await api.coinCommand(action)
    const ok = d.result && d.result.ok
    ElMessage[ok ? 'success' : 'warning']((ok ? '已执行:' : '已入队(结果:') + JSON.stringify((d.result && d.result.body) || d.note || d.result))
  } catch (e) { if (e && e.status === 403) ElMessage.error('需 OPERATOR') }
  finally { busy.value = false; setTimeout(load, 1500) }
}
onMounted(load)
</script>
