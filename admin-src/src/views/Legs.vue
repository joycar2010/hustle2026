<template>
  <el-card><template #header><span>双腿监控</span><el-button size="small" style="float:right" @click="load">{{t('refresh')}}</el-button></template>
    <el-row :gutter="14">
      <el-col :span="12"><el-card shadow="never"><template #header><span class="dotok" :class="{doterr:!main.connected}"></span>{{t('main')}} · ICMarkets</template>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('account')">{{main.account}}</el-descriptions-item>
          <el-descriptions-item :label="t('server')">{{main.server}}</el-descriptions-item>
          <el-descriptions-item :label="t('balance')">{{num(main.balance)}}</el-descriptions-item>
          <el-descriptions-item :label="t('equity')">{{num(main.equity)}}</el-descriptions-item>
          <el-descriptions-item label="健康">{{main.healthy?'正常':'异常'}} (fail {{main.failures}})</el-descriptions-item>
        </el-descriptions></el-card></el-col>
      <el-col :span="12"><el-card shadow="never"><template #header><span class="dotok" :class="{doterr:!hedge.connected}"></span>{{t('hedge')}} · Bybit</template>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('account')">{{hedge.account}}</el-descriptions-item>
          <el-descriptions-item :label="t('server')">{{hedge.server}}</el-descriptions-item>
          <el-descriptions-item :label="t('balance')">{{num(hedge.balance)}}</el-descriptions-item>
          <el-descriptions-item :label="t('equity')">{{num(hedge.equity)}}</el-descriptions-item>
          <el-descriptions-item label="健康">{{hedge.healthy?'正常':'异常'}} (fail {{hedge.failures}})</el-descriptions-item>
        </el-descriptions></el-card></el-col>
    </el-row>
    <el-divider>双腿持仓</el-divider>
    <el-table :data="positions" size="small" empty-text="当前无持仓">
      <el-table-column prop="leg" label="腿" width="80"/><el-table-column prop="symbol" label="品种"/>
      <el-table-column prop="dir" label="方向" width="70"/><el-table-column prop="volume" label="手数"/>
      <el-table-column prop="price" label="开仓价"/><el-table-column prop="profit" label="浮盈"/>
    </el-table>
  </el-card>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
const { t }=useI18n()
const main=ref({}),hedge=ref({}),positions=ref([]); let timer=null
const num=n=>(n==null||isNaN(n))?'--':Number(n).toFixed(2)
async function load(){
  try{ const l=await api.legs(); main.value=l.status?.main||{}; hedge.value=l.status?.hedge||{}
    const rows=[]; const add=(leg,pl)=>{(pl?.positions||pl||[]).forEach(p=>rows.push({leg,symbol:p.symbol,dir:(p.type==0||p.type=='buy')?'买':'卖',volume:p.volume,price:p.price_open||p.price,profit:p.profit}))}
    add('主',l.positions?.main); add('对冲',l.positions?.hedge); positions.value=rows }catch(e){}
}
onMounted(()=>{ load(); timer=setInterval(load,3000) }); onUnmounted(()=>clearInterval(timer))
</script>
