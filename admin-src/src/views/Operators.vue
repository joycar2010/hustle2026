<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>操作员管理 · 角色 / 权限 / IP</span>
        <span style="float:right">
          <el-button size="small" type="danger" plain @click="resetAdminToken">重置超管令牌</el-button>
          <el-button size="small" type="primary" @click="newOp">+ 新增操作员</el-button>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <el-table :data="operators" size="small" border>
        <el-table-column prop="username" label="账号" width="140"/>
        <el-table-column label="角色" width="110"><template #default="s">
          <el-tag size="small">{{roleName(s.row.role)}}</el-tag></template></el-table-column>
        <el-table-column prop="allowed_ips" label="IP白名单"><template #default="s">{{s.row.allowed_ips||'不限'}}</template></el-table-column>
        <el-table-column label="状态" width="80"><template #default="s">
          <el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'禁用'}}</el-tag></template></el-table-column>
        <el-table-column prop="last_login" label="最后登录"/>
        <el-table-column label="操作" width="150" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="editOp(s.row)">编辑</el-button>
          <el-button size="small" link type="warning" @click="resetPwd(s.row)">重置密码</el-button></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">「重置超管令牌」仅超级管理员可用:轮换后旧令牌立即失效,需用新令牌重新登录。</div>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span>角色权限矩阵 · 可自定义</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newRole">+ 新增角色</el-button></span></template>
      <el-table :data="roles" size="small" border>
        <el-table-column prop="role" label="角色键" width="110"/>
        <el-table-column prop="name" label="名称" width="130"/>
        <el-table-column label="可见模块"><template #default="s">
          <code style="font-size:11px">{{ s.row.perms==='*'?'全部模块':permsText(s.row.perms) }}</code></template></el-table-column>
        <el-table-column label="操作" width="140"><template #default="s">
          <el-button size="small" :disabled="s.row.role==='super'" @click="editRole(s.row)">编辑权限</el-button>
          <el-button size="small" type="danger" :disabled="s.row.role==='super'||s.row.role==='viewer'" @click="delRole(s.row.role)">删</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><span>操作员行为日志</span>
        <span style="float:right"><el-button size="small" @click="loadAudit">刷新</el-button></span></template>
      <el-table :data="audit" size="small" border max-height="320">
        <el-table-column prop="ts" label="时间" width="180"/>
        <el-table-column prop="operator" label="操作员" width="130"/>
        <el-table-column label="角色" width="90"><template #default="s">{{roleName(s.row.role)}}</template></el-table-column>
        <el-table-column prop="ip" label="IP" width="130"/>
        <el-table-column prop="action" label="操作"/>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="editing?'编辑操作员':'新增操作员'" width="420">
      <el-form label-width="92">
        <el-form-item label="账号"><el-input v-model="cur.username" :disabled="editing"/></el-form-item>
        <el-form-item label="密码"><el-input v-model="cur.password" type="password" :placeholder="editing?'留空=不改':'必填'"/></el-form-item>
        <el-form-item label="角色"><el-select v-model="cur.role"><el-option v-for="r in roles" :key="r.role" :label="r.name" :value="r.role"/></el-select></el-form-item>
        <el-form-item label="IP白名单"><el-input v-model="cur.allowed_ips" placeholder="逗号分隔,空=不限"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="cur.enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="saveOp">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="roleDlg" :title="(roleEdit?'编辑':'新增')+'角色权限'" width="500">
      <el-form label-width="80">
        <el-form-item label="角色键"><el-input v-model="roleCur.role" :disabled="roleEdit" placeholder="如 finance"/></el-form-item>
        <el-form-item label="名称"><el-input v-model="roleCur.name"/></el-form-item>
        <el-form-item label="可见模块">
          <div style="margin-bottom:8px">
            <span style="font-size:12px;color:#606266;margin-right:6px">快捷模板:</span>
            <el-button v-for="tpl in ROLE_TPLS" :key="tpl.key" size="small" @click="applyRoleTpl(tpl)">{{tpl.label}}</el-button>
          </div>
          <el-checkbox v-model="allMods" @change="toggleAll">全部模块(*)</el-checkbox>
          <div v-if="!allMods" style="margin-top:6px">
            <div v-for="grp in MODULE_GROUPS" :key="grp.name" style="margin-bottom:6px">
              <div style="font-size:12px;color:#909399;margin-bottom:2px">{{grp.name}}<span v-if="grp.name==='运维'" style="color:#E6A23C">(系统页 · 运营默认不含)</span></div>
              <el-checkbox-group v-model="roleMods">
                <el-checkbox v-for="m in grp.items" :key="m.k" :value="m.k" style="width:130px">{{m.n}}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="roleDlg=false">取消</el-button><el-button type="primary" @click="saveRole">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const operators=ref([]),roles=ref([]),audit=ref([]),dlg=ref(false),cur=ref({}),editing=ref(false)
