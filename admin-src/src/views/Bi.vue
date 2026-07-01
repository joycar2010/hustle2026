<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>平台总览 · 经营 KPI</span>
        <span style="float:right"><el-select v-model="days" size="small" style="width:110px" @change="load">
          <el-option :value="7" label="近7天"/><el-option :value="30" label="近30天"/><el-option :value="90" label="近90天"/></el-select>
          <el-button size="small" @click="load" style="margin-left:8px">刷新</el-button></span>
      </template>
      <el-row :gutter="12" v-if="ov">
        <el-col :span="4"><el-card class="stat-card"><div class="l">总用户</div><div class="v">{{ov.users.total}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">活跃用户</div><div class="v">{{ov.users.active}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">试用中</div><div class="v">{{ov.users.trialing}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">付费用户</div><div class="v">{{ov.users.paid}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">内购收入</div><div class="v">{{ov.iap.revenue}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">区间成交</div><div class="v">{{ov.deals.count}}</div></el-card></el-col>
      </el-row>
      <el-row :gutter="12" v-if="ov" style="margin-top:12px">
        <el-col :span="8"><el-card class="stat-card"><div class="l">平台净盈亏(区间)</div><div class="v" :class="ov.deals.net_profit>=0?'up':'down'">{{ov.deals.net_profit}}</div></el-card></el-col>
        <el-col :span="8"><el-card class="stat-card"><div class="l">手续费(区间)</div><div class="v">{{ov.deals.fees}}</div></el-card></el-col>
        <el-col :span="8"><el-card class="stat-card"><div class="l">内购订单</div><div class="v">{{ov.iap.orders}}</div></el-card></el-col>
      </el-row>
    </el-card>

    <el-card style="margin-bottom:12px">
      <template #header><span>Top 代理(累计佣金)</span></template>
      <el-table :data="ov?ov.top_agents:[]" size="small" border>
        <el-table-column prop="code" label="代理码"/>
        <el-table-column label="累计佣金"><template #default="s"><span class="up">{{s.row.comm}}</span></template></el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><span>币产品交易分析 · 跨用户(近{{days}}天)</span></template>
      <el-table :data="symbols" size="small" border>
        <el-table-column prop="symbol" label="币产品" width="120"/>
        <el-table-column prop="users" label="活跃用户" width="90"/>
        <el-table-column prop="deals" label="成交笔数" width="90"/>
        <el-table-column prop="volume" label="成交量(手)" width="110"/>
        <el-table-column label="净盈亏" width="100"><template #default="s"><span :class="s.row.net_profit>=0?'up':'down'">{{s.row.net_profit}}</span></template></el-table-column>
        <el-table-column prop="fees" label="手续费" width="90"/>
        <el-table-column prop="swap" label="过夜费" width="90"/>
        <el-table-column label="胜率" width="90"><template #default="s">{{s.row.win_rate==null?'—':s.row.win_rate+'%'}}</template></el-table-column>
      </el-table>
      <div v-if="!symbols.length" style="text-align:center;color:#909399;padding:18px">暂无成交数据</div>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const days=ref(30),ov=ref(null),symbols=ref([])
async function load(){
  try{ ov.value=await api.biOverview(days.value); symbols.value=(await api.biSymbols(days.value)).symbols||[] }
  catch(e){ ElMessage.error('加载失败') }
}
onMounted(load)
</script>
