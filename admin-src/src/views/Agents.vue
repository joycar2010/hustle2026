<template>
  <div>
    <!-- ===== 可视化区 ===== -->
    <el-row :gutter="12" style="margin-bottom:12px">
      <el-col :span="8"><el-card body-style="padding:8px"><div class="chart-title">分销层级树</div>
        <ChartBox v-if="agents.length" :option="treeOpt" :height="260"/>
        <div v-else style="color:#909399;text-align:center;padding:30px">暂无代理</div></el-card></el-col>
      <el-col :span="10"><el-card body-style="padding:8px"><div class="chart-title">佣金分布(已结/待结)</div>
        <ChartBox v-if="agents.length" :option="commBarOpt" :height="260"/>
        <div v-else style="color:#909399;text-align:center;padding:30px">暂无代理</div></el-card></el-col>
      <el-col :span="6"><el-card body-style="padding:8px"><div class="chart-title">试用转化漏斗</div>
        <ChartBox v-if="funnel" :option="funnelOpt" :height="260"/>
        <div v-else style="color:#909399;text-align:center;padding:30px">加载中</div></el-card></el-col>
    </el-row>

    <el-card style="margin-bottom:12px">
      <template #header><span>三级代理 · 分销管理</span>
        <span style="float:right">
          <el-button size="small" type="primary" @click="newAgent">+ 新增代理</el-button>
          <el-button size="small" @click="load">刷新</el-button></span>
      </template>
      <el-table :data="agents" size="small" border>
        <el-table-column prop="code" label="推广码" width="110"/>
        <el-table-column prop="name" label="名称"/>
        <el-table-column label="层级" width="70"><template #default="s"><el-tag size="small">L{{s.row.level}}</el-tag></template></el-table-column>
        <el-table-column prop="parent_code" label="上级"/>
        <el-table-column label="费率(L1/L2/L3)" width="150"><template #default="s">
          {{(s.row.rate_l1*100).toFixed(0)}}% / {{(s.row.rate_l2*100).toFixed(0)}}% / {{(s.row.rate_l3*100).toFixed(0)}}%</template></el-table-column>
        <el-table-column prop="direct_users" label="直属用户" width="90"/>
        <el-table-column label="累计佣金" width="100"><template #default="s">{{Number(s.row.total_comm).toFixed(2)}}</template></el-table-column>
        <el-table-column label="待结算" width="100"><template #default="s"><span class="up">{{Number(s.row.unsettled_comm).toFixed(2)}}</span></template></el-table-column>
        <el-table-column label="操作" width="180"><template #default="s">
          <el-button size="small" @click="editAgent(s.row)">编辑</el-button>
          <el-button size="small" type="success" @click="settle(s.row.code)" :disabled="Number(s.row.unsettled_comm)<=0">结算</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span>绑定用户到代理</span></template>
      <el-form inline>
        <el-form-item label="用户"><UserSelect v-model="bind.username" width="140px"/></el-form-item>
        <el-form-item label="代理码"><el-select v-model="bind.agent_code" size="small" style="width:140px">
          <el-option v-for="a in agents" :key="a.code" :label="a.code+' ('+a.name+')'" :value="a.code"/></el-select></el-form-item>
        <el-form-item><el-button type="primary" size="small" @click="doBind">绑定</el-button></el-form-item>
      </el-form>
    </el-card>

    <el-card>
      <template #header><span>佣金流水</span>
        <span style="float:right"><el-select v-model="filterAgent" size="small" clearable placeholder="按代理" style="width:130px;margin-right:8px" @change="loadComm">
          <el-option v-for="a in agents" :key="a.code" :label="a.code" :value="a.code"/></el-select>
          <el-button size="small" @click="loadComm">刷新</el-button></span>
      </template>
      <el-table :data="comms" size="small" border max-height="320">
        <el-table-column prop="agent_code" label="代理" width="90"/>
        <el-table-column prop="username" label="消费用户"/>
        <el-table-column label="层级" width="70"><template #default="s">T{{s.row.tier}}</template></el-table-column>
        <el-table-column label="类型" width="80"><template #default="s">{{zh(ORDER_KIND,s.row.order_kind)}}</template></el-table-column>
        <el-table-column label="订单额" width="90"><template #default="s">{{Number(s.row.base_amount).toFixed(2)}}</template></el-table-column>
        <el-table-column label="费率" width="70"><template #default="s">{{(s.row.rate*100).toFixed(0)}}%</template></el-table-column>
        <el-table-column label="佣金" width="90"><template #default="s"><span class="up">{{Number(s.row.amount).toFixed(2)}}</span></template></el-table-column>
        <el-table-column label="结算" width="80"><template #default="s"><el-tag size="small" :type="s.row.settled?'success':'warning'">{{s.row.settled?'已结':'待结'}}</el-tag></template></el-table-column>
        <el-table-column prop="created_at" label="时间"/>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="cur.code&&editing?'编辑代理':'新增代理'" width="420">
      <el-form label-width="92">
        <el-form-item label="推广码"><el-input v-model="cur.code" :disabled="editing" placeholder="唯一码,用户注册带此码"/></el-form-item>
        <el-form-item label="名称"><el-input v-model="cur.name"/></el-form-item>
        <el-form-item label="上级代理码"><el-input v-model="cur.parent_code" placeholder="留空=顶级"/></el-form-item>
        <el-form-item label="L1费率 (%)"><el-input-number v-model="pct.l1" :step="1" :min="0" :max="100" :precision="1"/><span style="color:#909399;font-size:11px;margin-left:8px">本人(直属)分佣比例</span></el-form-item>
        <el-form-item label="L2费率 (%)"><el-input-number v-model="pct.l2" :step="1" :min="0" :max="100" :precision="1"/><span style="color:#909399;font-size:11px;margin-left:8px">下级代理消费回溯</span></el-form-item>
        <el-form-item label="L3费率 (%)"><el-input-number v-model="pct.l3" :step="1" :min="0" :max="100" :precision="1"/><span style="color:#909399;font-size:11px;margin-left:8px">再下一级回溯</span></el-form-item>
        <el-form-item label="示例回显">
          <span style="color:#909399;font-size:12px">用户消费 ¥100 → L1 得 <b class="up">¥{{(pct.l1||0).toFixed(1)}}</b> / L2 得 <b>¥{{(pct.l2||0).toFixed(1)}}</b> / L3 得 <b>¥{{(pct.l3||0).toFixed(1)}}</b></span>
        </el-form-item>
        <el-form-item label="联系方式"><el-input v-model="cur.contact"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="saveAgent">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { zh, ORDER_KIND } from '../dicts'
