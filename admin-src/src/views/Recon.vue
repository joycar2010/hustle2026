<template>
  <el-card><template #header>跨用户对账 · 三源核对</template>
    <el-alert type="info" :closable="false" title="对账口径：引擎评估(eval) ↔ 双腿持仓(positions) ↔ 账户(account) 三源一致性" style="margin-bottom:12px"/>
    <el-table :data="rows" size="small" border>
      <el-table-column prop="user" label="用户"/>
      <el-table-column prop="symbol" label="品种"/>
      <el-table-column prop="mainLots" label="主腿手数"/>
      <el-table-column prop="hedgeLots" label="对冲手数"/>
      <el-table-column label="单腿"><template #default="s"><el-tag size="small" :type="s.row.singleLeg?'danger':'success'">{{s.row.singleLeg?('单腿!'+(s.row.missing||'')):'齐'}}</el-tag></template></el-table-column>
      <el-table-column label="对账结论"><template #default="s"><el-tag size="small" :type="s.row.ok?'success':'warning'">{{s.row.ok?'一致':'偏差'}}</el-tag></template></el-table-column>
    </el-table>
    <el-divider/>
    <el-descriptions :column="3" border size="small">
      <el-descriptions-item label="市场">{{market}}</el-descriptions-item>
      <el-descriptions-item label="循环对数">{{pairs}}</el-descriptions-item>
      <el-descriptions-item label="单腿计数">{{singleCnt}}</el-descriptions-item>
    </el-descriptions>
  </el-card>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
const rows=ref([]),market=ref('--'),pairs=ref(0),singleCnt=ref(0); let timer=null
async function load(){
  try{ const st=await api.engineState()
    market.value=st.market?.closed?('休市('+st.market.why+')'):'开市'; pairs.value=st.cycle?.pairs||0; singleCnt.value=st.cycle?.single_leg||0
    const ev=st.eval||{}; rows.value=Object.entries(ev).map(([user,e])=>({user,symbol:e.symbol,mainLots:e.main_lots,hedgeLots:e.hedge_lots,singleLeg:e.single_leg,missing:e.missing,ok:!e.single_leg}))
  }catch(e){}
}
onMounted(()=>{ load(); timer=setInterval(load,3000) }); onUnmounted(()=>clearInterval(timer))
</script>
