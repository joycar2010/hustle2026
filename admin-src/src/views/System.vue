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
        <el-col :span="4"><el-card class="stat-card" :class="cardCls(fraOk)"><div class="l">FRA 代理 · A2T</div>
          <div class="v" :class="fraOk?'up':'down'">{{fraVal}}</div>
          <div class="s">{{fraSub}}</div></el-card></el-col>
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

    <!-- 双腿连接器监控 -->
    <el-card v-if="sys&&sys.connectors" style="margin-bottom:12px" body-style="padding:10px 14px">
      <template #header><span class="ch"><el-icon><Connection/></el-icon> 双腿连接器监控</span>
        <span style="float:right;font-size:12px;color:#909399">当前生效: <b :style="{color:sys.connectors.active_mode==='api'?'#e0863a':'#2E8BD6'}">{{connModeLbl(sys.connectors.active_mode)}}</b> (引擎实执行/取数链路)
          · Bridge <el-tag size="small" :type="sys.connectors.mode_health&&sys.connectors.mode_health.bridge?'success':'info'">{{sys.connectors.mode_health&&sys.connectors.mode_health.bridge?'健康':'离线'}}</el-tag>
          · API <el-tag size="small" :type="sys.connectors.mode_health&&sys.connectors.mode_health.api?'success':'info'">{{sys.connectors.mode_health&&sys.connectors.mode_health.api?'健康':'离线'}}</el-tag>
          <el-tag v-if="sys.connectors.inconsistent>0" size="small" type="danger" style="margin-left:6px">{{sys.connectors.inconsistent}} 个用户主/对冲连接方式不一致</el-tag>
        </span></template>
      <div v-if="sys.connectors.err" style="color:#e6a23c;font-size:13px;padding:6px 2px">{{sys.connectors.err}}</div>
      <el-table v-else :data="sys.connectors.users||[]" size="small" border max-height="300">
        <el-table-column prop="username" label="用户" width="130" show-overflow-tooltip/>
        <el-table-column label="主账户连接" width="150"><template #default="s">
          <el-tag size="small" :type="s.row.main_mode==='api'?'warning':s.row.main_mode?'success':'info'">{{connModeLbl(s.row.main_mode)}}</el-tag>
          <span v-if="s.row.main_login" style="color:#909399;font-size:11px;margin-left:4px">{{s.row.main_login}}</span></template></el-table-column>
        <el-table-column label="对冲账户连接" width="150"><template #default="s">
          <el-tag size="small" :type="s.row.hedge_mode==='api'?'warning':s.row.hedge_mode?'success':'info'">{{connModeLbl(s.row.hedge_mode)}}</el-tag>
          <span v-if="s.row.hedge_login" style="color:#909399;font-size:11px;margin-left:4px">{{s.row.hedge_login}}</span></template></el-table-column>
        <el-table-column label="一致性" width="110"><template #default="s">
          <el-tag size="small" :type="s.row.consistent?'success':'danger'">{{s.row.consistent?('一致·'+connModeLbl(s.row.eff_mode)):'不一致'}}</el-tag></template></el-table-column>
        <el-table-column label="可运行" width="100"><template #default="s">
          <el-tag size="small" :type="s.row.runnable?'success':'danger'">{{s.row.runnable?'可运行':'禁止'}}</el-tag></template></el-table-column>
        <el-table-column label="说明" show-overflow-tooltip><template #default="s">
          <span style="font-size:12px;color:#909399">{{connExplain(s.row)}}</span></template></el-table-column>
      </el-table>
      <div style="font-size:11.5px;color:#909399;margin-top:6px">规则：套利策略器自动运行前 / 三个历史端点查询前，校验主与对冲连接方式一致且该方式健康，否则 fail-closed 禁止执行。</div>
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
import { useLiveRefresh } from '../composables/useLiveRefresh'
const sys=ref(null),audit=ref([]),actionFilter=ref(''),autoRefresh=ref(true),refreshSec=10,lastPull=ref(''),certs=ref([])
const estopOn=computed(()=>sys.value&&sys.value.auto&&sys.value.auto.global_estop)
// 新鲜度阈值: 引擎循环 5s 一轮, >15s 视为停滞; 采样器 >60s 视为停更
const engineFresh=computed(()=>sys.value&&sys.value.engine.cycle_age!=null&&sys.value.engine.cycle_age<15)
const samplerFresh=computed(()=>sys.value&&sys.value.engine.spread_age!=null&&sys.value.engine.spread_age<60)
const gateFlucOn=computed(()=>sys.value&&sys.value.gates&&sys.value.gates.fluctuation&&sys.value.gates.fluctuation.paused)
const wsTxt=computed(()=>{ const b=sys.value&&sys.value.ws&&sys.value.ws.broadcaster; return b==='running'?'运行中':b==='stale'?'停滞':'空闲' })
// FRA 执行代理(a2t-bridge @ eu-central-1, 贴 Api2Trade 源站): 双腿 health 全绿才算在线
const fraOk=computed(()=>{ const f=sys.value&&sys.value.fra; return !!(f&&f.configured&&f.main&&f.main.ok&&f.hedge&&f.hedge.ok&&f.main.health&&f.main.health.a2t&&f.main.health.a2t.reachable) })
const fraVal=computed(()=>{ const f=sys.value&&sys.value.fra; if(!f||!f.configured)return '未配置'
  if(!fraOk.value)return '离线'
  const p50=f.main.health.a2t.lat_p50_ms; return p50!=null?('源站 '+p50+'ms'):'在线' })
