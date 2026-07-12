<template>
  <div>
    <el-card style="margin-bottom:12px" body-style="padding:10px">
      <template #header><span class="ch"><el-icon><DataAnalysis/></el-icon> 全渠道总看板</span>
        <span style="float:right">
          <el-select v-model="days" size="small" style="width:110px;margin-right:6px" @change="load">
            <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load">刷新</el-button></span></template>
      <el-row :gutter="12">
        <el-col :span="8" v-for="ch in chOrder" :key="ch.key">
          <el-card class="stat-card" :body-style="{padding:'12px'}">
            <div class="cn">{{ch.name}}</div>
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="获客数">{{ (data[ch.key]||{}).users || 0 }}</el-descriptions-item>
              <el-descriptions-item label="试用数">{{ (data[ch.key]||{}).trials || 0 }}</el-descriptions-item>
              <el-descriptions-item label="付费数">{{ (data[ch.key]||{}).paid || 0 }}</el-descriptions-item>
              <el-descriptions-item label="转化率">{{ (data[ch.key]||{}).conv_rate || 0 }}%</el-descriptions-item>
              <el-descriptions-item label="订单数">{{ (data[ch.key]||{}).orders || 0 }}</el-descriptions-item>
              <el-descriptions-item label="营收(USDT)"><b class="up">{{ (data[ch.key]||{}).revenue || 0 }}</b></el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <el-card>
      <template #header><span>渠道对比图</span></template>
      <el-row :gutter="12">
        <el-col :span="8"><div class="chart-title">获客数</div><ChartBox :option="barOpt('users')" :height="220"/></el-col>
        <el-col :span="8"><div class="chart-title">付费转化率(%)</div><ChartBox :option="barOpt('conv_rate')" :height="220"/></el-col>
        <el-col :span="8"><div class="chart-title">营收(USDT)</div><ChartBox :option="barOpt('revenue')" :height="220"/></el-col>
      </el-row>
      <div style="color:#909399;font-size:11px;margin-top:6px">渠道口径: 员工=有 staff_code 归因;代理=无员工但有代理归因;自然=两者皆无。统一转化漏斗口径。</div>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import ChartBox from '../components/ChartBox.vue'
const days=ref(30), data=ref({})
const chOrder=[{key:'staff',name:'员工渠道'},{key:'agent',name:'代理渠道'},{key:'organic',name:'自然流量'}]
function barOpt(field){
  const cats=chOrder.map(c=>c.name); const vals=chOrder.map(c=>(data.value[c.key]||{})[field]||0)
  return { tooltip:{trigger:'axis'}, grid:{left:44,right:16,top:16,bottom:24},
    xAxis:{type:'category',data:cats,axisLabel:{fontSize:11}}, yAxis:{type:'value',axisLabel:{fontSize:10}},
    series:[{type:'bar',data:vals,itemStyle:{color:'#2E8BD6',borderRadius:[4,4,0,0]},barMaxWidth:44,label:{show:true,position:'top',fontSize:11}}]}
}
async function load(){ try{ data.value=(await api.overviewChannels(days.value)).channels||{} }catch(e){ ElMessage.error('加载失败(需 全渠道看板 权限)') } }
onMounted(load)
</script>
<style scoped>
.ch{display:inline-flex;align-items:center;gap:5px}.up{color:#1aa86a}
.stat-card .cn{font-weight:700;margin-bottom:8px;color:#08113A}
.chart-title{font-size:13px;color:#606266;margin-bottom:4px;text-align:center}
</style>
