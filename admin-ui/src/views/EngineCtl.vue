<template>
  <div>
    <el-alert v-if="auth.role !== 'SUPER_ADMIN'" title="部分操作需 SUPER_ADMIN 权限,当前只读" type="warning" :closable="false" style="margin-bottom:12px" />
    <div class="card"><h3>引擎控制(dualperp)· 热配置</h3>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="模式"><el-tag :type="cfg.mode === 'armed' ? 'danger' : 'info'">{{ cfg.mode || 'shadow' }}</el-tag></el-descriptions-item>
        <el-descriptions-item label="白名单">{{ cfg.arm_symbols || '(空)' }}</el-descriptions-item>
        <el-descriptions-item label="单腿硬顶U">{{ cfg.max_notional_hard }}</el-descriptions-item>
        <el-descriptions-item label="组合上限U">{{ cfg.max_portfolio_notional }}</el-descriptions-item>
        <el-descriptions-item label="自动收敛">{{ cfg.auto_converge }}</el-descriptions-item>
      </el-descriptions>
      <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
        <el-button :type="cfg.mode === 'armed' ? 'info' : 'danger'" @click="toggleArm">{{ cfg.mode === 'armed' ? '解除武装(转shadow)' : '武装(armed)' }}</el-button>
        <el-button @click="editSet('arm_symbols', '白名单(逗号分隔)')">改白名单</el-button>
        <el-button @click="editSet('max_notional_hard', '单腿硬顶U')">改单腿硬顶</el-button>
        <el-button @click="editSet('max_portfolio_notional', '组合上限U')">改组合上限</el-button>
        <el-button @click="editSet('auto_converge', '自动收敛 true/false')">自动收敛</el-button>
        <el-button type="danger" plain @click="kill" style="margin-left:auto">🛑 Kill Switch</el-button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { useAuth } from '../store/auth'
const cfg = reactive({}); const auth = useAuth()
async function load() {
  const d = await api.config(); auth.setMe(d.me)
  const m = {}; d.config.filter(c => c.engine === 'dualperp').forEach(c => (m[c.key] = c.val)); Object.assign(cfg, m)
}
async function setKey(key, val, extra = {}) {
  try { await api.setConfig('dualperp', key, val, extra); ElMessage.success(key + '=' + val); await load() }
  catch (e) {
    const s = e.status, msg = (e.data && e.data.error) || '失败'
    if (s === 409) ElMessage.error('武装联锁:风控未全绿'); else if (s === 403) ElMessage.error('权限不足'); else ElMessage.error(msg)
  }
}
async function toggleArm() {
  if (cfg.mode === 'armed') { await setKey('mode', 'shadow'); return }
  try {
    await ElMessageBox.prompt('武装将允许真金下单。确认请输入 ARM', '⚠️ 武装确认',
      { confirmButtonText: '武装', type: 'warning', inputValidator: v => v === 'ARM' || '请输入 ARM' })
    await setKey('mode', 'armed', { confirm: 'ARM' })
  } catch (e) {}
}
async function editSet(key, label) {
  try { const { value } = await ElMessageBox.prompt(label, '修改 ' + key, { inputValue: cfg[key] || '' }); await setKey(key, value) } catch (e) {}
}
async function kill() {
  try {
    await ElMessageBox.confirm('全组合置 shadow + 清空白名单(停止新开仓)。存量仓位需去路由页平仓。', '🛑 全局急停', { confirmButtonText: '确认急停', type: 'error' })
    await api.kill(); ElMessage.warning('已急停'); await load()
  } catch (e) { if (e && e.status) ElMessage.error('需 SUPER_ADMIN') }
}
onMounted(load)
</script>
