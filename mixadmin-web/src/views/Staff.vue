<template>
  <div>
    <el-card style="margin-bottom:12px" body-style="padding:10px">
      <template #header><span class="ch"><el-icon><Medal/></el-icon> 员工绩效积分 · 自动发放配置</span></template>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <el-switch v-model="perfCfg.enabled" active-text="自动发放开" inactive-text="关" @change="savePerfCfg"/>
        <span class="hint">每有效试用</span><el-input-number v-model="perfCfg.trial" :min="0" size="small" style="width:110px" @change="savePerfCfg"/>
        <span class="hint">每首单付费</span><el-input-number v-model="perfCfg.first_paid" :min="0" size="small" style="width:110px" @change="savePerfCfg"/>
        <span class="hint">每USDT订单额</span><el-input-number v-model="perfCfg.per_usdt" :min="0" :step="0.1" size="small" style="width:120px" @change="savePerfCfg"/>
        <span class="hint" style="color:#E6A23C">员工归因用户触发试用/首付/付费时, 自动给员工加绩效积分(内部激励, 与用户对冲积分隔离)</span>
      </div>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span class="ch"><el-icon><UserFilled/></el-icon> 员工推广 · 业绩概览</span>
        <span style="float:right"><el-button size="small" @click="loadStats">刷新</el-button></span></template>
      <el-table :data="stats" size="small" border max-height="280">
        <el-table-column prop="code" label="员工码" width="120"/>
        <el-table-column prop="name" label="姓名" width="100"/>
        <el-table-column prop="dept" label="部门" width="100"/>
        <el-table-column prop="users" label="获客数" width="90"/>
        <el-table-column prop="trials" label="试用数" width="90"/>
        <el-table-column prop="paid_users" label="付费数" width="90"/>
        <el-table-column label="转化率" width="90"><template #default="s">{{s.row.conv_rate}}%</template></el-table-column>
        <el-table-column prop="orders" label="订单数" width="80"/>
        <el-table-column label="营收(USDT)" width="100"><template #default="s"><b class="up">{{s.row.revenue}}</b></template></el-table-column>
        <el-table-column label="应发提成" width="90"><template #default="s"><b style="color:#E6A23C">{{s.row.commission_due}}</b></template></el-table-column>
        <el-table-column label="操作" width="120" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="openPerf(s.row.code)">绩效积分</el-button></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">业绩按 员工码归属用户 + 归因订单 实时聚合;员工体系与三级代理数据隔离、互不干涉。应发提成走薪资体系,与用户积分/代理佣金三者隔离。</div>
    </el-card>

    <el-card>
      <template #header><span>员工推广码管理</span>
        <span style="float:right"><el-button size="small" type="primary" @click="newStaff">+ 新增员工码</el-button>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <el-table :data="rows" size="small" border>
        <el-table-column prop="code" label="员工码" width="130"/>
        <el-table-column prop="name" label="姓名" width="110"/>
        <el-table-column prop="dept" label="部门" width="110"/>
        <el-table-column prop="username" label="绑定账号" width="130"/>
        <el-table-column label="默认试用" width="130"><template #default="s">{{s.row.default_trial_days}}天 · {{s.row.default_force_demo?'演示':'真金'}}</template></el-table-column>
        <el-table-column label="推广链接" min-width="200"><template #default="s">
          <el-input size="small" readonly :model-value="promoLink(s.row.code)"><template #append><el-button @click="copy(promoLink(s.row.code))">复制</el-button></template></el-input></template></el-table-column>
        <el-table-column label="状态" width="70"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="130" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="editStaff(s.row)">编辑</el-button>
          <el-button size="small" link type="danger" @click="delStaff(s.row.code)">删</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog :close-on-click-modal="false" v-model="dlg" :title="editing?'编辑员工码':'新增员工码'" width="460">
      <el-form label-width="100">
        <el-form-item label="员工码"><el-input v-model="cur.code" :disabled="editing" placeholder="唯一,如 staff_zhang"/></el-form-item>
        <el-form-item label="姓名"><el-input v-model="cur.name"/></el-form-item>
        <el-form-item label="部门"><el-input v-model="cur.dept" placeholder="如 销售一部"/></el-form-item>
        <el-form-item label="绑定账号"><el-input v-model="cur.username" placeholder="员工登录账号(可选)"/></el-form-item>
        <el-form-item label="默认试用天数"><el-input-number v-model="cur.default_trial_days" :min="1" :max="90"/></el-form-item>
        <el-form-item label="强制DEMO"><el-switch v-model="cur.default_force_demo"/></el-form-item>
        <el-divider content-position="left">阶梯提成(走薪资, 仅配置+核算)</el-divider>
        <el-form-item label="每有效试用"><el-input-number v-model="cur.comm_trial" :min="0" :step="1"/> <span style="color:#909399;font-size:11px">固定额(USDT/个有效试用)</span></el-form-item>
        <el-form-item label="首单比例"><el-input-number v-model="cur.comm_first_rate" :min="0" :max="1" :step="0.01"/> <span style="color:#909399;font-size:11px">0.10=首单额10%</span></el-form-item>
        <el-form-item label="复购比例"><el-input-number v-model="cur.comm_repeat_rate" :min="0" :max="1" :step="0.01"/> <span style="color:#909399;font-size:11px">0.05=复购额5%</span></el-form-item>
        <el-form-item label="启用"><el-switch v-model="cur.enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="pdlg" :title="'绩效积分 · '+perfCode" width="560">
      <el-form inline style="margin-bottom:8px">
        <el-form-item label="增减"><el-input-number v-model="perfAdj.delta" :step="10"/></el-form-item>
        <el-form-item label="事由"><el-input v-model="perfAdj.reason" size="small" placeholder="如: 达标奖励"/></el-form-item>
        <el-form-item><el-button type="primary" size="small" @click="doPerfAdjust">调整</el-button></el-form-item>
      </el-form>
      <el-table :data="perfLedger" size="small" border max-height="380">
        <el-table-column prop="created_at" label="时间" width="180"/>
        <el-table-column label="变动" width="90"><template #default="s"><span :class="s.row.delta>=0?'up':'down'">{{s.row.delta>=0?'+':''}}{{s.row.delta}}</span></template></el-table-column>
        <el-table-column prop="balance_after" label="余额" width="90"/>
        <el-table-column prop="reason" label="事由"/>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:6px">员工绩效积分与用户对冲积分完全隔离,仅内部激励用。</div>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const rows=ref([]),stats=ref([]),dlg=ref(false),cur=ref({}),editing=ref(false)
