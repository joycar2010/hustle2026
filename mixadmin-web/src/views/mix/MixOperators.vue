<template>
  <div class="mixops">
    <el-tabs v-model="tab" class="otabs">
      <!-- ① 操作员 / 用户 -->
      <el-tab-pane label="操作员 / 用户" name="users">
        <div class="card">
          <div class="chd"><b>dcm 操作员（权威表 · 只读）</b></div>
          <div class="tr th"><span>名称</span><span>角色</span><span>状态</span><span>最近使用</span></div>
          <div v-for="o in data.operators || []" :key="o.name" class="tr">
            <span>{{ o.name }}</span>
            <span><el-tag size="small" :type="o.role==='SUPER_ADMIN'?'warning':'info'" effect="plain">{{ roleCn(o.role) }}</el-tag></span>
            <span><i class="dot" :class="{bad: !o.enabled}"></i>{{ o.enabled ? '启用' : '停用' }}</span>
            <span class="dim">{{ o.last_seen }}</span>
          </div>
          <div class="fnote">{{ data.note }}</div>
        </div>

        <div class="card">
          <div class="chd"><b>Mix 用户（可管理 · 范围隔离 + IP 白名单）</b>
            <el-button size="small" type="warning" @click="showCreate=true">新增操作员</el-button>
          </div>
          <div class="tr th u"><span>账号</span><span>角色</span><span>绑定范围</span><span>IP白名单</span><span class="r">权益U</span><span>最近登录</span><span>操作</span></div>
          <div v-for="u in data.users || []" :key="u.id" class="tr u">
            <span><b>{{ u.username }}</b></span>
            <span>{{ roleCn(u.role) }}</span>
            <span class="dim">{{ u.scopes.length ? u.scopes.join('/') : (u.role==='owner'||u.role==='admin' ? '全量' : '未绑定') }}</span>
            <span class="dim">{{ u.ip_whitelist || '不限' }}</span>
            <span class="r">{{ (u.scope_equity||0).toLocaleString() }}</span>
            <span class="dim">{{ u.last_login || '—' }}</span>
            <span class="acts">
              <el-link size="small" @click="editRole(u)">改角色</el-link>
              <el-link size="small" @click="editScopes(u)">改范围</el-link>
              <el-link size="small" @click="editIp(u)">IP白名单</el-link>
              <el-link size="small" @click="resetPwd(u)">重置密码</el-link>
              <el-link size="small" :type="u.enabled?'danger':'success'" @click="toggle(u)">{{ u.enabled?'停用':'启用' }}</el-link>
            </span>
          </div>
        </div>
      </el-tab-pane>

      <!-- ② 角色权限矩阵 -->
      <el-tab-pane label="角色权限矩阵" name="roles">
        <div class="card">
          <div class="chd"><b>角色 · 可见模块（可自定义）</b>
            <el-button size="small" type="warning" @click="editRoleDlg()">新增角色</el-button>
            <el-button size="small" @click="loadRoles">刷新</el-button>
          </div>
          <el-table :data="roles" size="small">
            <el-table-column prop="role_key" label="角色键" width="120" />
            <el-table-column prop="name" label="名称" width="110" />
            <el-table-column label="可见模块" min-width="360">
              <template #default="{row}">
                <span v-if="(row.modules||[]).includes('*')" class="allmod">全部模块</span>
                <template v-else>
                  <el-tag v-for="m in row.modules" :key="m" size="small" effect="plain" style="margin:1px">{{ m }}</el-tag>
                </template>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="70">
              <template #default="{row}"><el-tag size="small" :type="row.is_builtin?'info':'warning'" effect="plain">{{ row.is_builtin?'内置':'自定义' }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{row}">
                <el-button size="small" link type="warning" @click="editRoleDlg(row)">编辑</el-button>
                <el-button size="small" link type="danger" :disabled="row.is_builtin" @click="delRole(row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ③ 操作员行为日志 -->
      <el-tab-pane label="操作员行为日志" name="audit">
        <div class="card">
          <div class="chd"><b>行为日志（admin_audit 全量留痕）</b><el-button size="small" @click="loadAudit">刷新</el-button></div>
          <el-table :data="audit" size="small" max-height="520">
            <el-table-column prop="at" label="时间" width="140" />
            <el-table-column prop="operator" label="操作员" width="120" />
            <el-table-column label="角色" width="100"><template #default="{row}">{{ roleCn(row.role) }}</template></el-table-column>
            <el-table-column prop="action" label="操作" width="150" />
            <el-table-column prop="target" label="对象" min-width="140" show-overflow-tooltip />
            <el-table-column prop="result" label="结果" min-width="160" show-overflow-tooltip />
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 开户 -->
    <el-dialog v-model="showCreate" title="开户（默认拒绝：不绑范围=零数据）" width="440">
      <el-input v-model="nu.username" placeholder="账号" style="margin-bottom:8px" />
      <el-input v-model="nu.password" placeholder="密码" show-password style="margin-bottom:8px" autocomplete="new-password" />
      <el-select v-model="nu.role" style="width:100%;margin-bottom:8px">
        <el-option v-for="r in roles" :key="r.role_key" :value="r.role_key" :label="`${r.name}（${r.role_key}）`" />
      </el-select>
      <el-select v-model="nu.scopes" multiple placeholder="绑定交易所范围" style="width:100%">
        <el-option v-for="v in venues" :key="v" :value="v" :label="v" />
      </el-select>
      <template #footer><el-button @click="showCreate=false">取消</el-button><el-button type="warning" @click="create">创建</el-button></template>
    </el-dialog>

    <!-- 角色编辑 -->
    <el-dialog v-model="roleDlg" :title="rf.is_builtin?'编辑内置角色（仅改可见模块）':'角色编辑'" width="520">
      <el-form label-width="80">
        <el-form-item label="角色键"><el-input v-model="rf.role_key" :disabled="rf._edit" placeholder="如 analyst" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="rf.name" placeholder="如 分析师" /></el-form-item>
        <el-form-item label="可见模块">
          <el-checkbox v-model="rf.all">全部模块</el-checkbox>
          <el-checkbox-group v-if="!rf.all" v-model="rf.modules" style="margin-top:6px">
            <el-checkbox v-for="m in ALL_MODULES" :key="m" :value="m" style="width:118px">{{ m }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="roleDlg=false">取消</el-button><el-button type="warning" @click="saveRole">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const ALL_MODULES = ['中控台', '策略总览', '规则中心', '交易历史', '账户列表', '黑名单', '币管理', '资金收益', '运维面板', '通知模块', '官网管理', '操作员管理', '系统配置', 'LLM设置']
const ROLE_CN = { SUPER_ADMIN: '超级管理员', OPERATOR: '操作员', VIEWER: '只读', USER: '用户', owner: '所有者', admin: '管理员', operator: '操作员', viewer: '只读', user: '用户' }
const roleCn = r => ROLE_CN[r] || r
const venues = ['binance', 'bybit', 'okx', 'gate', 'bitget', 'hyperliquid']
const tab = ref('users')
const data = ref({}); const showCreate = ref(false)
const nu = ref({ username: '', password: '', role: 'user', scopes: [] })
const roles = ref([]); const audit = ref([])
const roleDlg = ref(false)
const rf = reactive({ role_key: '', name: '', modules: [], all: false, is_builtin: false, _edit: false })

async function load() { try { data.value = await mixApi.operatorsAll() } catch (e) { ElMessage.error(e?.detail || '加载失败') } }
async function loadRoles() { try { roles.value = await mixApi.roles() } catch (e) { roles.value = [] } }
async function loadAudit() { try { audit.value = await mixApi.operatorsAudit() } catch (e) { audit.value = [] } }
async function create() {
  try { await mixApi.userCreate(nu.value); ElMessage.success('已开户'); showCreate.value = false; load() }
  catch (e) { ElMessage.error(e?.detail || '失败（需 SUPER_ADMIN）') }
}
async function toggle(u) { try { await mixApi.userUpdate(u.id, { enabled: !u.enabled }); load() } catch (e) { ElMessage.error(e?.detail || '失败') } }
async function editRole(u) {
  try {
    const opts = roles.value.map(r => r.role_key).join('/')
    const { value } = await ElMessageBox.prompt(`角色键：${opts}`, `改角色: ${u.username}`, { inputValue: u.role })
    await mixApi.userUpdate(u.id, { role: value }); ElMessage.success('已更新'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function editScopes(u) {
  try {
    const { value } = await ElMessageBox.prompt('逗号分隔交易所范围（留空=清空）', `改范围: ${u.username}`, { inputValue: u.scopes.join(',') })
    await mixApi.userUpdate(u.id, { scopes: value ? value.split(',').map(s => s.trim()).filter(Boolean) : [] })
    ElMessage.success('已更新'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function editIp(u) {
  try {
    const { value } = await ElMessageBox.prompt('IP 白名单（逗号分隔,留空=不限）', `IP白名单: ${u.username}`, { inputValue: u.ip_whitelist || '' })
    await mixApi.userUpdate(u.id, { ip_whitelist: value }); ElMessage.success('已更新'); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function resetPwd(u) {
  try {
    const { value } = await ElMessageBox.prompt('新密码', `重置密码: ${u.username}`, { inputType: 'password' })
    if (value) { await mixApi.userUpdate(u.id, { password: value }); ElMessage.success('已重置') }
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
function editRoleDlg(row) {
  Object.assign(rf, row
    ? { role_key: row.role_key, name: row.name, modules: (row.modules || []).filter(m => m !== '*'), all: (row.modules || []).includes('*'), is_builtin: row.is_builtin, _edit: true }
    : { role_key: '', name: '', modules: [], all: false, is_builtin: false, _edit: false })
  roleDlg.value = true
}
async function saveRole() {
  if (!rf.role_key) return ElMessage.warning('角色键必填')
  try {
    await mixApi.rolePut({ role_key: rf.role_key, name: rf.name, modules: rf.all ? ['*'] : rf.modules })
    ElMessage.success('已保存'); roleDlg.value = false; loadRoles()
  } catch (e) { ElMessage.error(e?.detail || '保存失败') }
}
async function delRole(row) {
  await ElMessageBox.confirm(`删除角色 ${row.name}？`, '删除', { type: 'warning' })
  try { await mixApi.roleDel(row.role_key); ElMessage.success('已删除'); loadRoles() } catch (e) { ElMessage.error(e?.detail || '内置角色不可删') }
}
onMounted(() => { load(); loadRoles(); loadAudit() })
</script>

<style scoped lang="scss">
.mixops { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 14px; margin-bottom: 12px; }
.chd { display: flex; gap: 10px; justify-content: space-between; align-items: center; margin-bottom: 8px; b { font-size: 13px; flex: 1; } }
.tr { display: grid; grid-template-columns: 160px 130px 110px 1fr; gap: 8px; font-size: 12px; padding: 4px 0; align-items: center;
  &.u { grid-template-columns: 110px 80px 1fr 120px 80px 100px 260px; }
  &.th { color: var(--mix-t3, #5E6673); font-weight: 700; } }
.dim { color: var(--mix-t2, #848E9C); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.r { text-align: right; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #0ECB81; margin-right: 5px; &.bad { background: #5E6673; } }
.fnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-top: 6px; }
.allmod { color: #F0B90B; font-weight: 700; font-size: 12px; }
.otabs :deep(.el-tabs__item) { color: var(--el-text-color-secondary); font-weight: 600; }
.otabs :deep(.el-tabs__item.is-active) { color: #F0B90B; }
.otabs :deep(.el-tabs__active-bar) { background: #F0B90B; }
</style>
