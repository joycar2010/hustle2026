<template>
  <div>
    <el-card style="margin-bottom:12px" body-style="padding:10px">
      <template #header><span>🌏 用户地区分布</span>
        <span style="float:right;font-size:12px;color:#909399" v-if="geo">已定位 {{geo.located}}/{{geo.total}}</span></template>
      <el-row :gutter="12" v-if="geo && geo.by_country.length">
        <el-col :span="14"><ChartBox :option="geoBarOpt" :height="200"/></el-col>
        <el-col :span="10">
          <el-table :data="geo.by_country.slice(0,8)" size="small" border max-height="200">
            <el-table-column label="地区"><template #default="s">{{s.row.name}}</template></el-table-column>
            <el-table-column prop="users" label="用户数" width="80"/>
            <el-table-column prop="active_30d" label="30日活跃" width="90"/>
          </el-table>
        </el-col>
      </el-row>
      <div v-else style="color:#909399;text-align:center;padding:16px">暂无地区数据(用户登录后按 IP 离线解析)</div>
    </el-card>

    <el-card>
      <template #header><span>用户管理 · 经营中心</span>
        <span style="float:right;display:inline-flex;align-items:center;gap:6px">
          <UserSelect v-model="q" width="170px" placeholder="搜用户名"/>
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">+ 新建用户</el-button></span></template>
      <el-table :data="users" size="small" border @row-click="openDetail">
        <el-table-column prop="username" label="用户" width="130"/>
        <el-table-column label="状态" width="90"><template #default="s">
          <el-tag size="small" :type="USER_STATUS_TAG[s.row.status]||'info'">
            {{ zh(USER_STATUS, s.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="到期倒计时" width="110"><template #default="s">
          <span :class="s.row.days_left!=null&&s.row.days_left<7?'down':''">{{s.row.days_left==null?'—':s.row.days_left+'天'}}</span></template></el-table-column>
        <el-table-column label="累计充值" width="100"><template #default="s">{{s.row.total_recharge}}</template></el-table-column>
        <el-table-column prop="agent_code" label="代理" width="80"/>
        <el-table-column label="模式" width="90"><template #default="s">
          <el-tag size="small" :type="s.row.force_demo?'info':'success'">{{s.row.force_demo?'演示':'真金'}}</el-tag></template></el-table-column>
        <el-table-column label="自动" width="120"><template #default="s">
          <span style="font-size:11px">进{{tag(s.row.auto_entry)}}/出{{tag(s.row.auto_exit)}}</span></template></el-table-column>
        <el-table-column label="近7日盈亏" width="100"><template #default="s">
          <span :class="s.row.pnl_7d>=0?'up':'down'">{{s.row.pnl_7d}}</span></template></el-table-column>
        <el-table-column label="操作" width="250" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click.stop="openDetail(s.row)">详情</el-button>
          <el-button size="small" link type="primary" @click.stop="openEdit(s.row)">编辑</el-button>
          <el-button v-if="s.row.status==='disabled'" size="small" link type="success" @click.stop="quickOp(s.row,'enable','启用用户 '+s.row.username+'?')">启用</el-button>
          <el-button v-else size="small" link type="warning" @click.stop="quickOp(s.row,'disable','停用用户 '+s.row.username+'?(阻止登录,不影响引擎)')">停用</el-button>
          <el-button size="small" link type="danger" @click.stop="quickOp(s.row,'delete','删除用户 '+s.row.username+'?有成交/订单将拒绝删除')">删</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="dlg" :title="'客户 360 · '+(cur.username||'')" size="540px">
      <div v-if="cur.username">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="状态"><el-tag size="small" :type="USER_STATUS_TAG[cur.status]||'info'">{{zh(USER_STATUS,cur.status)}}</el-tag></el-descriptions-item>
          <el-descriptions-item label="套餐">{{ ownedPackages(cur).join(' / ') || cur.plan || '—' }}</el-descriptions-item>
          <el-descriptions-item label="付费到期">{{fmt(cur.paid_until)}}</el-descriptions-item>
          <el-descriptions-item label="试用到期">{{fmt(cur.trial_until)}}</el-descriptions-item>
          <el-descriptions-item label="累计充值">{{cur.total_recharge}}</el-descriptions-item>
          <el-descriptions-item label="累计成交">{{cur.deals_total}} ({{cur.pnl_total}})</el-descriptions-item>
          <el-descriptions-item label="模式">{{cur.force_demo?'强制演示':'真金'}}</el-descriptions-item>
          <el-descriptions-item label="自动">进{{zh(AUTO_MODE,cur.auto_entry)}}/出{{zh(AUTO_MODE,cur.auto_exit)}}</el-descriptions-item>
        </el-descriptions>
        <el-divider>权益</el-divider>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item v-for="(v,k) in cur.entitlements" :key="k" :label="featName(k)">{{entValText(k,v)}}</el-descriptions-item>
        </el-descriptions>
        <el-divider>账户</el-divider>
        <el-table :data="cur.accounts" size="small" border>
          <el-table-column prop="login" label="登录号"/><el-table-column prop="broker" label="经纪商"/>
          <el-table-column label="角色"><template #default="s">{{zh(ACCOUNT_ROLE,s.row.role)}}</template></el-table-column></el-table>
        <el-divider>常规操作</el-divider>
        <el-space wrap>
          <el-input-number v-model="opDays" size="small" :min="1" style="width:120px"/>
          <el-button size="small" type="primary" @click="op('extend',{days:opDays})">延期 {{opDays}} 天</el-button>
          <el-button size="small" @click="op('force_demo',{force:!cur.force_demo})">{{cur.force_demo?'解除强制DEMO':'强制DEMO'}}</el-button>
          <el-button v-if="cur.status==='banned'" size="small" type="success" @click="confirmOp('unban','解封用户 '+cur.username+'？')">解封</el-button>
        </el-space>
        <el-divider>功能可见性(命名开关)</el-divider>
        <div>
          <div v-for="f in FEATURES" :key="f.key" style="display:flex;align-items:center;gap:8px;padding:3px 0">
            <span style="width:120px;font-size:13px">{{f.name}}</span>
            <el-switch v-if="f.type==='bool'" v-model="featModel[f.key]" @change="setFeature(f)"/>
            <template v-else>
              <el-input-number v-model="featModel[f.key]" :min="0" size="small" style="width:110px"/>
              <el-button size="small" @click="setFeature(f)">设置</el-button>
            </template>
            <span style="color:#909399;font-size:11px">{{f.hint}}</span>
          </div>
        </div>
        <el-divider>⚠ 危险操作</el-divider>
        <el-collapse>
          <el-collapse-item title="展开危险操作(封禁 / 重置密钥)" name="danger">
            <el-space wrap>
              <el-button size="small" type="warning" @click="confirmOp('reset_key','重置 '+cur.username+' 的密钥？旧密钥立即失效,用户需用新密钥重新登录。')">重置密钥</el-button>
              <el-button v-if="cur.status!=='banned'" size="small" type="danger" @click="banUser">封禁用户</el-button>
            </el-space>
            <div style="color:#c0392b;font-size:11px;margin-top:6px">封禁=立即断该用户自动进/出场+强制DEMO+停止真金交易;重置密钥不可撤销。</div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-drawer>

    <el-dialog v-model="edlg" :title="edit.isNew?'新建用户':'编辑用户 '+edit.username" width="420">
      <el-form label-width="90">
        <el-form-item label="用户名"><el-input v-model="edit.username" :disabled="!edit.isNew" placeholder="唯一,登录标识"/></el-form-item>
        <el-form-item v-if="!edit.isNew && edit.owned && edit.owned.length" label="已购套餐">
          <el-tag v-for="p in edit.owned" :key="p" size="small" type="success" style="margin-right:4px">{{p}}</el-tag></el-form-item>
        <el-form-item label="主套餐"><el-select v-model="edit.plan" placeholder="选套餐(内购商品目录)" style="width:100%">
          <el-option v-for="p in planOpts" :key="p.key" :label="p.name+' ('+p.price+' '+(p.unit||'USDT')+')'" :value="p.key"/>
          <el-option label="basic(免费基础)" value="basic"/></el-select></el-form-item>
        <el-form-item label="飞书ID"><el-input v-model="edit.feishu_id" placeholder="可选"/></el-form-item>
        <el-form-item :label="edit.isNew?'有效天数':'延长天数'"><el-input-number v-model="edit.expire_days" :min="0" :max="3650"/>
          <span style="color:#909399;font-size:11px;margin-left:6px">{{edit.isNew?'新号有效期(默认30)':'0=不改到期'}}</span></el-form-item>
      </el-form>
      <div v-if="edit.isNew" style="color:#909399;font-size:11px">保存后生成密钥(License),请复制交付用户。</div>
      <template #footer><el-button @click="edlg=false">取消</el-button><el-button type="primary" @click="saveEdit">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { FEATURES, featName, entValText } from '../features'
import { zh, USER_STATUS, USER_STATUS_TAG, AUTO_MODE, AUTO_MODE_SHORT, ACCOUNT_ROLE } from '../dicts'
import ChartBox from '../components/ChartBox.vue'
import UserSelect from '../components/UserSelect.vue'
const geo=ref(null)
const planOpts=ref([])
async function loadPlans(){ try{ planOpts.value=(await api.iapCatalog()).products||[] }catch(e){} }
async function loadGeo(){ try{ geo.value=await api.usersGeoStats() }catch(e){} }
const geoBarOpt=computed(()=>{ const a=(geo.value.by_country||[]).slice(0,10).reverse(); return {
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}}, grid:{left:70,right:24,top:8,bottom:20},
  xAxis:{type:'value',axisLabel:{fontSize:10}}, yAxis:{type:'category',data:a.map(x=>x.name),axisLabel:{fontSize:11}},
  series:[{type:'bar',data:a.map(x=>x.users),itemStyle:{color:'#2E8BD6',borderRadius:[0,4,4,0]},barMaxWidth:20,label:{show:true,position:'right',fontSize:10}}]}})
const users=ref([]),q=ref(''),dlg=ref(false),cur=ref({}),opDays=ref(30)
const featModel=ref({})
const edlg=ref(false), edit=ref({isNew:true,username:'',plan:'',feishu_id:'',expire_days:30,owned:[]})
// 已购套餐: 从订单(排除充值/包月)取 product_key → 商品名, 去重
function ownedPackages(u){
  const orders=(u&&u.orders)||[]; const names=new Set()
  orders.forEach(o=>{ const k=o.product_key; if(!k||k==='_recharge'||String(k).startsWith('_sub_'))return
    const p=planOpts.value.find(x=>x.key===k); names.add(p?p.name:k) })
  return [...names]
}
function openCreate(){ edit.value={isNew:true,username:'',plan:'basic',feishu_id:'',expire_days:30,owned:[]}; edlg.value=true }
async function openEdit(row){
  let owned=[]
  try{ const d=await api.adminUser(row.username); owned=ownedPackages(d) }catch(e){}
  edit.value={isNew:false,username:row.username,plan:row.plan||'',feishu_id:row.feishu_id||'',expire_days:0,owned}; edlg.value=true
}
async function saveEdit(){
  if(!edit.value.username) return ElMessage.warning('请输入用户名')
  const op=edit.value.isNew?'create':'edit'
  try{ const r=await api.userOp({op,username:edit.value.username,plan:edit.value.plan,feishu_id:edit.value.feishu_id,expire_days:edit.value.expire_days})
    if(r.new_license) ElMessageBox.alert('新用户密钥(请复制交付):\n'+r.new_license,'创建成功',{type:'success'})
    else ElMessage.success('已保存')
    edlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function quickOp(row,op,msg){
  try{ await ElMessageBox.confirm(msg,'确认操作',{type:'warning'}) }catch(e){ return }
  try{ await api.userOp({op,username:row.username}); ElMessage.success('操作成功'); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'操作失败') }
}
function tag(m){ return zh(AUTO_MODE_SHORT, m) }
function fmt(t){ return t?String(t).slice(0,10):'—' }
function buildFeatModel(ent){ const m={}; FEATURES.forEach(f=>{ const v=ent&&ent[f.key]; m[f.key]=f.type==='bool'?(String(v).toLowerCase()==='true'):(v!=null&&v!==''?Number(v):0); }); featModel.value=m }
async function load(){ try{ users.value=(await api.adminUsers(q.value)).users||[] }catch(e){ ElMessage.error('加载失败') } }
async function openDetail(row){ try{ cur.value=await api.adminUser(row.username); buildFeatModel(cur.value.entitlements||{}); dlg.value=true }catch(e){ ElMessage.error('详情加载失败') } }
async function op(o,extra={}){
  try{ const r=await api.userOp({username:cur.value.username,op:o,...extra});
    ElMessage.success(r.new_license?('新密钥: '+r.new_license):'操作成功'); openDetail(cur.value); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'操作失败') }
}
async function setFeature(f){
  const val=f.type==='bool'?(featModel.value[f.key]?'true':'false'):String(featModel.value[f.key]||0)
  try{ await api.userOp({username:cur.value.username,op:'feature',feature_key:f.key,value:val}); ElMessage.success(f.name+' 已设为 '+(f.type==='bool'?(featModel.value[f.key]?'开':'关'):val)) }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'设置失败'); openDetail(cur.value) }
}
async function confirmOp(o,msg){ try{ await ElMessageBox.confirm(msg,'确认操作',{type:'warning'}); op(o) }catch(e){} }
async function banUser(){
  try{ const {value}=await ElMessageBox.prompt('封禁原因(将断自动进/出场+强制DEMO+停真金)','⚠ 封禁 '+cur.value.username,{inputPlaceholder:'如:风控/违规',type:'warning'})
    op('ban',{reason:value||'manual'}) }catch(e){}
}
onMounted(()=>{ load(); loadGeo(); loadPlans() })
</script>
