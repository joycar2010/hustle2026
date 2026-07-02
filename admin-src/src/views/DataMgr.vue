<template>
  <div>
    <el-tabs v-model="tab" type="border-card">
      <!-- 版本管理(可推送 GitHub qh 分支) -->
      <el-tab-pane label="版本管理" name="version">
        <el-descriptions :column="1" border size="small" v-if="ver">
          <el-descriptions-item label="应用版本">{{ver.app_version}}</el-descriptions-item>
          <el-descriptions-item label="Python">{{ver.python}}</el-descriptions-item>
          <el-descriptions-item label="当前提交">{{ver.git}}</el-descriptions-item>
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

    </el-tabs>

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
onMounted(()=>{ loadVer(); loadDb(); loadSsl(); loadWs() })
</script>
<style scoped>
.ws-card-h{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--el-color-primary)}
.ws-card{border-radius:10px}
</style>
