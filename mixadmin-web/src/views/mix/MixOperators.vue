<template>
  <div class="mixops">
    <div class="card">
      <div class="chd"><b>操作员（dcm operators · 权威表只读）</b></div>
      <div class="tr th"><span>名称</span><span>角色</span><span>状态</span><span>最近使用</span></div>
      <div v-for="o in data.operators || []" :key="o.name" class="tr">
        <span>{{ o.name }}</span>
        <span><el-tag size="small" :type="o.role==='SUPER_ADMIN'?'warning':'info'" effect="plain">{{ o.role }}</el-tag></span>
        <span><i class="dot" :class="{bad: !o.enabled}"></i>{{ o.enabled ? '启用' : '停用' }}</span>
        <span class="dim">{{ o.last_seen }}</span>
      </div>
      <div class="fnote">{{ data.note }}</div>
    </div>

    <div class="card">
      <div class="chd"><b>Mix 用户（用户端账号 · 范围隔离）</b>
        <el-button size="small" type="warning" @click="showCreate=true">开户</el-button>
      </div>
      <div class="tr th u"><span>账号</span><span>角色</span><span>绑定范围</span><span class="r">范围内权益U</span><span>最近登录</span><span>操作</span></div>
      <div v-for="u in data.users || []" :key="u.id" class="tr u">
        <span><b>{{ u.username }}</b></span>
        <span>{{ u.role }}</span>
        <span class="dim">{{ u.scopes.length ? u.scopes.join('/') : (u.role==='owner'||u.role==='admin' ? '全量' : '未绑定=零数据') }}</span>
        <span class="r">{{ u.scope_equity.toLocaleString() }}</span>
        <span class="dim">{{ u.last_login || '—' }}</span>
        <span class="acts">
          <el-link size="small" @click="editRole(u)">改角色</el-link>
          <el-link size="small" @click="editScopes(u)">改范围</el-link>
          <el-link size="small" @click="resetPwd(u)">重置密码</el-link>
          <el-link size="small" :type="u.enabled?'danger':'success'" @click="toggle(u)">{{ u.enabled?'停用':'启用' }}</el-link>
        </span>
      </div>
    </div>

    <el-dialog v-model="showCreate" title="开户（默认拒绝：不绑范围=零数据）" width="420">
      <el-input v-model="nu.username" placeholder="账号" style="margin-bottom:8px" />
      <el-input v-model="nu.password" placeholder="密码" show-password style="margin-bottom:8px" />
      <el-select v-model="nu.role" style="width:100%;margin-bottom:8px">
        <el-option value="user" label="user（范围隔离）" /><el-option value="owner" label="owner（全量）" />
      </el-select>
      <el-select v-model="nu.scopes" multiple placeholder="绑定交易所范围" style="width:100%">
        <el-option v-for="v in venues" :key="v" :value="v" :label="v" />
      </el-select>
      <template #footer>
        <el-button type="warning" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const venues = ['binance', 'bybit', 'okx', 'gate', 'bitget', 'hyperliquid']
const data = ref({}); const showCreate = ref(false)
const nu = ref({ username: '', password: '', role: 'user', scopes: [] })

async function load() { try { data.value = await mixApi.operatorsAll() } catch (e) { ElMessage.error(e?.detail || '加载失败') } }
async function create() {
  try {
    await mixApi.userCreate(nu.value)
    ElMessage.success('已开户'); showCreate.value = false; load()
  } catch (e) { ElMessage.error(e?.detail || '失败（需 SUPER_ADMIN）') }
}
async function toggle(u) {
  try { await mixApi.userUpdate(u.id, { enabled: !u.enabled }); load() }
  catch (e) { ElMessage.error(e?.detail || '失败') }
}
async function editScopes(u) {
  try {
    const { value } = await ElMessageBox.prompt('逗号分隔的交易所范围（留空=清空）', `改范围: ${u.username}`,
      { inputValue: u.scopes.join(',') })
    await mixApi.userUpdate(u.id, { scopes: value ? value.split(',').map(s => s.trim()).filter(Boolean) : [] })
    ElMessage.success('已更新'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function editRole(u) {
  try {
    const { value } = await ElMessageBox.prompt('角色: user(范围隔离) / operator / admin / owner(全量)',
      `改角色: ${u.username}`, { inputValue: u.role, inputPattern: /^(user|operator|admin|owner)$/, inputErrorMessage: '仅 user/operator/admin/owner' })
    await mixApi.userUpdate(u.id, { role: value })
    ElMessage.success('已更新'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function resetPwd(u) {
  try {
    const { value } = await ElMessageBox.prompt('新密码', `重置密码: ${u.username}`, { inputType: 'password' })
    if (value) { await mixApi.userUpdate(u.id, { password: value }); ElMessage.success('已重置') }
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
onMounted(load)
</script>

<style scoped lang="scss">
.mixops { display: flex; flex-direction: column; gap: 12px; max-width: 1100px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 14px; }
.chd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; b { font-size: 13px; } }
.tr { display: grid; grid-template-columns: 160px 130px 110px 1fr; gap: 8px; font-size: 12px; padding: 4px 0; align-items: center;
  &.u { grid-template-columns: 120px 70px 1fr 110px 100px 230px; }
  &.th { color: var(--mix-t3, #5E6673); font-weight: 700; } }
.dim { color: var(--mix-t2, #848E9C); }
.r { text-align: right; }
.acts { display: flex; gap: 10px; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #0ECB81; margin-right: 5px; &.bad { background: #5E6673; } }
.fnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-top: 6px; }
</style>
