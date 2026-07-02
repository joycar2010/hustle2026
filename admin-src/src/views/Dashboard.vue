<template>
  <div>
    <el-alert v-if="ov&&ov.strategies&&ov.strategies.global_estop" type="error" :closable="false" show-icon
              title="全局急停生效中 — 所有用户自动进/出场已停" style="margin-bottom:12px"/>

    <!-- ========== 运营概览 ========== -->
    <el-card style="margin-bottom:12px" body-style="padding:14px">
      <template #header><span class="ch"><el-icon><TrendCharts/></el-icon> 运营概览</span>
        <span style="float:right"><el-select v-model="days" size="small" style="width:110px" @change="load">
          <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load" style="margin-left:8px">刷新</el-button></span></template>
      <el-row :gutter="12" v-if="ov">
        <el-col :span="4"><el-card class="stat-card"><div class="l">总用户</div><div class="v">{{ov.users.total}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">活跃用户</div><div class="v">{{ov.users.active}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">试用中</div><div class="v">{{ov.users.trialing}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">付费用户</div><div class="v">{{ov.users.paid}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">今日收入</div><div class="v up">{{ov.iap.revenue}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">内购订单</div><div class="v">{{ov.iap.orders}}</div></el-card></el-col>
      </el-row>
      <el-row :gutter="12" style="margin-top:12px">
        <el-col :span="10"><el-card body-style="padding:8px"><div class="chart-title">用户结构</div>
          <ChartBox v-if="ov" :option="userRingOpt" :height="220"/></el-card></el-col>
        <el-col :span="14"><el-card body-style="padding:8px"><div class="chart-title">收入趋势(按日)</div>
          <ChartBox v-if="rev" :option="revTrendOpt" :height="220"/></el-card></el-col>
      </el-row>
    </el-card>

    <!-- ========== 系统运行 ========== -->
    <el-card body-style="padding:14px">
      <template #header><span class="ch"><el-icon><Monitor/></el-icon> 系统运行</span>
        <span v-if="ov" style="float:right;font-size:12px">
          <el-tag size="small" :type="ov.strategies.global_estop?'danger':'success'">{{ov.strategies.global_estop?'急停中':'运行中'}}</el-tag></span></template>
      <el-row :gutter="12" v-if="ov">
        <el-col :span="6"><el-card class="stat-card"><div class="l">在跑自动进场</div><div class="v">{{ov.strategies.auto_entry}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">在跑自动出场</div><div class="v">{{ov.strategies.auto_exit}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">平台净盈亏(区间)</div><div class="v" :class="ov.deals.net_profit>=0?'up':'down'">{{ov.deals.net_profit}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">区间成交笔数</div><div class="v">{{ov.deals.count}}</div></el-card></el-col>
      </el-row>
      <el-row :gutter="12" style="margin-top:12px">
        <el-col :span="10"><el-card body-style="padding:8px"><div class="chart-title">告警级别占比</div>
          <ChartBox v-if="ov" :option="alertRingOpt" :height="220"/></el-card></el-col>
        <el-col :span="14"><el-card body-style="padding:8px">
          <div class="chart-title">最近告警</div>
          <div v-if="ov" style="max-height:200px;overflow:auto">
            <div v-for="(a,i) in ov.alerts.recent" :key="i" style="padding:5px 0;border-bottom:1px solid #eef0f6;font-size:12px">
              <el-tag size="small" :type="{err:'danger',warn:'warning',info:'info'}[a.lv]">{{ {err:'错',warn:'警',info:'信'}[a.lv] }}</el-tag>
              <span style="margin-left:8px">{{a.msg}}</span>
              <span style="float:right;color:#909399">{{(a.ts||'').slice(11,19)}}</span>
            </div>
            <div v-if="!ov.alerts.recent.length" style="color:#909399;text-align:center;padding:14px">暂无告警</div>
          </div></el-card></el-col>
      </el-row>
    </el-card>

    <!-- ========== Top 代理 ========== -->
    <el-card style="margin-top:12px" body-style="padding:8px">
      <div class="chart-title">Top 代理(累计佣金)</div>
      <ChartBox v-if="ov && ov.top_agents && ov.top_agents.length" :option="topAgentOpt" :height="Math.max(120, ov.top_agents.length*34)"/>
      <div v-else style="color:#909399;text-align:center;padding:14px">暂无代理数据</div>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import ChartBox from '../components/ChartBox.vue'
const days=ref(30),ov=ref(null),rev=ref(null)
const AZURE='#2E8BD6', NAVY='#08113A'
async function load(){
  try{ ov.value=await api.biOverview(days.value) }catch(e){ ElMessage.error('总控加载失败') }
  try{ rev.value=await api.revenue(days.value) }catch(e){}
}
const userRingOpt=computed(()=>{ const u=ov.value.users; return {
  tooltip:{trigger:'item'}, legend:{bottom:0,textStyle:{fontSize:11}},
  series:[{type:'pie',radius:['42%','66%'],center:['50%','44%'],avoidLabelOverlap:true,
    label:{show:true,formatter:'{b}\n{c}'},
    data:[{value:u.active,name:'活跃',itemStyle:{color:AZURE}},{value:u.trialing,name:'试用',itemStyle:{color:'#E6A23C'}},
      {value:u.paid,name:'付费',itemStyle:{color:'#67C23A'}},{value:Math.max(0,u.total-u.active-u.trialing),name:'其它',itemStyle:{color:'#C0C4CC'}}]}]}})
const revTrendOpt=computed(()=>{ const d=(rev.value.by_day||[]).slice().reverse(); return {
  tooltip:{trigger:'axis'}, grid:{left:48,right:16,top:20,bottom:28},
  xAxis:{type:'category',data:d.map(x=>String(x.day).slice(5)),axisLabel:{fontSize:10}},
  yAxis:{type:'value',axisLabel:{fontSize:10}},
  series:[{type:'line',smooth:true,data:d.map(x=>x.revenue),areaStyle:{opacity:.15,color:AZURE},lineStyle:{color:AZURE},itemStyle:{color:AZURE}}]}})
const alertRingOpt=computed(()=>{ const lv=ov.value.alerts.levels; return {
  tooltip:{trigger:'item'}, legend:{bottom:0,textStyle:{fontSize:11}},
  series:[{type:'pie',radius:['42%','66%'],center:['50%','44%'],label:{show:true,formatter:'{b} {c}'},
    data:[{value:lv.err,name:'错',itemStyle:{color:'#F56C6C'}},{value:lv.warn,name:'警',itemStyle:{color:'#E6A23C'}},
      {value:lv.info,name:'信',itemStyle:{color:'#909399'}}]}]}})
const topAgentOpt=computed(()=>{ const a=(ov.value.top_agents||[]).slice().reverse(); return {
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}}, grid:{left:70,right:24,top:8,bottom:20},
  xAxis:{type:'value',axisLabel:{fontSize:10}}, yAxis:{type:'category',data:a.map(x=>x.code),axisLabel:{fontSize:11}},
  series:[{type:'bar',data:a.map(x=>Number(x.comm)),itemStyle:{color:AZURE,borderRadius:[0,4,4,0]},barMaxWidth:20,label:{show:true,position:'right',fontSize:10}}]}})
let timer=null
onMounted(()=>{ load(); timer=setInterval(load,15000) })
onBeforeUnmount(()=>{ timer&&clearInterval(timer) })
</script>
<style scoped>
.chart-title{font-size:13px;font-weight:600;color:#08113A;margin:2px 0 6px 4px}
</style>
