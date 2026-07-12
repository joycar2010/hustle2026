<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span class="ch"><el-icon><TrendCharts/></el-icon> 平台总览 · 经营 KPI</span>
        <span style="float:right"><el-select v-model="days" size="small" style="width:110px" @change="load">
          <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load" style="margin-left:8px">刷新</el-button></span>
      </template>
      <el-row :gutter="12" v-if="ov">
        <el-col :span="4"><el-card class="stat-card"><div class="l">总用户</div><div class="v">{{ov.users.total}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">活跃用户</div><div class="v">{{ov.users.active}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">试用中</div><div class="v">{{ov.users.trialing}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">付费用户</div><div class="v">{{ov.users.paid}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">内购收入</div><div class="v up">{{ov.iap.revenue}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">区间成交</div><div class="v">{{ov.deals.count}}</div></el-card></el-col>
      </el-row>
    </el-card>

    <el-row :gutter="12">
      <el-col :span="8"><el-card><template #header><span class="ch"><el-icon><User/></el-icon> 用户构成</span></template>
        <ChartBox v-if="ov" :option="userRingOpt" :height="240"/></el-card></el-col>
      <el-col :span="16"><el-card><template #header><span class="ch"><el-icon><Money/></el-icon> 收入趋势</span></template>
        <ChartBox v-if="rev" :option="revTrendOpt" :height="240"/></el-card></el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="12"><el-card><template #header><span class="ch"><el-icon><Coin/></el-icon> 盈亏 / 手续费(区间)</span></template>
        <ChartBox v-if="ov" :option="pnlBarOpt" :height="240"/></el-card></el-col>
      <el-col :span="12"><el-card><template #header><span class="ch"><el-icon><Share/></el-icon> Top 代理(累计佣金)</span></template>
        <ChartBox v-if="ov&&ov.top_agents&&ov.top_agents.length" :option="topAgentOpt" :height="240"/>
        <div v-else style="text-align:center;color:#909399;padding:40px">暂无代理佣金数据</div></el-card></el-col>
    </el-row>

    <!-- 全渠道对比(原「全渠道看板」并入此处) -->
    <el-card style="margin-top:12px">
      <template #header><span class="ch"><el-icon><DataAnalysis/></el-icon> 全渠道获客/转化/营收对比</span>
        <span style="float:right;font-size:12px;color:#909399">员工 / 代理 / 自然流量 三渠道 · 近{{days}}天</span></template>
      <el-row :gutter="12" v-if="chans">
        <el-col :span="8" v-for="ch in chOrder" :key="ch.key">
          <el-card class="stat-card" :body-style="{padding:'10px'}">
            <div style="font-weight:700;color:#08113A;margin-bottom:6px">{{ch.name}}</div>
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="获客">{{(chans[ch.key]||{}).users||0}}</el-descriptions-item>
              <el-descriptions-item label="试用">{{(chans[ch.key]||{}).trials||0}}</el-descriptions-item>
              <el-descriptions-item label="付费">{{(chans[ch.key]||{}).paid||0}}</el-descriptions-item>
              <el-descriptions-item label="转化率">{{(chans[ch.key]||{}).conv_rate||0}}%</el-descriptions-item>
              <el-descriptions-item label="营收">{{(chans[ch.key]||{}).revenue||0}}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>
      <el-row :gutter="12" style="margin-top:10px" v-if="chans">
        <el-col :span="8"><div class="chart-title">获客数</div><ChartBox :option="chOpt('users')" :height="200"/></el-col>
        <el-col :span="8"><div class="chart-title">付费转化率(%)</div><ChartBox :option="chOpt('conv_rate')" :height="200"/></el-col>
        <el-col :span="8"><div class="chart-title">营收(USDT)</div><ChartBox :option="chOpt('revenue')" :height="200"/></el-col>
      </el-row>
      <div v-if="!chans" style="text-align:center;color:#909399;padding:20px">暂无渠道数据</div>
    </el-card>
    <div style="color:#909399;font-size:12px;margin-top:8px">币产品交易分析 / AI套利分析已在「产品分析」页(支持下钻与 PDF 导出)。</div>
  </div>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useLiveRefresh } from '../composables/useLiveRefresh'
import { api } from '../api'
import ChartBox from '../components/ChartBox.vue'
const AZURE='#2E8BD6'
const days=ref(30),ov=ref(null),rev=ref(null),chans=ref(null)
const chOrder=[{key:'staff',name:'员工渠道'},{key:'agent',name:'代理渠道'},{key:'organic',name:'自然流量'}]
async function load(){
  try{ ov.value=await api.biOverview(days.value) }catch(e){ ElMessage.error('加载失败') }
  try{ rev.value=await api.revenue(days.value) }catch(e){}
  try{ chans.value=(await api.overviewChannels(days.value)).channels }catch(e){}
}
function chOpt(field){ const cats=chOrder.map(c=>c.name); const vals=chOrder.map(c=>(chans.value[c.key]||{})[field]||0); return {
  tooltip:{trigger:'axis'}, grid:{left:44,right:16,top:16,bottom:24},
  xAxis:{type:'category',data:cats,axisLabel:{fontSize:11}}, yAxis:{type:'value',axisLabel:{fontSize:10}},
  series:[{type:'bar',data:vals,itemStyle:{color:AZURE,borderRadius:[4,4,0,0]},barMaxWidth:44,label:{show:true,position:'top',fontSize:11}}]}}
const userRingOpt=computed(()=>{ const u=ov.value.users; return {
  tooltip:{trigger:'item'}, legend:{bottom:0,textStyle:{fontSize:11}},
  series:[{type:'pie',radius:['42%','66%'],center:['50%','44%'],avoidLabelOverlap:true,label:{show:true,formatter:'{b}\n{c}'},
    data:[{value:u.active,name:'活跃',itemStyle:{color:AZURE}},{value:u.trialing,name:'试用',itemStyle:{color:'#E6A23C'}},
      {value:u.paid,name:'付费',itemStyle:{color:'#67C23A'}},{value:Math.max(0,u.total-u.active-u.trialing),name:'其它',itemStyle:{color:'#C0C4CC'}}]}]}})
const revTrendOpt=computed(()=>{ const d=(rev.value.by_day||[]).slice().reverse(); return {
  tooltip:{trigger:'axis'}, grid:{left:48,right:16,top:20,bottom:28},
  xAxis:{type:'category',data:d.map(x=>String(x.day).slice(5)),axisLabel:{fontSize:10}},
  yAxis:{type:'value',axisLabel:{fontSize:10}},
  series:[{type:'line',smooth:true,data:d.map(x=>x.revenue),areaStyle:{opacity:.15,color:AZURE},lineStyle:{color:AZURE},itemStyle:{color:AZURE}}]}})
const pnlBarOpt=computed(()=>{ const d=ov.value.deals; return {
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}}, grid:{left:60,right:16,top:20,bottom:24},
  xAxis:{type:'category',data:['净盈亏','手续费','内购收入']}, yAxis:{type:'value',axisLabel:{fontSize:10}},
  series:[{type:'bar',barMaxWidth:48,label:{show:true,position:'top',fontSize:11},
    data:[{value:d.net_profit,itemStyle:{color:d.net_profit>=0?'#67C23A':'#F56C6C'}},
      {value:d.fees,itemStyle:{color:'#E6A23C'}},{value:Number(ov.value.iap.revenue)||0,itemStyle:{color:AZURE}}]}]}})
const topAgentOpt=computed(()=>{ const a=(ov.value.top_agents||[]).slice(0,8).reverse(); return {
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}}, grid:{left:70,right:30,top:8,bottom:20},
  xAxis:{type:'value',axisLabel:{fontSize:10}}, yAxis:{type:'category',data:a.map(x=>x.code),axisLabel:{fontSize:11}},
  series:[{type:'bar',data:a.map(x=>Number(x.comm)),itemStyle:{color:AZURE,borderRadius:[0,4,4,0]},barMaxWidth:20,label:{show:true,position:'right',fontSize:10}}]}})
const live=useLiveRefresh(load,{interval:20000})
onMounted(()=>{ load(); live.start() })
onBeforeUnmount(()=>live.stop())
</script>
<style scoped>
.ch{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.ch .el-icon{color:var(--el-color-primary)}
.stat-card .v{font-size:22px;font-weight:700;font-family:"Roboto Mono",monospace}
.stat-card .l{color:#46506e;font-size:12px}
.up{color:var(--el-color-success)}
</style>
