<template>
  <div>
    <el-card style="margin-bottom:12px" body-style="padding:10px">
      <template #header><span class="ch"><el-icon><Medal/></el-icon> 会员等级分布</span>
        <span style="float:right;font-size:12px;color:#909399">等级=订阅档 与 成长值(累计消费×10)就高生效</span></template>
      <el-row :gutter="12" v-if="dist.length">
        <el-col :span="14"><ChartBox :option="distOpt" :height="180"/></el-col>
        <el-col :span="10">
          <el-table :data="dist" size="small" border max-height="180">
            <el-table-column label="等级" width="70"><template #default="s">L{{s.row.level}}</template></el-table-column>
            <el-table-column prop="name" label="名称"/>
            <el-table-column prop="count" label="人数" width="80"/>
          </el-table>
        </el-col>
      </el-row>
      <div v-else style="color:#909399;text-align:center;padding:16px">暂无会员数据</div>
    </el-card>

    <el-card>
      <template #header><span>会员与积分 · 用户列表</span>
        <span style="float:right;display:inline-flex;align-items:center;gap:6px">
          <UserSelect v-model="q" width="170px" placeholder="搜用户名"/>
          <el-button size="small" @click="load">查询</el-button></span></template>
      <el-table :data="users" size="small" border>
        <el-table-column label="用户" width="150"><template #default="s">
          <span>{{s.row.username}}</span>
          <div v-if="s.row.nickname" style="font-size:11px;color:#909399">{{s.row.nickname}}</div></template></el-table-column>
        <el-table-column label="会员等级" width="120"><template #default="s">
          <el-tag size="small" :type="LVL_TAG[s.row.member_level]||'info'">L{{s.row.member_level}} {{s.row.member_level_name}}</el-tag></template></el-table-column>
        <el-table-column label="积分余额" width="100"><template #default="s"><b>{{s.row.points}}</b></template></el-table-column>
        <el-table-column label="成长值" width="100"><template #default="s">{{s.row.growth_value}}</template></el-table-column>
        <el-table-column prop="total_recharge" label="累计消费" width="100"/>
        <el-table-column prop="staff_code" label="归属员工" width="100"><template #default="s">{{s.row.staff_code||'—'}}</template></el-table-column>
        <el-table-column label="操作" width="180" fixed="right"><template #default="s">
          <el-button size="small" link type="primary" @click="openLedger(s.row)">积分流水</el-button>
          <el-button size="small" link type="warning" @click="openAdjust(s.row)">手工调整</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog :close-on-click-modal="false" v-model="ldlg" :title="'积分流水 · '+cur.username" width="640">
      <el-table :data="ledger" size="small" border max-height="440">
        <el-table-column prop="created_at" label="时间" width="180"/>
        <el-table-column label="变动" width="90"><template #default="s"><span :class="s.row.delta>=0?'up':'down'">{{s.row.delta>=0?'+':''}}{{s.row.delta}}</span></template></el-table-column>
        <el-table-column prop="balance_after" label="余额" width="90"/>
        <el-table-column prop="reason" label="事由"/>
        <el-table-column prop="ref_type" label="来源" width="90"/>
      </el-table>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="adlg" :title="'手工调整积分 · '+cur.username" width="420">
      <el-form label-width="80">
        <el-form-item label="当前积分"><b>{{cur.points}}</b></el-form-item>
        <el-form-item label="增减值"><el-input-number v-model="adj.delta" :step="10"/>
          <span style="color:#909399;font-size:11px;margin-left:6px">正=加, 负=扣(不可扣成负)</span></el-form-item>
        <el-form-item label="事由"><el-input v-model="adj.reason" placeholder="如: 活动补发/纠错"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="adlg=false">取消</el-button><el-button type="primary" @click="doAdjust">确定</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import ChartBox from '../components/ChartBox.vue'
import UserSelect from '../components/UserSelect.vue'
const LVL_TAG={0:'info',1:'success',2:'warning',3:'danger',4:'danger'}
const users=ref([]),dist=ref([]),q=ref('')
const ldlg=ref(false),adlg=ref(false),cur=ref({}),ledger=ref([])
const adj=ref({delta:0,reason:''})
const distOpt=computed(()=>{ const a=dist.value; return {
  tooltip:{trigger:'item'}, series:[{type:'pie',radius:['40%','70%'],
    data:a.map(x=>({name:'L'+x.level+' '+x.name,value:x.count})),
    label:{fontSize:11}}]}})
async function load(){ try{ const d=await api.members(q.value); users.value=d.users||[]; dist.value=d.level_dist||[] }catch(e){ ElMessage.error('加载失败(需 会员与积分 权限)') } }
async function openLedger(row){ cur.value=row; try{ ledger.value=(await api.pointsLedger(row.username,100)).ledger||[]; ldlg.value=true }catch(e){ ElMessage.error('流水加载失败') } }
function openAdjust(row){ cur.value=row; adj.value={delta:0,reason:''}; adlg.value=true }
async function doAdjust(){
  if(!adj.value.delta) return ElMessage.warning('增减值不能为 0')
  try{ const r=await api.pointsAdjust({username:cur.value.username,delta:adj.value.delta,reason:adj.value.reason||'手工调整'})
    ElMessage.success('已调整, 新余额 '+r.points); adlg.value=false; load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'调整失败') }
}
onMounted(load)
</script>
<style scoped>.up{color:#1aa86a}.down{color:#c0392b}.ch{display:inline-flex;align-items:center;gap:5px}</style>
