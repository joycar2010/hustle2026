<template>
  <div>
    <el-tabs v-model="tab" type="border-card">
      <!-- 飞书 -->
      <el-tab-pane label="飞书通知" name="feishu">
        <el-alert :type="fs.connected?'success':'warning'" :closable="false" show-icon
          :title="fs.connected?'飞书 Open API 已连通':'未连通: '+(fs.error||'飞书 APPID/SECRET 未配置')" style="margin-bottom:12px"/>
        <el-form label-width="120" style="max-width:520px">
          <el-form-item label="App ID"><el-input v-model="fscfg.appid" size="small" placeholder="cli_ 开头 / 已配置留空=不改"/></el-form-item>
          <el-form-item label="App Secret"><el-input v-model="fscfg.secret" type="password" show-password size="small" placeholder="留空=不改"/></el-form-item>
          <el-form-item>
            <el-button type="primary" size="small" @click="saveFeishuCfg">保存凭证</el-button>
            <span style="color:#909399;font-size:12px;margin-left:8px">存服务端自管文件(600权限,离库),与 AI客服配置页同源。{{fscfg.appid_set?'(App ID 已配置)':''}}</span>
          </el-form-item>
        </el-form>
        <el-divider>测试发送</el-divider>
        <el-form inline>
          <el-form-item label="测试接收人"><el-input v-model="fsRecipient" size="small" style="width:260px" placeholder="open_id(ou_开头)/邮箱/手机号"/></el-form-item>
          <el-form-item><el-button type="primary" size="small" @click="testFeishu">发送测试卡片</el-button></el-form-item>
          <el-form-item><el-button size="small" @click="loadFeishuStatus">刷新连通</el-button></el-form-item>
        </el-form>
        <div style="color:#909399;font-size:12px">获取路径:飞书开放平台 → 应用 → 凭证与基础信息 → App ID / App Secret。</div>
      </el-tab-pane>

      <!-- 邮件 -->
      <el-tab-pane label="邮件(SMTP)" name="email">
        <el-form label-width="120" style="max-width:520px">
          <el-form-item label="SMTP 主机"><el-input v-model="email.smtp_host" size="small"/></el-form-item>
          <el-form-item label="端口"><el-input-number v-model="email.smtp_port" :min="1" :max="65535" size="small"/></el-form-item>
          <el-form-item label="用户名"><el-input v-model="email.smtp_user" size="small"/></el-form-item>
          <el-form-item label="密码"><el-input v-model="email.smtp_password" type="password" show-password size="small" placeholder="留空=不改"/></el-form-item>
          <el-form-item label="发件人"><el-input v-model="email.smtp_from" size="small" placeholder="默认=用户名"/></el-form-item>
          <el-form-item label="SSL"><el-switch v-model="email.use_ssl"/></el-form-item>
          <el-form-item label="启用"><el-switch v-model="email.is_enabled"/></el-form-item>
          <el-form-item>
            <el-button type="primary" size="small" @click="saveEmail">保存</el-button>
            <el-button size="small" @click="testEmail">发送测试邮件</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- 模板 -->
      <el-tab-pane label="通知模板" name="templates">
        <div style="margin-bottom:8px"><el-button type="primary" size="small" @click="newTpl">+ 新增模板</el-button>
          <el-button size="small" @click="loadTemplates">刷新</el-button></div>
        <el-table :data="templates" size="small" border>
          <el-table-column prop="template_name" label="名称" width="130"/>
          <el-table-column prop="category" label="分类" width="90"/>
          <el-table-column prop="title_template" label="标题模板"/>
          <el-table-column label="渠道" width="150"><template #default="s">
            <el-tag v-if="s.row.enable_feishu" size="small" type="success" style="margin-right:3px">飞书</el-tag>
            <el-tag v-if="s.row.enable_email" size="small" style="margin-right:3px">邮件</el-tag>
            <el-tag v-if="s.row.enable_marquee" size="small" type="warning">跑马灯</el-tag></template></el-table-column>
          <el-table-column label="启用" width="70"><template #default="s"><el-tag size="small" :type="s.row.is_enabled?'success':'info'">{{s.row.is_enabled?'是':'否'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="130"><template #default="s">
            <el-button size="small" @click="editTpl(s.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="delTpl(s.row.id)">删</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 网站通知/跑马灯 -->
      <el-tab-pane label="网站通知(跑马灯)" name="broadcast">
        <el-form label-width="90" style="max-width:520px">
          <el-form-item label="标题"><el-input v-model="bc.title" size="small"/></el-form-item>
          <el-form-item label="内容"><el-input v-model="bc.content" type="textarea" :rows="2"/></el-form-item>
          <el-form-item label="颜色"><el-color-picker v-model="bc.color"/></el-form-item>
          <el-form-item label="闪烁"><el-switch v-model="bc.blink"/></el-form-item>
          <el-form-item><el-button type="primary" size="small" @click="doBroadcast">立即广播到用户端跑马灯</el-button></el-form-item>
        </el-form>
        <div style="color:#909399;font-size:12px">广播即时推送到 Redis + 落 marquee 日志;用户端轮询 /api/notify/marquee/recent 展示。</div>
      </el-tab-pane>

      <!-- 发送日志 -->
      <el-tab-pane label="发送日志" name="logs">
        <div style="margin-bottom:8px">
          <el-select v-model="logCh" size="small" clearable placeholder="渠道" style="width:110px;margin-right:6px" @change="loadLogs">
            <el-option value="feishu" label="飞书"/><el-option value="email" label="邮件"/><el-option value="marquee" label="跑马灯"/></el-select>
          <el-button size="small" @click="loadLogs">刷新</el-button></div>
        <el-table :data="logs" size="small" border max-height="420">
          <el-table-column prop="created_at" label="时间" width="180"/>
          <el-table-column prop="template_name" label="名称"/>
          <el-table-column prop="channel" label="渠道" width="80"/>
          <el-table-column prop="recipient" label="接收人" width="160"/>
          <el-table-column label="状态" width="70"><template #default="s"><el-tag size="small" :type="s.row.status==='sent'?'success':'danger'">{{s.row.status==='sent'?'成功':'失败'}}</el-tag></template></el-table-column>
          <el-table-column prop="content" label="内容"/>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="tdlg" :title="tcur.id?'编辑模板':'新增模板'" width="520">
      <el-form label-width="92">
        <el-form-item label="名称"><el-input v-model="tcur.template_name"/></el-form-item>
        <el-form-item label="分类"><el-select v-model="tcur.category"><el-option value="system" label="系统"/><el-option value="trade" label="交易"/><el-option value="risk" label="风险"/><el-option value="marketing" label="营销"/></el-select></el-form-item>
        <el-form-item label="标题模板"><el-input v-model="tcur.title_template" placeholder="支持 {username} {detail} 等变量"/></el-form-item>
        <el-form-item label="内容模板"><el-input v-model="tcur.content_template" type="textarea" :rows="2"/></el-form-item>
        <el-form-item label="渠道">
          <el-checkbox v-model="tcur.enable_feishu">飞书</el-checkbox>
          <el-checkbox v-model="tcur.enable_email">邮件</el-checkbox>
          <el-checkbox v-model="tcur.enable_marquee">跑马灯</el-checkbox>
        </el-form-item>
        <el-form-item label="跑马灯颜色"><el-color-picker v-model="tcur.marquee_color"/> <el-checkbox v-model="tcur.marquee_blink" style="margin-left:10px">闪烁</el-checkbox></el-form-item>
        <el-form-item label="冷却(秒)"><el-input-number v-model="tcur.cooldown_seconds" :min="0"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="tcur.is_enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="tdlg=false">取消</el-button><el-button type="primary" @click="saveTpl">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