const roleDlg=ref(false),roleCur=ref({}),roleEdit=ref(false),roleMods=ref([]),allMods=ref(false)
// 后台模块清单(perms = 这些 key 的逗号串; '*'=全部)
// 后台模块清单(perms = 这些 key 的逗号串; '*'=全部)。按业务分组展示(对齐侧栏 分析/经营/运维)
const MODULE_GROUPS=[
  {name:'分析',items:[{k:'dashboard',n:'总控面板'},{k:'bi',n:'经营分析'}]},
  {name:'经营',items:[{k:'users',n:'用户管理'},{k:'orders',n:'充值订单'},{k:'iap',n:'内购配置'},{k:'agents',n:'三级代理'},{k:'trials',n:'试用管理'},{k:'leads',n:'线索中台'},{k:'chat',n:'AI客服'}]},
  {name:'运维',items:[{k:'system',n:'系统管理'},{k:'notify',n:'系统通知'},{k:'datamgr',n:'数据管理'},{k:'operators',n:'操作员'},{k:'params',n:'参数下发'},{k:'legs',n:'双腿监控'},{k:'recon',n:'对账'},{k:'deals',n:'成交记录'}]},
]
// 角色模板: 运营默认不含运维系统页
const ROLE_TPLS=[
  {key:'ops',     label:'运营',     mods:['dashboard','bi','users','orders','iap','agents','trials','leads','chat']},
  {key:'finance', label:'财务',     mods:['dashboard','bi','orders','iap','agents']},
  {key:'service', label:'客服',     mods:['dashboard','leads','chat','users','trials']},
  {key:'opsro',   label:'只读运维', mods:['dashboard','legs','recon','deals','params']},
]
function applyRoleTpl(tpl){ allMods.value=false; roleMods.value=[...tpl.mods] }
// 模块键→中文名 拍平映射(取自 MODULE_GROUPS),用于可见模块列中文化
const MODULE_NAME=Object.fromEntries(MODULE_GROUPS.flatMap(g=>g.items.map(m=>[m.k,m.n])))
function permsText(perms){ if(!perms) return '—'; return perms.split(',').map(x=>x.trim()).filter(Boolean).map(k=>MODULE_NAME[k]||k).join(' / ') }
function roleName(k){ const r=roles.value.find(x=>x.role===k); return r?r.name:k }
async function load(){ try{ const d=await api.operators(); operators.value=d.operators||[]; roles.value=d.roles||[] }catch(e){ ElMessage.error('加载失败(需超管 token)') } }
async function loadAudit(){ try{ audit.value=(await api.operatorAudit()).audit||[] }catch(e){} }
function newOp(){ cur.value={username:'',password:'',role:'viewer',allowed_ips:'',enabled:true}; editing.value=false; dlg.value=true }
function newRole(){ roleCur.value={role:'',name:'',perms:''}; roleMods.value=[]; allMods.value=false; roleEdit.value=false; roleDlg.value=true }
function editRole(r){ roleCur.value={...r}; allMods.value=(r.perms==='*'); roleMods.value=r.perms==='*'?[]:(r.perms||'').split(',').map(x=>x.trim()).filter(Boolean); roleEdit.value=true; roleDlg.value=true }
function toggleAll(v){ if(v)roleMods.value=[] }
async function saveRole(){
  const perms=allMods.value?'*':roleMods.value.join(',')
  try{ await api.roleSave({role:roleCur.value.role,name:roleCur.value.name,perms}); ElMessage.success('已保存'); roleDlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delRole(role){ try{ await api.roleDel(role); ElMessage.success('已删除'); load() }catch(e){ ElMessage.error(e?.response?.data?.detail||'删除失败') } }
function editOp(r){ cur.value={...r,password:''}; editing.value=true; dlg.value=true }
async function saveOp(){
  try{ await api.operatorSave(cur.value); ElMessage.success('已保存'); dlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(检查 Admin Token)') }
}
async function resetPwd(row){
  try{ const {value}=await ElMessageBox.prompt('为操作员 '+row.username+' 设置新登录密码(≥6位):','重置密码',{inputType:'password',inputPattern:/.{6,}/,inputErrorMessage:'至少6位'})
    await api.operatorResetPwd(row.username,value); ElMessage.success('密码已重置') }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'失败') }
}
async function resetAdminToken(){
  try{ await ElMessageBox.confirm('重置超管令牌?旧令牌立即失效,你需用新令牌重新登录。仅超级管理员可执行。','⚠ 高危确认',{type:'warning',confirmButtonText:'确认重置'})
    const {value}=await ElMessageBox.prompt('新令牌(留空=随机生成,≥12位):','设置新超管令牌',{inputPlaceholder:'留空随机',inputValidator:v=>(!v||v.length>=12)||'至少12位'}).catch(()=>({value:''}))
    const r=await api.resetAdminToken(value||'')
    await ElMessageBox.alert('新超管令牌(请立即复制保存):\n\n'+r.new_token+'\n\n旧令牌已失效。','重置成功',{type:'success'})
    // 本地更新令牌, 避免当前会话失效
    localStorage.setItem('qh_admin_token', r.new_token)
  }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'仅超级管理员可操作') }
}
onMounted(()=>{ load(); loadAudit() })
</script>
