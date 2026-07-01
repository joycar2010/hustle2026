<template>
  <el-card><template #header>告警中心</template>
    <el-timeline>
      <el-timeline-item v-for="(a,i) in alerts" :key="i" :timestamp="(a.ts||'').slice(11,19)" :type="a.lv==='err'?'danger':a.lv==='warn'?'warning':'primary'">{{a.msg}}</el-timeline-item>
    </el-timeline>
    <el-empty v-if="!alerts.length" description="暂无告警"/>
  </el-card>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
const alerts=ref([]); let timer=null
async function load(){ try{ alerts.value=(await api.alerts(50)).alerts||[] }catch(e){} }
onMounted(()=>{ load(); timer=setInterval(load,4000) }); onUnmounted(()=>clearInterval(timer))
</script>
