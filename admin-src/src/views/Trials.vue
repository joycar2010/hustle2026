<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>试用体验 · 转化漏斗</span>
        <span style="float:right"><el-button size="small" @click="load">刷新</el-button></span></template>
      <el-row :gutter="12" v-if="sum">
        <el-col :span="6"><el-card class="stat-card"><div class="l">试用总数</div><div class="v">{{sum.total}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">试用中</div><div class="v">{{sum.trialing}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">已转化</div><div class="v up">{{sum.converted}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">转化率</div><div class="v">{{sum.conv_rate}}%</div></el-card></el-col>
      </el-row>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span>发放试用授权</span></template>
      <div style="margin-bottom:10px">
        <span style="font-size:12px;color:#606266;margin-right:8px">一键套餐:</span>
        <el-button v-for="tpl in TEMPLATES" :key="tpl.key" size="small"
          :type="g.key===tpl.key?'primary':'default'" @click="applyTpl(tpl)">{{tpl.label}}</el-button>
        <span style="color:#909399;font-size:11px;margin-left:8px">点一下填好天数+DEMO档,再补用户名发放</span>
      </div>
      <el-form inline>
        <el-form-item label="用户"><UserSelect v-model="g.username" width="170px"/></el-form-item>
        <el-form-item label="试用天数"><el-input-number v-model="g.days" size="small" :min="1" :max="90"/></el-form-item>
        <el-form-item label="强制DEMO"><el-switch v-model="g.force_demo"/></el-form-item>
        <el-form-item><el-button type="primary" size="small" @click="grant">发放试用</el-button></el-form-item>
      </el-form>
      <div style="color:#909399;font-size:11px">强制 DEMO=试用期只演示不真金下单(限风险); 试用到期自动降级。</div>
      <div v-if="g.key==='flagship'" style="color:#E6A23C;font-size:11px;margin-top:4px">⚠ 旗舰档为真金下单,请确认用户已注资再发放。</div>
    </el-card>

    <el-card>
      <template #header><span>试用用户列表 · 试用期行为</span></template>
      <el-table :data="trials" size="small" border>
        <el-table-column prop="username" label="用户" width="140"/>
        <el-table-column label="漏斗状态" width="100"><template #default="s">
          <el-tag size="small" :type="{trialing:'warning',converted:'success',lost:'info'}[s.row.funnel]">
            {{ {trialing:'试用中',converted:'已转化',lost:'已流失'}[s.row.funnel] }}</el-tag></template></el-table-column>
        <el-table-column prop="trial_started" label="试用起始"/>
        <el-table-column prop="trial_until" label="试用到期"/>
        <el-table-column prop="paid_until" label="付费到期"/>
        <el-table-column prop="deal_cnt" label="成交笔数" width="90"><template #default="s">
          <span :class="s.row.deal_cnt>0?'up':''">{{s.row.deal_cnt}}</span></template></el-table-column>
        <el-table-column label="操作" width="120"><template #default="s">
          <el-button size="small" @click="quickExtend(s.row.username)">续试用7天</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import UserSelect from '../components/UserSelect.vue'
const trials=ref([]),sum=ref(null)
// 一键套餐模板: 点选即填 days+force_demo(用户再补用户名发放)
const TEMPLATES=[
  {key:'taste',    label:'体验 3天·演示',  days:3,  force_demo:true},
  {key:'standard', label:'标准 14天·演示', days:14, force_demo:true},
  {key:'flagship', label:'旗舰 30天·真金', days:30, force_demo:false},
]
const g=ref({username:'',days:7,force_demo:true,key:''})
function applyTpl(tpl){ g.value.days=tpl.days; g.value.force_demo=tpl.force_demo; g.value.key=tpl.key }
async function load(){ try{ const d=await api.trials(); trials.value=d.trials||[]; sum.value=d.summary }catch(e){ ElMessage.error('加载失败') } }
async function grant(){
  if(!g.value.username) return ElMessage.warning('请输入用户')
  try{ const r=await api.trialGrant({username:g.value.username,days:g.value.days,force_demo:g.value.force_demo}); ElMessage.success('试用至 '+r.trial_until.slice(0,10)); load() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'发放失败(检查 Admin Token)') }
}
async function quickExtend(u){
  try{ await api.trialGrant({username:u,days:7,force_demo:true}); ElMessage.success('已续7天'); load() }
  catch(e){ ElMessage.error('失败') }
}
onMounted(load)
</script>