const pdlg=ref(false),perfCode=ref(''),perfLedger=ref([]),perfAdj=ref({delta:0,reason:''})
const perfCfg=ref({enabled:true,trial:10,first_paid:50,per_usdt:0.2})
async function loadPerfCfg(){ try{ const c=await api.staffPerfCfgGet(); perfCfg.value={enabled:!!c.enabled,trial:c.trial,first_paid:c.first_paid,per_usdt:c.per_usdt} }catch(e){} }
async function savePerfCfg(){ try{ await api.staffPerfCfgSave(perfCfg.value); ElMessage.success('绩效配置已保存') }catch(e){ ElMessage.error('保存失败') } }
// 推广链接: 指向用户端注册/试用页, 带 staff 参数(后端 _self_register 接受 staff_code 首归因)
function promoLink(code){ return 'https://qh.hustle2026.xyz/?staff='+encodeURIComponent(code) }
function copy(t){ try{ navigator.clipboard.writeText(t); ElMessage.success('已复制') }catch(e){ ElMessage.warning('复制失败,请手动选择') } }
async function load(){ try{ rows.value=(await api.staffList()).staff||[] }catch(e){ ElMessage.error('加载失败(需 员工推广 权限)') } }
async function loadStats(){ try{ stats.value=(await api.staffStats()).stats||[] }catch(e){} }
function newStaff(){ cur.value={code:'',name:'',dept:'',username:'',default_trial_days:3,default_force_demo:true,comm_trial:0,comm_first_rate:0,comm_repeat_rate:0,enabled:true}; editing.value=false; dlg.value=true }
function editStaff(r){ cur.value={...r}; editing.value=true; dlg.value=true }
async function save(){
  if(!cur.value.code) return ElMessage.warning('员工码不能为空')
  try{ await api.staffSave(cur.value); ElMessage.success('已保存'); dlg.value=false; load(); loadStats() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delStaff(code){
  try{ await ElMessageBox.confirm('删除员工码「'+code+'」?已归因用户的历史归属保留不变。','确认删除',{type:'warning'}) }catch(e){ return }
  try{ await api.staffDel(code); ElMessage.success('已删除'); load(); loadStats() }catch(e){ ElMessage.error('删除失败') }
}
async function openPerf(code){ perfCode.value=code; perfAdj.value={delta:0,reason:''}; try{ perfLedger.value=(await api.staffPerfLedger(code,100)).ledger||[]; pdlg.value=true }catch(e){ ElMessage.error('绩效流水加载失败') } }
async function doPerfAdjust(){
  if(!perfAdj.value.delta) return ElMessage.warning('增减值不能为 0')
  try{ const r=await api.staffPerfAdjust({staff_code:perfCode.value,delta:perfAdj.value.delta,reason:perfAdj.value.reason||'手工调整'})
    ElMessage.success('已调整, 绩效积分 '+r.perf_points); openPerf(perfCode.value) }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'调整失败') }
}
onMounted(()=>{ load(); loadStats(); loadPerfCfg() })
</script>
<style scoped>.up{color:#1aa86a}.down{color:#c0392b}.ch{display:inline-flex;align-items:center;gap:5px}.hint{font-size:12px;color:#909399}</style>
