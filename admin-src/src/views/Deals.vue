<template>
  <el-card><template #header><span>成交记录 · 本地账本</span>
    <span style="float:right">
      <el-input v-model="user" size="small" style="width:130px;margin-right:8px"/>
      <el-button size="small" @click="load">{{t('refresh')}}</el-button>
      <el-button size="small" type="primary" @click="doSync">{{t('sync')}}</el-button>
    </span></template>
    <el-table :data="deals" size="small" height="calc(100vh - 230px)" stripe>
      <el-table-column prop="dealt_at" label="时间" width="170"><template #default="s">{{(s.row.dealt_at||'').slice(0,19).replace('T',' ')}}</template></el-table-column>
      <el-table-column prop="ticket" label="票号" width="120"/>
      <el-table-column prop="symbol" label="品种" width="90"/>
      <el-table-column label="方向" width="70"><template #default="s"><el-tag size="small" :type="s.row.side==='buy'?'danger':s.row.side==='sell'?'primary':'info'">{{ {buy:'买',sell:'卖',balance:'金'}[s.row.side]||s.row.side }}</el-tag></template></el-table-column>
      <el-table-column prop="lots" label="手数" width="80"/>
      <el-table-column prop="price" label="价格" width="100"/>
      <el-table-column label="盈亏" width="100"><template #default="s"><span :class="s.row.profit>=0?'up':'down'">{{s.row.profit>=0?'+':''}}{{Number(s.row.profit).toFixed(2)}}</span></template></el-table-column>
      <el-table-column prop="platform" label="平台" width="70"/>
    </el-table>
  </el-card>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const { t }=useI18n()
const user=ref('hedge_pro'),deals=ref([])
async function load(){ try{ deals.value=(await api.deals(user.value,200)).deals||[] }catch(e){ ElMessage.error('加载失败') } }
async function doSync(){ try{ const r=await api.sync(user.value,30); ElMessage.success(`同步 ${r.synced} 笔，跳过 ${r.skipped_dup}`); load() }catch(e){ ElMessage.error('同步失败') } }
onMounted(load)
</script>