const fraSub=computed(()=>{ const f=sys.value&&sys.value.fra; if(!f||!f.configured)return ''
  const rtt=(f.main&&f.main.latency_ms!=null)?('QH→FRA '+f.main.latency_ms+'ms'):'不可达'
  const armed=!!(f.main&&f.main.health&&f.main.health.trading_armed)
  return rtt+' · '+(armed?'已武装⚡':'未武装') })
function cardCls(ok){ return ok?'':'stat-bad' }
function connModeLbl(m){ return m==='api'?'API·Api2Trade':m==='bridge'?'Bridge云端':(m?m:'未设置') }
function connExplain(r){
  if(!r.main_mode||!r.hedge_mode) return '主/对冲未同时配置连接方式';
  if(!r.consistent) return '主('+connModeLbl(r.main_mode)+')与对冲('+connModeLbl(r.hedge_mode)+')不一致→禁止运行/查询';
  const mh=(sys.value&&sys.value.connectors&&sys.value.connectors.mode_health)||{};
  if(!mh[r.eff_mode]) return connModeLbl(r.eff_mode)+' 连接当前离线→禁止运行';
  return '一致且健康，可正常运行';
}
function ageTxt(a){ if(a==null)return '—'; if(a<60)return a+'s'; if(a<3600)return Math.floor(a/60)+'m'; return Math.floor(a/3600)+'h' }
async function load(){ try{ sys.value=await api.system(); lastPull.value=new Date().toTimeString().slice(0,8) }catch(e){ ElMessage.error('系统状态加载失败') } }
async function loadAudit(){ try{ audit.value=(await api.auditLog(100,actionFilter.value)).audit||[] }catch(e){} }
async function loadSsl(){ try{ certs.value=(await api.dmSslList()).certificates||[] }catch(e){} }
async function doEstop(){
  try{ await ElMessageBox.confirm('确认全局急停？将停止所有用户的自动进/出场,且无法重新武装直到解除。','危险操作',{type:'warning'})
    await api.estop(); ElMessage.success('全局急停已生效'); load() }catch(e){ if(e!=='cancel')ElMessage.error('急停失败') }
}
async function clearEstop(){ try{ await api.estopClear(); ElMessage.success('已解除急停'); load() }catch(e){ ElMessage.error('失败') } }
// L5 活保型轮询: 可见性暂停 + 失败指数退避 + 前台/联网自愈(替代裸 setInterval)
const live=useLiveRefresh(async()=>{ if(autoRefresh.value) await load() }, { interval: refreshSec*1000 })
onMounted(()=>{ load(); loadAudit(); loadSsl(); live.start() })
onUnmounted(()=>{ live.stop() })
</script>
<style scoped>
.stat-card .s{font-size:11px;color:#909399;margin-top:2px;font-family:"Roboto Mono",monospace}
.stat-bad{box-shadow:0 0 0 1px var(--el-color-danger) inset}
.alert-row{display:flex;align-items:center;gap:8px;padding:5px 2px;border-bottom:1px solid var(--el-border-color-lighter);font-size:12.5px}
.alert-row .at{color:#909399;font-family:"Roboto Mono",monospace;flex:0 0 auto}
.alert-row .am{color:var(--el-text-color-primary);flex:1;word-break:break-all}
</style>
