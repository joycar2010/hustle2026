<template>
  <div>
    <!-- 顶部: 全局急停横幅 -->
    <el-alert v-if="estopOn" type="error" :closable="false" show-icon
              title="全局急停生效中 — 所有用户自动进/出场已停, 无法重新武装" style="margin-bottom:12px"/>

    <!-- 全链路健康总览 -->
    <el-card style="margin-bottom:12px" body-style="padding:14px">
      <template #header><span class="ch"><el-icon><Monitor/></el-icon> 全链路运行监控</span>
        <span style="float:right">
          <el-tag size="small" :type="autoRefresh?'success':'info'" style="margin-right:8px">{{autoRefresh?('自动刷新 '+refreshSec+'s'):'已暂停'}}</el-tag>
          <el-button size="small" @click="autoRefresh=!autoRefresh">{{autoRefresh?'暂停':'恢复'}}自动</el-button>
          <el-button size="small" @click="load">刷新</el-button>
          <span v-if="sys" style="font-size:11px;color:#909399;margin-left:8px">更新 {{lastPull}}</span>
        </span></template>

      <el-row :gutter="12" v-if="sys">
        <el-col :span="4"><el-card class="stat-card" :class="cardCls(sys.bridges.main&&sys.bridges.main.ok)"><div class="l">主桥 8021</div>
          <div class="v" :class="sys.bridges.main&&sys.bridges.main.ok?'up':'down'">{{sys.bridges.main&&sys.bridges.main.ok?'正常':'异常'}}</div>
          <div class="s">{{sys.bridges.main&&sys.bridges.main.latency_ms!=null?sys.bridges.main.latency_ms+'ms':'—'}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card" :class="cardCls(sys.bridges.hedge&&sys.bridges.hedge.ok)"><div class="l">对冲桥 8001</div>
          <div class="v" :class="sys.bridges.hedge&&sys.bridges.hedge.ok?'up':'down'">{{sys.bridges.hedge&&sys.bridges.hedge.ok?'正常':'异常'}}</div>
          <div class="s">{{sys.bridges.hedge&&sys.bridges.hedge.latency_ms!=null?sys.bridges.hedge.latency_ms+'ms':'—'}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card" :class="cardCls(engineFresh)"><div class="l">引擎循环</div>
          <div class="v" :class="engineFresh?'up':'down'">{{ageTxt(sys.engine.cycle_age)}}</div>
          <div class="s">对{{sys.engine.cycle?sys.engine.cycle.pairs||0:0}} · 单腿{{sys.engine.cycle?sys.engine.cycle.single_leg||0:0}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card" :class="cardCls(samplerFresh)"><div class="l">点差采样</div>
          <div class="v" :class="samplerFresh?'up':'down'">{{ageTxt(sys.engine.spread_age)}}</div>
          <div class="s">{{sys.engine.sampler_err?'错误':(sys.engine.spread_count||0)+'条'}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card" :class="cardCls(sys.ws&&sys.ws.broadcaster!=='stale')"><div class="l">WS 连接</div>
          <div class="v">{{sys.ws?sys.ws.clients:0}}</div>
          <div class="s">{{wsTxt}}</div></el-card></el-col>
        <el-col :span="4"><el-card class="stat-card"><div class="l">真金 / 武装</div>
          <div class="v">{{sys.demo_mode?'演示':'真金'}}</div>
          <div class="s">进{{sys.auto?sys.auto.auto_entry_armed:0}} / 出{{sys.auto?sys.auto.auto_exit_armed:0}}</div></el-card></el-col>
      </el-row>

      <!-- 护栏闸状态 -->
      <el-descriptions v-if="sys" :column="4" border size="small" style="margin-top:12px">
        <el-descriptions-item label="市场"><el-tag size="small" :type="sys.engine.market&&sys.engine.market.closed?'warning':'success'">{{sys.engine.market?(sys.engine.market.closed?('休市·'+(sys.engine.market.why||'')):'运行'):'--'}}</el-tag></el-descriptions-item>
        <el-descriptions-item label="波动闸"><el-tag size="small" :type="gateFlucOn?'danger':'success'">{{gateFlucOn?'软暂停':'正常'}}</el-tag></el-descriptions-item>
        <el-descriptions-item label="背离闸"><el-tag size="small" :type="sys.gates&&sys.gates.div_tripped?'danger':'success'">{{sys.gates&&sys.gates.div_tripped?'已触发':'正常'}}</el-tag></el-descriptions-item>
        <el-descriptions-item label="采样器错误">{{sys.engine.sampler_err||'无'}}</el-descriptions-item>
        <el-descriptions-item label="自动出场心跳">{{ageTxt(sys.engine.auto_exit_age)}}</el-descriptions-item>
        <el-descriptions-item label="自动进单心跳">{{ageTxt(sys.engine.auto_entry_age)}}</el-descriptions-item>
        <el-descriptions-item label="纳管用户">{{sys.auto?sys.auto.users:0}}</el-descriptions-item>
        <el-descriptions-item label="引擎错误">{{sys.engine.err||'无'}}</el-descriptions-item>
      </el-descriptions>

      <el-divider/>
      <el-button v-if="!estopOn" type="danger" @click="doEstop"><el-icon style="margin-right:4px"><CircleClose/></el-icon>全局急停(停所有自动)</el-button>
      <el-button v-else type="success" @click="clearEstop">解除全局急停</el-button>
    </el-card>

    <!-- 实时告警流 -->
    <el-card style="margin-bottom:12px" body-style="padding:10px 14px">
      <template #header><span class="ch"><el-icon><BellFilled/></el-icon> 实时告警流</span>
        <span style="float:right;font-size:12px;color:#909399">最近 {{(sys&&sys.alerts?sys.alerts.length:0)}} 条 (裸空/单腿/强平/护栏/影子)</span></template>
      <div v-if="!sys||!sys.alerts||!sys.alerts.length" style="color:#909399;font-size:13px;padding:8px 2px">暂无告警</div>
      <div v-else style="max-height:240px;overflow-y:auto">
        <div v-for="(a,i) in sys.alerts" :key="i" class="alert-row">
          <el-tag size="small" :type="{err:'danger',warn:'warning',info:'info'}[a.lv]||'info'">{{ {err:'严重',warn:'警告',info:'信息'}[a.lv]||a.lv }}</el-tag>
          <span class="at">{{(a.ts||'').replace('T',' ').slice(5,19)}}</span>
          <span class="am">{{a.msg}}</span>
        </div>
      </div>
    </el-card>

    <!-- SSL 证书到期状态(从数据管理并入) -->
    <el-card style="margin-bottom:12px" body-style="padding:10px 14px">
      <template #header><span class="ch"><el-icon><Lock/></el-icon> SSL 证书到期状态</span>
        <span style="float:right"><el-button size="small" @click="loadSsl">刷新</el-button></span></template>
      <el-table :data="certs" size="small" border v-if="certs.length">
        <el-table-column prop="cert_name" label="名称" width="150"/>
        <el-table-column prop="domain_name" label="域名"/>
        <el-table-column label="到期" width="200"><template #default="s">
          <span :class="s.row.days_left!=null&&s.row.days_left<30?'down':(s.row.days_left!=null&&s.row.days_left<60?'':'up')">
            {{(s.row.expires_at||'').slice(0,10)}} ({{s.row.days_left}}天)</span>
          <el-tag v-if="s.row.days_left!=null&&s.row.days_left<30" size="small" type="danger" style="margin-left:6px">即将到期</el-tag></template></el-table-column>
        <el-table-column label="部署" width="80"><template #default="s"><el-tag size="small" :type="s.row.is_deployed?'success':'info'">{{s.row.is_deployed?'已部署':'未部署'}}</el-tag></template></el-table-column>
      </el-table>
      <div v-else style="color:#909399;font-size:13px;padding:8px 2px">暂无证书记录(在「系统管理」页可上传/扫描 Let's Encrypt)</div>
    </el-card>

    <!-- 审计日志 -->
    <el-card>
      <template #header><span class="ch"><el-icon><Document/></el-icon> 审计日志</span>
        <span style="float:right"><el-input v-model="actionFilter" size="small" placeholder="按 action" style="width:140px;margin-right:6px"/>
          <el-button size="small" @click="loadAudit">查询</el-button></span></template>
      <el-table :data="audit" size="small" border max-height="360">
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
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const sys=ref(null),audit=ref([]),actionFilter=ref(''),autoRefresh=ref(true),refreshSec=10,lastPull=ref(''),certs=ref([])
let _timer=null
const estopOn=computed(()=>sys.value&&sys.value.auto&&sys.value.auto.global_estop)
// 新鲜度阈值: 引擎循环 5s 一轮, >15s 视为停滞; 采样器 >60s 视为停更
const engineFresh=computed(()=>sys.value&&sys.value.engine.cycle_age!=null&&sys.value.engine.cycle_age<15)
const samplerFresh=computed(()=>sys.value&&sys.value.engine.spread_age!=null&&sys.value.engine.spread_age<60)
const gateFlucOn=computed(()=>sys.value&&sys.value.gates&&sys.value.gates.fluctuation&&sys.value.gates.fluctuation.paused)
const wsTxt=computed(()=>{ const b=sys.value&&sys.value.ws&&sys.value.ws.broadcaster; return b==='running'?'运行中':b==='stale'?'停滞':'空闲' })
function cardCls(ok){ return ok?'':'stat-bad' }
function ageTxt(a){ if(a==null)return '—'; if(a<60)return a+'s'; if(a<3600)return Math.floor(a/60)+'m'; return Math.floor(a/3600)+'h' }
async function load(){ try{ sys.value=await api.system(); lastPull.value=new Date().toTimeString().slice(0,8) }catch(e){ ElMessage.error('系统状态加载失败') } }
async function loadAudit(){ try{ audit.value=(await api.auditLog(100,actionFilter.value)).audit||[] }catch(e){} }
async function loadSsl(){ try{ certs.value=(await api.dmSslList()).certificates||[] }catch(e){} }
async function doEstop(){
  try{ await ElMessageBox.confirm('确认全局急停？将停止所有用户的自动进/出场,且无法重新武装直到解除。','危险操作',{type:'warning'})
    await api.estop(); ElMessage.success('全局急停已生效'); load() }catch(e){ if(e!=='cancel')ElMessage.error('急停失败') }
}
async function clearEstop(){ try{ await api.estopClear(); ElMessage.success('已解除急停'); load() }catch(e){ ElMessage.error('失败') } }
function tick(){ if(autoRefresh.value) load() }
onMounted(()=>{ load(); loadAudit(); loadSsl(); _timer=setInterval(tick,refreshSec*1000) })
onUnmounted(()=>{ if(_timer)clearInterval(_timer) })
</script>
<style scoped>
.stat-card .s{font-size:11px;color:#909399;margin-top:2px;font-family:"Roboto Mono",monospace}
.stat-bad{box-shadow:0 0 0 1px var(--el-color-danger) inset}
.alert-row{display:flex;align-items:center;gap:8px;padding:5px 2px;border-bottom:1px solid var(--el-border-color-lighter);font-size:12.5px}
.alert-row .at{color:#909399;font-family:"Roboto Mono",monospace;flex:0 0 auto}
.alert-row .am{color:var(--el-text-color-primary);flex:1;word-break:break-all}
</style>