import ChartBox from '../components/ChartBox.vue'
import UserSelect from '../components/UserSelect.vue'
const AZURE='#2E8BD6'
const agents=ref([]),comms=ref([]),dlg=ref(false),cur=ref({}),editing=ref(false)
const pct=ref({l1:10,l2:5,l3:2}) // 百分比表单态(后端存 0-1 分数, 进出弹框 ×100/÷100)
const bind=ref({username:'',agent_code:''}),filterAgent=ref('')
const funnel=ref(null)
async function load(){ try{ agents.value=(await api.agents()).agents||[] }catch(e){ ElMessage.error('加载失败') } }
async function loadFunnel(){ try{ funnel.value=(await api.trials()).summary||null }catch(e){} }
// 分销层级树:按 parent_code 客户端建树
const treeOpt=computed(()=>{
  const list=agents.value, byCode={}, roots=[]
  list.forEach(a=>{ byCode[a.code]={name:`${a.code}\n${a.name||''}`, value:Number(a.total_comm||0), children:[]} })
  list.forEach(a=>{ const n=byCode[a.code]; if(a.parent_code&&byCode[a.parent_code]) byCode[a.parent_code].children.push(n); else roots.push(n) })
  const data = roots.length ? [{name:'平台', children:roots}] : [{name:'平台',children:[]}]
  return { tooltip:{trigger:'item',formatter:p=>`${p.name}<br>累计佣金 ${p.value||0}`},
    series:[{type:'tree',data,top:'4%',left:'12%',bottom:'4%',right:'18%',symbolSize:8,
      label:{position:'left',verticalAlign:'middle',align:'right',fontSize:10},
      leaves:{label:{position:'right',align:'left'}},itemStyle:{color:AZURE},lineStyle:{color:'#c0c8dd'},expandAndCollapse:true,initialTreeDepth:3}]}})
// 佣金分布:各代理 已结/待结 堆叠柱
const commBarOpt=computed(()=>{ const a=agents.value.slice().sort((x,y)=>Number(y.total_comm)-Number(x.total_comm)).slice(0,12); return {
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}}, legend:{data:['已结','待结'],bottom:0,textStyle:{fontSize:11}},
  grid:{left:50,right:16,top:14,bottom:34}, xAxis:{type:'category',data:a.map(x=>x.code),axisLabel:{fontSize:10,interval:0,rotate:a.length>6?30:0}},
  yAxis:{type:'value',axisLabel:{fontSize:10}},
  series:[
    {name:'已结',type:'bar',stack:'c',data:a.map(x=>Number(x.total_comm)-Number(x.unsettled_comm)),itemStyle:{color:'#67C23A'},barMaxWidth:26},
    {name:'待结',type:'bar',stack:'c',data:a.map(x=>Number(x.unsettled_comm)),itemStyle:{color:'#E6A23C'}}]}})
// 转化漏斗:试用→转化
const funnelOpt=computed(()=>{ const f=funnel.value; return {
  tooltip:{trigger:'item',formatter:'{b}: {c}'},
  series:[{type:'funnel',top:10,bottom:10,left:'6%',right:'6%',minSize:'20%',label:{fontSize:11},
    data:[{value:f.total||0,name:'试用总数'},{value:f.trialing||0,name:'试用中'},{value:f.converted||0,name:`已转化(${f.conv_rate||0}%)`}]}]}})
async function loadComm(){ try{ comms.value=(await api.commissions(filterAgent.value||'')).commissions||[] }catch(e){} }
function newAgent(){ cur.value={code:'',name:'',parent_code:'',contact:''}; pct.value={l1:10,l2:5,l3:2}; editing.value=false; dlg.value=true }
function editAgent(r){ cur.value={...r}; pct.value={l1:+(r.rate_l1*100).toFixed(1),l2:+(r.rate_l2*100).toFixed(1),l3:+(r.rate_l3*100).toFixed(1)}; editing.value=true; dlg.value=true }
async function saveAgent(){
  const payload={...cur.value, rate_l1:(pct.value.l1||0)/100, rate_l2:(pct.value.l2||0)/100, rate_l3:(pct.value.l3||0)/100}
  try{ await api.agentSave(payload); ElMessage.success('已保存'); dlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(检查 Admin Token)') }
}
async function doBind(){
  try{ await api.agentBind(bind.value); ElMessage.success('已绑定'); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'绑定失败') }
}
async function settle(code){
  try{ const r=await api.commissionSettle(code); ElMessage.success('已结算 '+r.settled+' 笔'); load(); loadComm() }
  catch(e){ ElMessage.error('结算失败') }
}
onMounted(()=>{ load(); loadComm(); loadFunnel() })
</script>
<style scoped>
.chart-title{font-size:13px;font-weight:600;color:#08113A;margin:2px 0 6px 4px}
</style>

