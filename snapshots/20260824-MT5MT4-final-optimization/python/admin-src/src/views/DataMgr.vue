<template>
  <div>
    <el-tabs v-model="tab" type="border-card">
      <!-- 版本管理(可推送 GitHub qh 分支) -->
      <el-tab-pane label="版本管理" name="version">
        <el-descriptions :column="2" border size="small" v-if="ver">
          <el-descriptions-item label="应用版本"><b style="color:var(--el-color-primary)">v{{ver.app_version}}</b>
            <span style="color:#909399;font-size:11px;margin-left:6px">(每次 GitHub 推送自增)</span></el-descriptions-item>
          <el-descriptions-item label="提交哈希">{{ver.git_hash}}<el-tag v-if="ver.git_branch" size="small" style="margin-left:6px">{{ver.git_branch}}</el-tag></el-descriptions-item>
          <el-descriptions-item label="提交时间">{{(ver.git_time||'').slice(0,19)}}</el-descriptions-item>
          <el-descriptions-item label="工作区状态">
            <el-tag size="small" :type="ver.git_dirty?'warning':'success'">{{ver.git_dirty?('有未推送改动 '+(ver.git_dirty_n||0)+' 项'):'干净(已备份)'}}</el-tag>
            <el-tag v-if="ver.ahead" size="small" type="warning" style="margin-left:6px">领先 origin {{ver.ahead}}</el-tag>
            <el-tag v-if="ver.behind" size="small" type="danger" style="margin-left:6px">落后 origin {{ver.behind}}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Python">{{ver.python}}</el-descriptions-item>
          <el-descriptions-item label="最新提交说明">{{ver.git_msg||'—'}}</el-descriptions-item>
        </el-descriptions>

        <el-divider>GitHub 推送 · qh 分支</el-divider>
        <el-alert type="info" :closable="false" show-icon
          title="把服务器 /opt/quanthedge 当前代码(app.py/engine/connector/web前端/admin后台+Vue源)提交并推送到 GitHub qh 分支。已排除密钥/venv/备份文件;FF 对齐,绝不强推。"
          style="margin-bottom:10px"/>
        <div style="display:flex;gap:8px;align-items:flex-start">
          <el-input v-model="pushMsg" type="textarea" :rows="2" placeholder="推送备注信息(必填),如:修复移动端点差图时间轴 + 消费记录独立页" style="flex:1"/>
          <el-button type="primary" :loading="pushing" :disabled="!pushMsg.trim()" @click="doPush">
            {{pushing?'推送中...':'推送到 GitHub'}}
          </el-button>
        </div>
        <el-progress v-if="pushProgress>0" :percentage="pushProgress" :status="pushProgress>=100?'success':undefined"
          :text-inside="true" :stroke-width="18" style="margin-top:10px"/>
        <div v-if="pushProgress>0&&pushProgress<100" style="color:#909399;font-size:12px;margin-top:4px">
          {{pushProgress<25?'准备/备份标签…':pushProgress<55?'暂存变更…':pushProgress<92?'与 origin 对齐 + 推送 GitHub…':'完成中…'}}
        </div>

        <el-divider>提交历史</el-divider>
        <el-table :data="ver?ver.history:[]" size="small" border max-height="300">
          <el-table-column prop="hash" label="哈希" width="90"/>
          <el-table-column prop="date" label="时间" width="200"/>
          <el-table-column prop="msg" label="说明"/>
        </el-table>
      </el-tab-pane>

      <!-- 数据库 -->
      <!-- 配置中心 -->
      <el-tab-pane label="配置中心" name="config">
        <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
          title="运行时热改配置(散在 Redis 的连接/A2T 目录参数收口于此)。env/数据库配置各有专页, 不在此中心。危险配置(读取源/执行方式)需 danger 能力。"/>
        <el-table :data="configs" size="small" border>
          <el-table-column prop="group" label="分组" width="70"/>
          <el-table-column prop="label" label="配置项" width="150"/>
          <el-table-column label="当前值" min-width="220"><template #default="s">
            <span v-if="s.row.type!=='json'" style="font-family:monospace">{{s.row.value||'(默认 '+(s.row.default||'空')+')'}}</span>
            <span v-else style="font-family:monospace;font-size:11px;color:#909399">{{s.row.value?(s.row.value.slice(0,60)+(s.row.value.length>60?'…':'')):'(空)'}}</span>
          </template></el-table-column>
          <el-table-column prop="apply" label="生效方式" width="140"/>
          <el-table-column label="操作" width="90" fixed="right"><template #default="s"><el-button size="small" @click="editCfg(s.row)">编辑</el-button></template></el-table-column>
        </el-table>
        <el-dialog v-model="cfgDlg" :title="'编辑配置 — '+(curCfg.label||'')" width="560">
          <div style="color:#909399;font-size:12px;margin-bottom:10px">{{curCfg.note}}</div>
          <el-select v-if="curCfg.type==='enum'" v-model="cfgVal" style="width:220px"><el-option v-for="o in (curCfg.options||[])" :key="o" :value="o" :label="o"/></el-select>
          <el-input v-else-if="curCfg.type==='json'" v-model="cfgVal" type="textarea" :rows="6" placeholder="JSON, 留空=删除该键回落默认"/>
          <el-input v-else v-model="cfgVal" placeholder="留空=删除该键"/>
          <template #footer><el-button @click="cfgDlg=false">取消</el-button><el-button type="primary" :loading="cfgSaving" @click="saveCfg">保存(热生效)</el-button></template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane label="数据库管理" name="db">
        <el-row :gutter="12" v-if="dbStats">
          <el-col :span="8"><el-card class="stat-card"><div class="l">数据库大小</div><div class="v">{{dbStats.size}}</div></el-card></el-col>
          <el-col :span="8"><el-card class="stat-card"><div class="l">表数量</div><div class="v">{{dbStats.table_count}}</div></el-card></el-col>
          <el-col :span="8"><el-card class="stat-card"><div class="l">活动连接</div><div class="v">{{dbStats.active_connections}}</div></el-card></el-col>
        </el-row>
        <div style="margin:10px 0">
          <el-button size="small" type="warning" @click="doBackup">备份数据库(pg_dump→本地)</el-button>
          <el-button size="small" type="danger" @click="doCleanup">清理过期日志(&gt;90天)</el-button>
          <el-button size="small" @click="loadDb">刷新</el-button>
        </div>
        <el-table :data="tables" size="small" border max-height="360" @row-click="viewTable">
          <el-table-column prop="name" label="表名"/>
          <el-table-column prop="row_count" label="行数" width="100"/>
          <el-table-column prop="size" label="占用" width="100"/>
          <el-table-column label="操作" width="80"><template #default="s"><el-button size="small" @click.stop="viewTable(s.row)">查看</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- SSL -->
      <el-tab-pane label="SSL 证书" name="ssl">
        <el-alert type="warning" :closable="false" show-icon title="SSL 部署为高危操作:写 /etc/ssl 并 reload nginx,影响线上访问,请谨慎。" style="margin-bottom:12px"/>
        <div style="margin-bottom:8px">
          <el-button size="small" type="primary" @click="sslDlg=true">+ 上传证书</el-button>
          <el-button size="small" @click="doScan">扫描 Let's Encrypt</el-button>
          <el-button size="small" @click="loadSsl">刷新</el-button>
        </div>
        <el-table :data="certs" size="small" border>
          <el-table-column prop="cert_name" label="名称" width="140"/>
          <el-table-column prop="domain_name" label="域名"/>
          <el-table-column prop="cert_type" label="类型" width="100"/>
          <el-table-column label="到期" width="160"><template #default="s">
            <span :class="s.row.days_left!=null&&s.row.days_left<30?'down':''">{{(s.row.expires_at||'').slice(0,10)}} ({{s.row.days_left}}天)</span></template></el-table-column>
          <el-table-column label="部署" width="70"><template #default="s"><el-tag size="small" :type="s.row.is_deployed?'success':'info'">{{s.row.is_deployed?'已部署':'未部署'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="170"><template #default="s">
            <el-button size="small" type="warning" @click="doDeploy(s.row)">部署</el-button>
            <el-button size="small" type="danger" :disabled="s.row.is_deployed" @click="doDelCert(s.row.id)">删</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Api2Trade -->
      <el-tab-pane label="Api2Trade" name="a2t">
        <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
          title="Api2Trade 免终端云接入(MT4/MT5)。一份订阅(平台凭证)可绑定多个 MT 账户;用户在客户端「对冲账户设置→连接方式:API 连接」注册后写入 UUID。订阅到期后引擎 fail-closed 拒绝调用。"/>
        <div style="margin-bottom:8px">
          <el-button size="small" type="primary" @click="a2tOpenNew">+ 新增订阅配置</el-button>
          <el-button size="small" @click="loadA2t">刷新</el-button>
        </div>
        <el-table :data="a2tList" size="small" border>
          <el-table-column prop="label" label="名称" width="130"/>
          <el-table-column prop="account" label="平台账号" width="150" show-overflow-tooltip/>
          <el-table-column label="套餐" width="90"><template #default="s">
            <el-tag size="small" :type="s.row.plan==='pro'?'warning':'info'">{{s.row.plan==='pro'?'Pro(无限)':'Single'}}</el-tag></template></el-table-column>
          <el-table-column prop="api_key" label="API Key(掩码)" width="140" show-overflow-tooltip/>
          <el-table-column label="有效期" width="150"><template #default="s">
            <span v-if="s.row.expires_at" :class="s.row.days_left!=null&&s.row.days_left<30?'down':''">
              {{s.row.expires_at}} <span v-if="s.row.days_left!=null">({{s.row.days_left}}天{{s.row.days_left<0?'·已过期':''}})</span></span>
            <span v-else style="color:#909399">未设置</span></template></el-table-column>
          <el-table-column label="绑定账户" width="90"><template #default="s">
            <el-tag size="small" type="success">{{s.row.bound_accounts}}</el-tag></template></el-table-column>
          <el-table-column label="启用" width="70"><template #default="s">
            <el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="240"><template #default="s">
            <el-button size="small" @click="a2tTest(s.row)" :loading="a2tTesting===s.row.id">测试</el-button>
            <el-button size="small" @click="a2tViewAcc(s.row)">账户</el-button>
            <el-button size="small" type="primary" @click="a2tEdit(s.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="a2tDel(s.row)">删</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

    </el-tabs>

    <!-- Api2Trade 配置编辑 -->
    <el-dialog :close-on-click-modal="false" v-model="a2tDlg" :title="a2tForm.id?'编辑 Api2Trade 订阅':'新增 Api2Trade 订阅'" width="560">
      <el-form label-width="110">
        <el-form-item label="名称"><el-input v-model="a2tForm.label" placeholder="如 主订阅/Pro"/></el-form-item>
        <el-form-item label="平台账号"><el-input v-model="a2tForm.account" placeholder="Api2Trade 注册邮箱/账号"/></el-form-item>
        <el-form-item label="套餐">
          <el-select v-model="a2tForm.plan" style="width:100%">
            <el-option label="Single(x-api-key)" value="single"/>
            <el-option label="Pro(专属URL + Basic Auth)" value="pro"/>
          </el-select>
        </el-form-item>
        <el-form-item label="API Key" v-if="a2tForm.plan==='single'">
          <el-input v-model="a2tForm.api_key" placeholder="留空则不修改(编辑时显示掩码)" show-password/>
        </el-form-item>
        <template v-if="a2tForm.plan==='pro'">
          <el-form-item label="专属 Base URL"><el-input v-model="a2tForm.base_url" placeholder="https://xxx.api2trade.com"/></el-form-item>
          <el-form-item label="Basic 用户名"><el-input v-model="a2tForm.basic_user"/></el-form-item>
          <el-form-item label="Basic 密码"><el-input v-model="a2tForm.basic_pass" placeholder="留空则不修改" show-password/></el-form-item>
        </template>
        <el-form-item label="有效期(到期)"><el-date-picker v-model="a2tForm.expires_at" type="date" value-format="YYYY-MM-DD" placeholder="订阅到期日,到期后 fail-closed" style="width:100%"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="a2tForm.enabled"/></el-form-item>
        <el-form-item label="备注"><el-input v-model="a2tForm.note" type="textarea" :rows="2"/></el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="a2tForm.id" @click="a2tCanary" :loading="a2tCanaryRun">延迟 Canary</el-button>
        <el-button @click="a2tDlg=false">取消</el-button>
        <el-button type="primary" @click="a2tDoSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- Api2Trade 账户列表 -->
    <el-dialog :close-on-click-modal="false" v-model="a2tAccDlg" title="Api2Trade 已注册账户" width="720">
      <el-table :data="a2tAccList" size="small" border max-height="440">
        <el-table-column prop="uuid" label="UUID" width="150" show-overflow-tooltip/>
        <el-table-column prop="account_number" label="账号" width="110"/>
        <el-table-column prop="account_server" label="服务器" show-overflow-tooltip/>
        <el-table-column prop="type" label="平台" width="120"/>
        <el-table-column label="绑定用户" width="120"><template #default="s">
          <span v-if="s.row.bound_user">{{s.row.bound_user}}<el-tag size="small" style="margin-left:4px">{{s.row.bound_role}}</el-tag></span>
          <span v-else style="color:#e6a23c">未绑定</span></template></el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="tblDlg" :title="'表数据 · '+tblName" width="80%">
      <el-table :data="tblRows" size="small" border max-height="480">
        <el-table-column v-for="c in tblCols" :key="c" :prop="c" :label="c" show-overflow-tooltip/>
      </el-table>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="sslDlg" title="上传 SSL 证书" width="560">
      <el-form label-width="90">
        <el-form-item label="名称"><el-input v-model="sslForm.cert_name" placeholder="如 qh主域名"/></el-form-item>
        <el-form-item label="域名"><el-input v-model="sslForm.domain_name" placeholder="留空则从证书 SAN 取"/></el-form-item>
        <el-form-item label="证书PEM"><el-input v-model="sslForm.cert_content" type="textarea" :rows="4" placeholder="-----BEGIN CERTIFICATE-----"/></el-form-item>
        <el-form-item label="私钥PEM"><el-input v-model="sslForm.key_content" type="textarea" :rows="4" placeholder="-----BEGIN PRIVATE KEY-----"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="sslDlg=false">取消</el-button><el-button type="primary" @click="doUpload">上传</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Odometer, Connection, RefreshRight } from '@element-plus/icons-vue'