const tab=ref('feishu')
const fs=ref({connected:false,error:''}), fsRecipient=ref('')
const fscfg=ref({appid:'',secret:'',appid_set:false})
async function saveFeishuCfg(){
  try{ await api.channelConfig({channel:'feishu',appid:fscfg.value.appid,secret:fscfg.value.secret})
    ElMessage.success('已保存(热读生效)'); fscfg.value.appid=''; fscfg.value.secret=''; loadFeishuStatus(); loadFsCfgStatus() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(检查 Admin Token)') }
}
async function loadFsCfgStatus(){ try{ const s=await api.channelStatus(); fscfg.value.appid_set=!!(s.feishu&&s.feishu.fields&&s.feishu.fields.appid) }catch(e){} }
const email=ref({smtp_host:'',smtp_port:465,smtp_user:'',smtp_password:'',smtp_from:'',use_ssl:true,is_enabled:false})
const templates=ref([]), tdlg=ref(false), tcur=ref({})
const bc=ref({title:'',content:'',color:'#2E8BD6',blink:false,sound:'none'})
const logs=ref([]), logCh=ref('')
async function loadFeishuStatus(){ try{ fs.value=await api.notifyFeishuStatus() }catch(e){ ElMessage.error('状态加载失败(需超管)') } }
async function testFeishu(){ if(!fsRecipient.value)return ElMessage.warning('填测试接收人')
  try{ const r=await api.notifyFeishuTest(fsRecipient.value); r.status==='sent'?ElMessage.success('已发送'):ElMessage.error(r.detail||'失败') }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadEmail(){ try{ const d=await api.notifyEmailGet(); email.value={...email.value,...d,smtp_password:''} }catch(e){} }
async function saveEmail(){ try{ await api.notifyEmailSave(email.value); ElMessage.success('已保存') }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function testEmail(){ try{ const r=await api.notifyEmailTest(); r.status==='sent'?ElMessage.success('已发送'):ElMessage.error(r.detail||'失败') }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadTemplates(){ try{ templates.value=(await api.notifyTemplates()).templates||[] }catch(e){ ElMessage.error('加载失败') } }
function newTpl(){ tcur.value={id:0,template_name:'',category:'system',title_template:'',content_template:'',enable_feishu:true,enable_email:false,enable_marquee:true,priority:1,cooldown_seconds:0,marquee_color:'#2E8BD6',marquee_blink:false,sound_key:'none',is_enabled:true}; tdlg.value=true }
function editTpl(r){ tcur.value={...r}; tdlg.value=true }
async function saveTpl(){ try{ await api.notifyTemplateSave(tcur.value); ElMessage.success('已保存'); tdlg.value=false; loadTemplates() }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function delTpl(id){ try{ await api.notifyTemplateDel(id); ElMessage.success('已删除'); loadTemplates() }catch(e){ ElMessage.error('失败') } }
async function doBroadcast(){ if(!bc.value.title)return ElMessage.warning('填标题')
  try{ await api.notifyBroadcast(bc.value); ElMessage.success('已广播'); bc.value.content='' }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadLogs(){ try{ logs.value=(await api.notifyLogs(logCh.value)).logs||[] }catch(e){} }
onMounted(()=>{ loadFeishuStatus(); loadFsCfgStatus(); loadEmail(); loadTemplates(); loadLogs() })
</script>
