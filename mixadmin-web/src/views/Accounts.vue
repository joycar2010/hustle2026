<template>
  <div>
    <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
      title="用户交易账户登记管理(跨用户)。此处仅管理登记信息(标签/角色/连接方式/启用),不触碰任何交易、持仓或凭证数据。API 连接账户可用「清A2T」联动注销云端托管(官方 DeleteAccount)。"/>
    <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center">
      <el-input v-model="q" placeholder="搜索用户名/登录号/标签" clearable style="width:260px" @keyup.enter="load" @clear="load"/>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button @click="q='';load()">重置</el-button>
      <span style="color:#909399;font-size:12px">共 {{rows.length}} 个账户</span>
    </div>
    <el-table :data="rows" size="small" border max-height="620" v-loading="loading">
      <el-table-column prop="username" label="用户" width="130" fixed show-overflow-tooltip>
        <template #default="s"><span>{{s.row.username}}</span>
          <el-tag v-if="s.row.user_status&&s.row.user_status!=='active'" size="small" type="danger" style="margin-left:4px">{{s.row.user_status}}</el-tag></template>
      </el-table-column>
      <el-table-column prop="label" label="标签" width="140" show-overflow-tooltip class-name="col-sec"/>
      <el-table-column prop="login" label="登录号" width="120"/>
      <el-table-column label="角色" width="90"><template #default="s">
        <el-tag size="small" :type="s.row.role==='hedge'?'warning':'primary'">{{s.row.role==='hedge'?'对冲':'主'}}</el-tag></template></el-table-column>
      <el-table-column label="连接方式" width="150"><template #default="s">
        <el-tag size="small" :type="connType(s.row.conn_mode)">{{connLabel(s.row.conn_mode)}}</el-tag>
        <el-tag v-if="s.row.conn_mode==='api'&&s.row.api2trade_uuid" size="small" type="info" style="margin-left:4px" title="Api2Trade UUID">{{s.row.api2trade_uuid.slice(0,6)}}…</el-tag></template></el-table-column>
      <el-table-column prop="platform" label="平台" width="80" class-name="col-sec"/>
      <el-table-column prop="server" label="服务器" width="150" show-overflow-tooltip class-name="col-sec"/>
      <el-table-column label="启用" width="70"><template #default="s">
        <el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="230" fixed="right"><template #default="s">
        <el-button size="small" type="primary" @click="edit(s.row)">编辑</el-button>
        <el-button size="small" @click="del(s.row)">删登记</el-button>
        <el-button size="small" type="danger" @click="purge(s.row)" title="彻底注销: 联动注销云端托管账户 + 删登记(不影响交易记录)">清A2T</el-button></template></el-table-column>
    </el-table>

    <el-dialog :close-on-click-modal="false" v-model="dlg" title="编辑账户登记" width="480">
      <el-descriptions :column="1" border size="small" style="margin-bottom:12px">
        <el-descriptions-item label="用户">{{cur.username}}</el-descriptions-item>
        <el-descriptions-item label="登录号">{{cur.login}}</el-descriptions-item>
        <el-descriptions-item v-if="cur.conn_mode==='api'&&cur.api2trade_uuid" label="Api2Trade UUID">{{cur.api2trade_uuid}}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="90">
        <el-form-item label="标签"><el-input v-model="form.label"/></el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role"><el-radio-button label="main">主账户</el-radio-button><el-radio-button label="hedge">对冲账户</el-radio-button></el-radio-group>
        </el-form-item>
        <el-form-item label="连接方式">
          <el-select v-model="form.conn_mode" style="width:100%">
            <el-option label="Bridge 云端" value="bridge"/>
            <el-option label="API · Api2Trade" value="api"/>
          </el-select>
        </el-form-item>
        <el-form-item label="平台">
          <el-radio-group v-model="form.platform"><el-radio-button label="MT4">MT4</el-radio-button><el-radio-button label="MT5">MT5</el-radio-button></el-radio-group>
        </el-form-item>
        <el-form-item label="经纪商">
          <el-select v-model="form.broker" filterable allow-create default-first-option clearable
            placeholder="选择经纪商(可手输)" style="width:100%" :loading="brokersLoading" @change="onBrokerPick">
            <el-option v-for="c in brokerDir" :key="c.company" :label="c.company+(c.local?' · 本地':'')" :value="c.company"/>
          </el-select>
        </el-form-item>
        <el-form-item label="服务器">
          <el-select v-model="form.server" filterable allow-create default-first-option clearable
            placeholder="选择服务器(可手输)" style="width:100%">
            <el-option v-for="s in serverOpts" :key="s" :label="s" :value="s"/>
          </el-select>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="doSave">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const q=ref(''), rows=ref([]), loading=ref(false)