import { api } from '../api'
const tab=ref('version')
const ver=ref(null), dbStats=ref(null), tables=ref([]), certs=ref([]), ws=ref(null)
// 配置中心
const configs=ref([]), cfgDlg=ref(false), curCfg=ref({}), cfgVal=ref(''), cfgSaving=ref(false)
async function loadConfigs(){ try{ configs.value=(await api.configList()).configs||[] }catch(e){} }
function editCfg(row){ curCfg.value={...row}; cfgVal.value=row.value||''; cfgDlg.value=true }
async function saveCfg(){ cfgSaving.value=true
  try{ await api.configSet(curCfg.value.key, cfgVal.value); ElMessage.success('已保存(热生效)'); cfgDlg.value=false; loadConfigs() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } finally{ cfgSaving.value=false } }
const tblDlg=ref(false), tblName=ref(''), tblCols=ref([]), tblRows=ref([])
const sslDlg=ref(false), sslForm=ref({cert_name:'',domain_name:'',cert_content:'',key_content:''})
// WS 面板派生态
const wsBcastType=computed(()=>{ const b=ws.value&&ws.value.ws&&ws.value.ws.broadcaster; return b==='running'?'success':b==='stale'?'danger':'info' })
const wsBcastText=computed(()=>{ const b=ws.value&&ws.value.ws&&ws.value.ws.broadcaster; return b==='running'?'运行中':b==='stale'?'停滞':b==='idle'?'空闲(无连接)':'—' })
function wsUptime(s){ s=Number(s)||0; const h=Math.floor(s/3600), m=Math.floor((s%3600)/60); return h+'h '+m+'m' }
const pushMsg=ref(''), pushing=ref(false), pushProgress=ref(0)
let _pushTimer=null
async function doPush(){
  if(!pushMsg.value.trim())return
  pushing.value=true; pushProgress.value=6
  // 后端 git push 为单次阻塞(无字节级进度), 前端乐观分段推进至 92%, 收到响应再填满
  _pushTimer=setInterval(()=>{ if(pushProgress.value<92)pushProgress.value+=Math.max(1,Math.round((92-pushProgress.value)/12)) }, 400)
  try{
    const r=await api.dmGitPush(pushMsg.value.trim())
    clearInterval(_pushTimer); pushProgress.value=100
    if(r.status==='success'){
      ElMessage.success(r.no_change?'无变更可推送(已与 origin/qh 一致)':('推送成功 → qh'+(r.version?(' · v'+r.version):'')))
      pushMsg.value=''
      loadVer()
    }else{
      ElMessage.error('推送失败: '+(r.output||'').slice(0,160))
    }
  }catch(e){
    clearInterval(_pushTimer)
    ElMessage.error('推送失败: '+(e?.response?.data?.detail||e?.message||'网络错误'))
  }finally{
    pushing.value=false
    setTimeout(()=>{ pushProgress.value=0 }, 2500)
  }
}
async function loadVer(){ try{ ver.value=await api.dmVersion() }catch(e){ ElMessage.error('需超管权限') } }
async function loadDb(){ try{ dbStats.value=await api.dmDbStats(); tables.value=(await api.dmDbTables()).tables||[] }catch(e){} }
async function viewTable(row){ try{ const d=await api.dmDbTable(row.name); tblName.value=row.name; tblCols.value=d.columns||[]; tblRows.value=d.rows||[]; tblDlg.value=true }catch(e){ ElMessage.error(e?.response?.data?.detail||'查询失败') } }
async function doBackup(){ try{ await ElMessageBox.confirm('执行 pg_dump 备份到服务器本地?','确认',{type:'warning'}); const r=await api.dmDbBackup(); r.status==='success'?ElMessage.success('已备份 '+r.size_mb+'MB'):ElMessage.error(r.output||'失败') }catch(e){} }
async function doCleanup(){ try{ await ElMessageBox.confirm('删除 90 天前的审计/通知日志?不可恢复。','危险操作',{type:'warning'}); const r=await api.dmDbCleanup(); ElMessage.success('已清理: '+JSON.stringify(r.deleted)) }catch(e){} }
async function loadSsl(){ try{ certs.value=(await api.dmSslList()).certificates||[] }catch(e){} }
async function doScan(){ try{ const r=await api.dmSslScan(); ElMessage.success('扫描 '+r.scanned+' 导入 '+r.added); loadSsl() }catch(e){ ElMessage.error('失败') } }
async function doUpload(){ try{ await api.dmSslUpload(sslForm.value); ElMessage.success('已上传'); sslDlg.value=false; loadSsl() }catch(e){ ElMessage.error(e?.response?.data?.detail||'上传失败') } }
async function doDeploy(row){ try{ await ElMessageBox.confirm('部署证书 '+row.domain_name+' 到 /etc/ssl 并 reload nginx?高危,影响线上。','高危确认',{type:'warning',confirmButtonText:'确认部署'})
  const r=await api.dmSslDeploy(row.id); ElMessage.success('已部署'+(r.nginx_reloaded?' + nginx已重载':' (nginx测试:'+r.nginx_test+')')); loadSsl() }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'部署失败') } }
