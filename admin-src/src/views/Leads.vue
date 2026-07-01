<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>线索中台 · 商机池</span>
        <span style="float:right">
          <el-select v-model="fStatus" size="small" clearable placeholder="状态" style="width:110px;margin-right:6px" @change="load">
            <el-option value="new" label="新线索"/><el-option value="contacted" label="已联系"/>
            <el-option value="trial" label="试用中"/><el-option value="converted" label="已转化"/><el-option value="lost" label="已流失"/></el-select>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <el-row :gutter="12">
        <el-col :span="4" v-for="(v,k) in funnelOrdered" :key="k"><el-card class="stat-card">
          <div class="l">{{statusName(k)}}</div><div class="v">{{v}}</div></el-card></el-col>
      </el-row>
      <el-table :data="leads" size="small" border style="margin-top:12px" @row-click="openLead">
        <el-table-column prop="id" label="#" width="60"/>
        <el-table-column prop="channel" label="渠道" width="100"/>
        <el-table-column prop="nickname" label="昵称"/>
        <el-table-column prop="contact" label="联系方式"/>
        <el-table-column label="状态" width="90"><template #default="s">
          <el-tag size="small" :type="LEAD_STATUS_TAG[s.row.status]" >{{statusName(s.row.status)}}</el-tag></template></el-table-column>
        <el-table-column prop="agent_code" label="代理" width="80"/>
        <el-table-column prop="msg_cnt" label="对话数" width="80"/>
        <el-table-column prop="converted_user" label="转化用户" width="120"/>
      </el-table>
    </el-card>

    <el-drawer v-model="dlg" :title="'线索 #'+(cur.lead?cur.lead.id:'')+' · '+(cur.lead?cur.lead.channel:'')" size="500px">
      <div v-if="cur.lead">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="昵称">{{cur.lead.nickname||'—'}}</el-descriptions-item>
          <el-descriptions-item label="联系方式">{{cur.lead.contact||'—'}}</el-descriptions-item>
          <el-descriptions-item label="状态">{{statusName(cur.lead.status)}}</el-descriptions-item>
          <el-descriptions-item label="代理码">{{cur.lead.agent_code||'—'}}</el-descriptions-item>
        </el-descriptions>
        <el-divider>对话</el-divider>
        <div style="max-height:240px;overflow:auto;background:#f4f6fa;border-radius:6px;padding:8px">
          <div v-for="(m,i) in cur.messages" :key="i" :style="{textAlign:m.direction==='in'?'left':'right',margin:'4px 0'}">
            <span :style="{display:'inline-block',padding:'5px 9px',borderRadius:'8px',fontSize:'12px',background:m.direction==='in'?'#fff':'#2E8BD6',color:m.direction==='in'?'#08113A':'#fff'}">
              <b style="font-size:10px;opacity:.7">{{m.by_whom}}</b><br>{{m.content}}</span>
          </div>
          <div v-if="!cur.messages.length" style="color:#909399;text-align:center">暂无对话</div>
        </div>
        <el-input v-model="reply" size="small" placeholder="客服回复..." style="margin-top:8px" @keyup.enter="doReply">
          <template #append><el-button @click="doReply">发送</el-button></template></el-input>
        <el-divider>转化</el-divider>
        <el-space wrap>
          <UserSelect v-model="convUser" width="150px" placeholder="绑定用户名"/>
          <el-input-number v-model="convDays" size="small" :min="1" style="width:110px"/>
          <el-button size="small" type="primary" @click="convert('trial')">转试用</el-button>
          <el-button size="small" type="success" @click="convert('convert')">标记转化</el-button>
          <el-button size="small" type="info" @click="convert('lost')">标记流失</el-button>
        </el-space>
        <el-divider>状态流转 / 指派</el-divider>
        <el-space wrap>
          <el-button size="small" v-if="cur.lead.status==='new'" @click="setStatus('contacted')">标记已联系</el-button>
          <el-button size="small" v-if="cur.lead.status==='lost'" @click="setStatus('new')">重新激活</el-button>
          <el-input v-model="assignOp" size="small" placeholder="指派操作员" style="width:120px"/>
          <el-input v-model="assignAgent" size="small" placeholder="指派代理码" style="width:120px"/>
          <el-button size="small" type="primary" @click="doAssign">指派</el-button>
        </el-space>
        <el-divider>内部备注(私有,不发给客户)</el-divider>
        <el-input v-model="noteText" type="textarea" :rows="2" placeholder="跟进备注..." />
        <el-button size="small" type="primary" style="margin-top:6px" @click="saveNote">保存备注</el-button>
      </div>
    </el-drawer>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import UserSelect from '../components/UserSelect.vue'
import { LEAD_STATUS, LEAD_STATUS_TAG } from '../dicts'
const leads=ref([]),funnel=ref({}),dlg=ref(false),cur=ref({lead:null,messages:[]}),reply=ref(''),convUser=ref(''),convDays=ref(7),fStatus=ref('')
const assignOp=ref(''),assignAgent=ref(''),noteText=ref('')
function statusName(k){ return LEAD_STATUS[k]||k }
const funnelOrdered=computed(()=>{ const o={}; ['new','contacted','trial','converted','lost'].forEach(k=>o[k]=funnel.value[k]||0); return o })
async function load(){ try{ const d=await api.leads(fStatus.value); leads.value=d.leads||[]; funnel.value=d.funnel||{} }catch(e){ ElMessage.error('加载失败') } }
async function openLead(row){ try{ cur.value=await api.lead(row.id); convUser.value=cur.value.lead.converted_user||''; assignOp.value=cur.value.lead.owner_op||''; assignAgent.value=cur.value.lead.agent_code||''; noteText.value=cur.value.lead.note||''; dlg.value=true }catch(e){ ElMessage.error('详情失败') } }
async function doReply(){ if(!reply.value)return; try{ await api.leadReply({lead_id:cur.value.lead.id,content:reply.value}); reply.value=''; openLead(cur.value.lead); load() }catch(e){ ElMessage.error('发送失败') } }
async function convert(action){
  try{ const r=await api.leadConvert({lead_id:cur.value.lead.id,action,username:convUser.value,days:convDays.value})
    ElMessage.success('已'+statusName(r.status||action)); openLead(cur.value.lead); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'操作失败') }
}
async function setStatus(status){
  try{ await api.leadSetStatus({lead_id:cur.value.lead.id,status}); ElMessage.success('已'+statusName(status)); openLead(cur.value.lead); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'操作失败') }
}
async function doAssign(){
  try{ await api.leadAssign({lead_id:cur.value.lead.id,owner_op:assignOp.value,agent_code:assignAgent.value}); ElMessage.success('已指派'); openLead(cur.value.lead); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'指派失败') }
}
async function saveNote(){
  try{ await api.leadNote({lead_id:cur.value.lead.id,note:noteText.value}); ElMessage.success('备注已保存') }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
onMounted(load)
</script>