const dlg=ref(false), cur=ref({}), form=ref({})
// 经纪商/服务器目录: 复用 /a2t/brokers 聚合缓存(A2T /Search, 后端 Redis 6h)
const brokerDir=ref([]), brokersLoading=ref(false)
const serverOpts=computed(()=>{ const c=brokerDir.value.find(x=>x.company===form.value.broker); return c?c.servers:[] })
async function loadBrokers(){ if(brokerDir.value.length)return; brokersLoading.value=true
  try{ brokerDir.value=(await api.a2tBrokers()).companies||[] }catch(e){ /* 目录不可用时保持手输 */ }finally{ brokersLoading.value=false } }
function onBrokerPick(){ const opts=serverOpts.value; if(form.value.server && opts.length && !opts.includes(form.value.server)) form.value.server='' }
function connType(m){ return m==='api'?'warning':'success' }
function connLabel(m){ return m==='api'?'API·Api2Trade':'Bridge云端' }
async function load(){ loading.value=true; try{ rows.value=(await api.adminAccounts(q.value)).accounts||[] }catch(e){ ElMessage.error(e?.response?.data?.detail||'需权限(accounts)') }finally{ loading.value=false } }
function edit(row){ cur.value=row; form.value={id:row.id,label:row.label||'',role:row.role||'main',conn_mode:row.conn_mode||'bridge',platform:row.platform||'MT5',broker:row.broker||'',server:row.server||'',enabled:!!row.enabled}; loadBrokers(); dlg.value=true }
async function doSave(){ try{ await api.adminAcctSave(form.value); ElMessage.success('已保存'); dlg.value=false; load() }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function del(row){ try{ await ElMessageBox.confirm('仅删除 '+row.username+' 的账户登记「'+(row.label||row.login)+'」?\n云端托管账户不联动删除(如需彻底注销请用「清A2T」)。不影响交易记录。','删除登记',{type:'warning',dangerouslyUseHTMLString:false}); await api.adminAcctDelete(row.id); ElMessage.success('已删除登记'); load() }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'删除失败') } }
async function purge(row){
  try{
    await ElMessageBox.confirm(
      '<b>彻底注销</b> '+row.username+' 的账户「'+(row.label||row.login)+'」？<br><br>'+
      '• 联动调用云端 API <b>注销云端托管账户</b>（不可逆）<br>'+
      '• 删除本地登记行<br>'+
      '• <b>不影响任何交易记录 / 历史成交</b>（仅登记与云端托管）<br><br>'+
      '<span style="color:#e6a23c">走云端官方 DeleteAccount 注销; 云端已不存在时视为已释放; 若注销失败会明确提示原因。注销后可在账户设置重新「保存并登录」再次接入。</span>',
      '彻底注销云端账户',{type:'error',dangerouslyUseHTMLString:true,confirmButtonText:'彻底注销'})
    const r=await api.adminAcctPurge(row.id)
    if(r.a2t_ok) ElMessage.success('已彻底注销: '+(r.a2t_msg||'云端已注销')+' + 本地已删')
    else ElMessage.warning('本地登记已删; 云端注销未成功: '+(r.a2t_msg||'请后台处理'))
    load()
  }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'操作失败') }
}
onMounted(load)
</script>