async function doDelCert(id){ try{ await api.dmSslDelete(id); ElMessage.success('已删除'); loadSsl() }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadWs(){ try{ ws.value=await api.dmWsStats() }catch(e){} }
// ── Api2Trade ──
const a2tList=ref([]), a2tDlg=ref(false), a2tTesting=ref(0), a2tCanaryRun=ref(false)
const a2tForm=ref({id:0,label:'',account:'',plan:'single',api_key:'',base_url:'',basic_user:'',basic_pass:'',expires_at:'',enabled:true,note:''})
const a2tAccDlg=ref(false), a2tAccList=ref([])
async function loadA2t(){ try{ a2tList.value=(await api.a2tConfigs()).configs||[] }catch(e){ ElMessage.error(e?.response?.data?.detail||'加载失败') } }
function a2tOpenNew(){ a2tForm.value={id:0,label:'',account:'',plan:'single',api_key:'',base_url:'',basic_user:'',basic_pass:'',expires_at:'',enabled:true,note:''}; a2tDlg.value=true }
function a2tEdit(row){ a2tForm.value={id:row.id,label:row.label,account:row.account,plan:row.plan,api_key:'',base_url:row.base_url,basic_user:row.basic_user,basic_pass:'',expires_at:row.expires_at||'',enabled:row.enabled,note:row.note}; a2tDlg.value=true }
async function a2tDoSave(){ try{ await api.a2tSave(a2tForm.value); ElMessage.success('已保存'); a2tDlg.value=false; loadA2t() }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function a2tDel(row){ try{ await ElMessageBox.confirm('删除订阅配置「'+row.label+'」?','确认',{type:'warning'}); await api.a2tDelete(row.id); ElMessage.success('已删除'); loadA2t() }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'删除失败') } }
async function a2tTest(row){ a2tTesting.value=row.id; try{ const r=await api.a2tTest(row.id); ElMessage[r.expired?'warning':'success']('连通 · 延迟'+r.latency_ms+'ms · 账户'+r.accounts+'个'+(r.expired?' · ⚠订阅已过期':'')) }catch(e){ ElMessage.error(e?.response?.data?.detail||'测试失败') }finally{ a2tTesting.value=0 } }
async function a2tViewAcc(row){ try{ const r=await api.a2tAccounts(row.id); a2tAccList.value=r.accounts||[]; a2tAccDlg.value=true }catch(e){ ElMessage.error(e?.response?.data?.detail||'加载失败') } }
async function a2tCanary(){ a2tCanaryRun.value=true; try{ const r=await api.a2tCanary({id:a2tForm.value.id,n:10}); ElMessageBox.alert('延迟分布(ms): min '+r.min+' / p50 '+r.p50+' / p90 '+r.p90+' / max '+r.max+'\\n\\n结论: '+r.verdict,'Canary 结果 · N='+r.n,{type:r.p50<=300?'success':'warning'}) }catch(e){ ElMessage.error(e?.response?.data?.detail||'Canary 失败') }finally{ a2tCanaryRun.value=false } }
onMounted(()=>{ loadVer(); loadDb(); loadSsl(); loadWs(); loadA2t(); loadConfigs() })
</script>
<style scoped>
.ws-card-h{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--el-color-primary)}
.ws-card{border-radius:10px}
</style>
