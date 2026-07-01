<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>系统管理 · 健康 + 急停</span>
        <span style="float:right"><el-button size="small" @click="load">刷新</el-button></span></template>
      <el-alert v-if="sys&&sys.auto&&sys.auto.global_estop" type="error" :closable="false" show-icon
                title="⛔ 全局急停生效中 — 所有用户自动进/出场已停, 无法重新武装" style="margin-bottom:12px"/>
      <el-row :gutter="12" v-if="sys">
        <el-col :span="6"><el-card class="stat-card"><div class="l">主桥(8021)</div><div class="v" :class="sys.bridges.main&&sys.bridges.main.ok?'up':'down'">{{sys.bridges.main&&sys.bridges.main.ok?'正常':'异常'}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">对冲桥(8001)</div><div class="v" :class="sys.bridges.hedge&&sys.bridges.hedge.ok?'up':'down'">{{sys.bridges.hedge&&sys.bridges.hedge.ok?'正常':'异常'}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">真金模式</div><div class="v">{{sys.demo_mode?'演示':'真金'}}</div></el-card></el-col>
        <el-col :span="6"><el-card class="stat-card"><div class="l">自动武装(进/出)</div><div class="v">{{sys.auto?sys.auto.auto_entry_armed:0}}/{{sys.auto?sys.auto.auto_exit_armed:0}}</div></el-card></el-col>
      </el-row>
      <el-descriptions v-if="sys" :column="2" border size="small" style="margin-top:12px">
        <el-descriptions-item label="引擎循环">{{sys.engine.cycle?('对'+ (sys.engine.cycle.pairs||0)):'--'}}</el-descriptions-item>
        <el-descriptions-item label="市场">{{sys.engine.market?(sys.engine.market.closed?'休市':'运行'):'--'}}</el-descriptions-item>
        <el-descriptions-item label="自动出场心跳">{{sys.engine.auto_exit_last||'--'}}</el-descriptions-item>
        <el-descriptions-item label="自动进单心跳">{{sys.engine.auto_entry_last||'--'}}</el-descriptions-item>
      </el-descriptions>
      <el-divider/>
      <el-button v-if="!estopOn" type="danger" @click="doEstop">⛔ 全局急停(停所有自动)</el-button>
      <el-button v-else type="success" @click="clearEstop">解除全局急停</el-button>
    </el-card>

    <el-card>
      <template #header><span>审计日志</span>
        <span style="float:right"><el-input v-model="actionFilter" size="small" placeholder="按 action" style="width:140px;margin-right:6px"/>
          <el-button size="small" @click="loadAudit">查询</el-button></span></template>
      <el-table :data="audit" size="small" border max-height="380">
        <el-table-column prop="ts" label="时间" width="180"/>
        <el-table-column prop="username" label="用户" width="120"/>
        <el-table-column prop="action" label="操作"/>
        <el-table-column prop="actor" label="操作者" width="120"/>
        <el-table-column label="DEMO" width="70"><template #default="s"><el-tag size="small" :type="s.row.demo_mode?'info':'danger'">{{s.row.demo_mode?'演':'真'}}</el-tag></template></el-table-column>
        <el-table-column prop="result" label="结果"/>
      </el-table>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const sys=ref(null),audit=ref([]),actionFilter=ref('')
const estopOn=computed(()=>sys.value&&sys.value.auto&&sys.value.auto.global_estop)
async function load(){ try{ sys.value=await api.system() }catch(e){ ElMessage.error('系统状态加载失败') } }
async function loadAudit(){ try{ audit.value=(await api.auditLog(100,actionFilter.value)).audit||[] }catch(e){} }
async function doEstop(){
  try{ await ElMessageBox.confirm('确认全局急停？将停止所有用户的自动进/出场,且无法重新武装直到解除。','危险操作',{type:'warning'})
    await api.estop(); ElMessage.success('全局急停已生效'); load() }catch(e){ if(e!=='cancel')ElMessage.error('急停失败') }
}
async function clearEstop(){ try{ await api.estopClear(); ElMessage.success('已解除急停'); load() }catch(e){ ElMessage.error('失败') } }
onMounted(()=>{ load(); loadAudit() })
</script>
