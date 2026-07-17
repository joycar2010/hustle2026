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
          <div class="chd"><b>Mix 用户（登录账号 · 角色 · 数据范围）</b>
            <span class="sub">仅内部人员账号与权限;<b>不含投资权益</b>——客户资金权益在「客户与份额」页(REV2 §4A.2 分域)</span>
            <el-button size="small" type="warning" @click="showCreate=true">新增操作员</el-button>
          </div>
          <div class="tr th u"><span>账号</span><span>角色</span><span>数据范围</span><span>IP白名单</span><span>MFA/设备</span><span>最近登录</span><span>操作</span></div>
          <div v-for="u in data.users || []" :key="u.id" class="tr u">
            <span><b>{{ u.username }}</b></span>
            <span>{{ roleCn(u.role) }}</span>
            <span class="dim">{{ u.scopes.length ? u.scopes.join('/') : (u.role==='owner'||u.role==='admin' ? '全量' : '未绑定') }}</span>
            <span class="dim">{{ u.ip_whitelist || '不限' }}</span>
            <span class="dim">{{ u.mfa_bound ? 'Passkey' : (u.totp_bound ? 'TOTP' : '—') }}</span>
            <span class="dim">{{ u.last_login || '—' }}</span>
            <span class="acts"><el-button size="small" text type="primary" @click="openManage(u)">管理</el-button></span>
          </div>
          <div class="fnote">停用登录账号不影响任何客户份额;改角色/范围不改变客户权益(§4A.1 四权威分离)。</div>
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
      <el-tab-pane label="受信设备" name="devices">
        <div class="card">
          <div class="chd"><b>受信移动设备（REV2 §9）</b>
            <span class="sub">受信=本受信桌面确认注册+绑定 Passkey;移动端据此判能否完整研判/开仓(受设备额度)。设备丢失即撤销。</span>
            <el-button size="small" style="margin-left:auto" @click="loadDevices">刷新</el-button>
            <el-button size="small" type="warning" @click="devDlg=true">注册新设备</el-button></div>
          <el-table :data="devices" size="small" max-height="520">
            <el-table-column prop="label" label="设备" width="150" />
            <el-table-column prop="surface" label="类型" width="70" />
            <el-table-column label="受信" width="80"><template #default="{row}"><el-tag size="small" :type="row.trust_state==='trusted'?'success':'info'">{{ row.trust_state==='trusted'?'已受信':row.trust_state }}</el-tag></template></el-table-column>
            <el-table-column label="Passkey" width="80"><template #default="{row}">{{ row.has_passkey?'已绑':'未绑' }}</template></el-table-column>
            <el-table-column label="单笔额度U" width="100" align="right"><template #default="{row}">{{ row.max_notional }}</template></el-table-column>
            <el-table-column label="当日额度U" width="100" align="right"><template #default="{row}">{{ row.daily_budget }}</template></el-table-column>
            <el-table-column prop="last_seen" label="最近活跃" width="150" />
            <el-table-column label="操作" min-width="160"><template #default="{row}">
              <el-button size="small" text @click="editLimits(row)">改额度</el-button>
              <el-button size="small" text type="danger" @click="revokeDev(row)">撤销</el-button></template></el-table-column>
          </el-table>
          <div class="fnote" style="font-size:11px;color:var(--mix-t3);margin-top:8px">额度只能在此(受信桌面)调整,移动端不可自行提高;撤销后该设备现有会话立即失效,后续一律 untrusted。真金移动开仓(C2.P/C3 canary)仍待专场放行。</div>
        </div>
      </el-tab-pane>
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

    <!-- 用户管理抽屉(§4A.2:每行只留「管理」主动作,高危收进抽屉减少误点) -->
    <el-drawer v-model="mgDlg" :title="`管理 · ${mgUser.username||''}`" size="360px">
      <div v-if="mgUser.id" class="mgbody">
        <div class="mgkv"><span>角色</span><b>{{ roleCn(mgUser.role) }}</b></div>
        <div class="mgkv"><span>数据范围</span><b>{{ mgUser.scopes?.length ? mgUser.scopes.join('/') : '未绑定' }}</b></div>
        <div class="mgkv"><span>IP白名单</span><b>{{ mgUser.ip_whitelist || '不限' }}</b></div>
        <div class="mgkv"><span>状态</span><b :class="mgUser.enabled?'':'bad'">{{ mgUser.enabled?'启用':'停用' }}</b></div>
        <div class="mgkv"><span>访问令牌</span><b :class="mgTok?'':'dim'">{{ mgTok?'已签发（可撤销）':'未签发' }}</b></div>
        <div class="mgacts">
          <el-button @click="editRole(mgUser)">改角色</el-button>
          <el-button @click="editScopes(mgUser)">改数据范围</el-button>
          <el-button @click="editIp(mgUser)">IP白名单</el-button>
          <el-button @click="resetPwd(mgUser)">重置密码</el-button>
        </div>
        <div class="mgsec">登录访问令牌（投资人「访问令牌」登录用）</div>
        <div class="mgacts">
          <el-button type="warning" @click="issueTok">{{ mgTok?'重置令牌（旧失效）':'生成访问令牌' }}</el-button>
          <el-button v-if="mgTok" type="danger" @click="revokeTok">删除令牌（撤销）</el-button>
        </div>
        <div v-if="mgTokVal" class="sidbox" style="margin-top:8px">
          <b>访问令牌（仅显示一次，交给该用户）</b>
          <div class="sidval">{{ mgTokVal }}</div>
          <el-button size="small" @click="copyTok">复制</el-button>
        </div>
        <div class="mgsec">账号状态</div>
        <div class="mgacts">
          <el-button :type="mgUser.enabled?'danger':'success'" @click="toggle(mgUser)">{{ mgUser.enabled?'停用登录':'启用登录' }}</el-button>
        </div>
        <p class="mgnote">停用只禁止登录,不删除账号、不改变其查看授权对应客户的资金权益。重置/删除令牌立即使旧令牌失效。删除客户/份额请到「客户与份额」页,且只能停用不能物理删。</p>
      </div>
    </el-drawer>
    <!-- 注册受信设备(§9:桌面确认→受信→移动端保存会话) -->
    <el-dialog v-model="devDlg" title="注册受信移动设备" width="460">
      <p style="font-size:11px;color:#F0B90B;margin-bottom:10px">本受信桌面确认后,该移动设备即受信;把生成的会话交给移动设备(更多·绑定本机)即可完整研判/开仓(受额度)。设备须已注册 Passkey。</p>
      <el-form label-width="90px" size="small">
        <el-form-item label="设备类型"><el-radio-group v-model="nd.surface"><el-radio value="phone">手机</el-radio><el-radio value="tablet">平板</el-radio></el-radio-group></el-form-item>
        <el-form-item label="设备名"><el-input v-model="nd.label" placeholder="如 老板的iPhone" /></el-form-item>
        <el-form-item label="单笔额度U"><el-input-number v-model="nd.max_notional" :min="0" /></el-form-item>
        <el-form-item label="当日额度U"><el-input-number v-model="nd.daily_budget" :min="0" /></el-form-item>
      </el-form>
      <div v-if="lastSid" class="sidbox">
        <b>设备会话（复制到移动设备）</b>
        <div class="sidval">{{ lastSid }}</div>
        <el-button size="small" @click="copySid">复制</el-button>
      </div>
      <template #footer><el-button @click="devDlg=false;lastSid=''">关闭</el-button><el-button type="warning" @click="registerDev">注册并生成会话</el-button></template>
    </el-dialog>
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

    <!-- 改角色（下拉选择,不填空框） -->
    <el-dialog v-model="chRoleDlg" :title="`改角色 · ${chForm.username}`" width="360">
      <el-select v-model="chForm.role" style="width:100%">
        <el-option v-for="r in roles" :key="r.role_key" :value="r.role_key" :label="`${r.name}（${r.role_key}）`" />
      </el-select>
      <template #footer><el-button @click="chRoleDlg=false">取消</el-button><el-button type="warning" @click="saveChRole">保存</el-button></template>
    </el-dialog>

    <!-- 改范围（勾选,不填空框） -->
    <el-dialog v-model="chScopeDlg" :title="`改范围 · ${chForm.username}`" width="400">
      <el-checkbox-group v-model="chForm.scopes">
        <el-checkbox v-for="v in venues" :key="v" :value="v" style="width:110px">{{ v }}</el-checkbox>
      </el-checkbox-group>
      <div style="font-size:11px;color:var(--el-text-color-placeholder);margin-top:8px">不勾=零数据（默认拒绝）；owner/admin 角色天然全量。</div>
      <template #footer><el-button @click="chScopeDlg=false">取消</el-button><el-button type="warning" @click="saveChScope">保存</el-button></template>
    </el-dialog>

    <!-- 角色编辑 -->
    <el-dialog v-model="roleDlg" :title="rf.is_builtin?'编辑内置角色（仅改可见模块）':'角色编辑'" width="520">
      <el-form label-width="80">
        <el-form-item label="角色键"><el-input v-model="rf.role_key" :disabled="rf._edit" placeholder="如 analyst" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="rf.name" placeholder="如 分析师" /></el-form-item>
        <el-form-item label="可见模块">
          <el-checkbox v-model="rf.all">全部模块</el-checkbox>
          <div v-if="!rf.all" style="margin-top:6px">
            <div v-for="g in MODULE_GROUPS" :key="g.group" class="modgrp">
              <div class="modgrp-h">{{ g.group }}</div>
              <el-checkbox-group v-model="rf.modules">
                <el-checkbox v-for="m in g.mods" :key="m" :value="m" style="width:150px">{{ m }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
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

// V6 模块清单权威(与真实菜单同步;新增模块须同步此处+记忆 mix-module-inventory)
const MODULE_GROUPS = [
  { group: '今日工作', mods: ['今日工作', '训练模式', '策略工作台', 'AiCoin研判'] },
  { group: '风险与账务', mods: ['风险事件', '资产收益', '交易与核对', '客户与份额'] },
  { group: '管理设置', mods: ['策略与额度', '账户币种与路由', 'C3.S坑位工作台'] },
  { group: '研究与实验', mods: ['DEX/Onchain LAB'] },
  { group: '系统设置', mods: ['系统状态', '通知模块', '操作员管理', '系统配置', '网站设置', 'LLM设置', '旧C3.S对比'] },
  { group: '外接屏/移动', mods: ['三分屏墙', '平板值守', '手机值守'] },
]
const ALL_MODULES = MODULE_GROUPS.flatMap(g => g.mods)
const ROLE_CN = { SUPER_ADMIN: '超级管理员', OPERATOR: '操作员', VIEWER: '只读', USER: '用户', owner: '所有者', admin: '管理员', operator: '操作员', viewer: '只读', user: '用户' }
const roleCn = r => ROLE_CN[r] || r
const venues = ['binance', 'bybit', 'okx', 'gate', 'bitget', 'hyperliquid']
const tab = ref('users')
const data = ref({}); const showCreate = ref(false)
const nu = ref({ username: '', password: '', role: 'user', scopes: [] })
const roles = ref([]); const audit = ref([])
const roleDlg = ref(false)
const rf = reactive({ role_key: '', name: '', modules: [], all: false, is_builtin: false, _edit: false })
const chRoleDlg = ref(false), chScopeDlg = ref(false)
const chForm = reactive({ id: null, username: '', role: '', scopes: [] })

async function load() { try { data.value = await mixApi.operatorsAll() } catch (e) { ElMessage.error(e?.detail || '加载失败') } }
async function loadRoles() { try { roles.value = await mixApi.roles() } catch (e) { roles.value = [] } }
async function loadAudit() { try { audit.value = await mixApi.operatorsAudit() } catch (e) { audit.value = [] } }
async function create() {
  try { await mixApi.userCreate(nu.value); ElMessage.success('已开户'); showCreate.value = false; load() }
  catch (e) { ElMessage.error(e?.detail || '失败（需 SUPER_ADMIN）') }
}
async function toggle(u) { try { await mixApi.userUpdate(u.id, { enabled: !u.enabled }); load() } catch (e) { ElMessage.error(e?.detail || '失败') } }
function editRole(u) { Object.assign(chForm, { id: u.id, username: u.username, role: u.role, scopes: [...(u.scopes || [])] }); chRoleDlg.value = true }
async function saveChRole() {
  try { await mixApi.userUpdate(chForm.id, { role: chForm.role }); ElMessage.success('已更新'); chRoleDlg.value = false; load() }
  catch (e) { ElMessage.error(e?.detail || '失败') }
}
function editScopes(u) { Object.assign(chForm, { id: u.id, username: u.username, role: u.role, scopes: [...(u.scopes || [])] }); chScopeDlg.value = true }
async function saveChScope() {
  try { await mixApi.userUpdate(chForm.id, { scopes: chForm.scopes }); ElMessage.success('已更新'); chScopeDlg.value = false; load() }
  catch (e) { ElMessage.error(e?.detail || '失败') }
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
// 用户管理抽屉 + 访问令牌
const mgDlg = ref(false); const mgUser = reactive({})
const mgTok = ref(false); const mgTokVal = ref('')
async function openManage(u) {
  Object.assign(mgUser, u); mgTokVal.value = ''; mgDlg.value = true
  try { mgTok.value = (await mixApi.userTokenStatus(u.id)).has_token } catch (e) { mgTok.value = false }
}
async function issueTok() {
  try {
    if (mgTok.value) await ElMessageBox.confirm('重置将使该用户现有访问令牌立即失效,确认？', '重置访问令牌', { type: 'warning' })
    const r = await mixApi.userTokenIssue(mgUser.id, 90); mgTokVal.value = r.access_token; mgTok.value = true
    ElMessage.success('已生成访问令牌（仅显示一次）')
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function revokeTok() {
  try { await ElMessageBox.confirm('删除后该用户访问令牌立即失效,需重新生成才能用令牌登录,确认？', '删除访问令牌', { type: 'warning' })
    await mixApi.userTokenRevoke(mgUser.id); mgTok.value = false; mgTokVal.value = ''; ElMessage.success('已撤销') } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
function copyTok() { navigator.clipboard?.writeText(mgTokVal.value); ElMessage.success('已复制访问令牌') }
// REV2 §9 受信设备
const devices = ref([])
const devDlg = ref(false)
const nd = reactive({ surface: 'phone', label: '', max_notional: 50, daily_budget: 200 })
const lastSid = ref('')
async function loadDevices() { try { devices.value = await mixApi.devList() } catch (e) { devices.value = [] } }
function copySid() { navigator.clipboard?.writeText(lastSid.value); ElMessage.success('已复制设备会话') }
async function registerDev() {
  try {
    const r = await mixApi.devRegister({ surface: nd.surface, label: nd.label, max_notional: nd.max_notional, daily_budget: nd.daily_budget })
    lastSid.value = r.device_session_id
    ElMessage.success('设备已注册·受信')
    loadDevices()
  } catch (e) { ElMessage.error(e?.detail || '注册失败（需先注册 Passkey）') }
}
async function revokeDev(row) {
  try { await ElMessageBox.confirm(`撤销设备「${row.label}」？现有会话立即失效。`, '撤销受信', { type: 'warning' })
    await mixApi.devRevoke(row.sid_full); ElMessage.success('已撤销'); loadDevices() } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
async function editLimits(row) {
  try {
    const { value } = await ElMessageBox.prompt(`「${row.label}」单笔额度U（当前 ${row.max_notional}）`, '改额度', { inputValue: String(row.max_notional) })
    await mixApi.devLimits(row.sid_full, { max_notional: Number(value), daily_budget: row.daily_budget })
    ElMessage.success('已更新'); loadDevices()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || '失败') }
}
onMounted(() => { load(); loadRoles(); loadAudit(); loadDevices() })
</script>

<style scoped lang="scss">
.mixops { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 14px; margin-bottom: 12px; }
.chd { display: flex; gap: 10px; justify-content: space-between; align-items: center; margin-bottom: 8px; b { font-size: 13px; flex: 1; } }
.chd .sub { font-size: 10.5px; color: var(--mix-t3, #5E6673); font-weight: 400; flex: 2; }
.sidbox { margin-top: 12px; padding: 10px 12px; background: var(--mix-panel, #12151A); border: 1px solid #F0B90B44; border-radius: 8px;
  b { font-size: 11px; color: #F0B90B; } }
.sidval { font-family: 'Roboto Mono', monospace; font-size: 12px; color: var(--mix-t1, #EAECEF); word-break: break-all; margin: 6px 0; }
.mgbody { display: flex; flex-direction: column; gap: 10px; }
.mgkv { display: flex; justify-content: space-between; font-size: 12px; color: var(--mix-t2, #848E9C); padding: 4px 0; border-bottom: 1px solid var(--mix-border, #262B33); b { color: var(--mix-t1, #EAECEF); } b.bad { color: #F6465D; } }
.mgacts { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; }
.mgnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); line-height: 1.6; margin-top: 8px; }
.mgsec { font-size: 10.5px; color: var(--mix-t3, #5E6673); font-weight: 700; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--mix-border, #2B3139); }
.modgrp { margin-bottom: 8px; }
.modgrp-h { font-size: 10.5px; color: #F0B90B; font-weight: 700; margin: 6px 0 2px; }
.tr { display: grid; grid-template-columns: 160px 130px 110px 1fr; gap: 8px; font-size: 12px; padding: 6px 0; align-items: center;
  color: var(--mix-t1, #EAECEF); border-bottom: 1px solid rgba(43,49,57,.5);
  &.u { grid-template-columns: 110px 80px 1fr 120px 90px 110px 90px; }
  &.th { color: var(--mix-t2, #B7BDC6); font-weight: 700; border-bottom: 1px solid var(--mix-border, #2B3139); } }
.tr span { color: var(--mix-t1, #EAECEF); }
.tr.th span { color: var(--mix-t2, #B7BDC6); }
.dim { color: var(--mix-t2, #B7BDC6) !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.r { text-align: right; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; }
.acts :deep(.el-button.is-text) { color: #F0B90B; font-weight: 700; }
.acts :deep(.el-button.is-text:hover) { color: #F0B90B; background: rgba(240,185,11,.12); }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #0ECB81; margin-right: 5px; &.bad { background: #5E6673; } }
.fnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-top: 6px; }
.allmod { color: #F0B90B; font-weight: 700; font-size: 12px; }
.otabs :deep(.el-tabs__item) { color: var(--el-text-color-secondary); font-weight: 600; }
.otabs :deep(.el-tabs__item.is-active) { color: #F0B90B; }
.otabs :deep(.el-tabs__active-bar) { background: #F0B90B; }
</style>
