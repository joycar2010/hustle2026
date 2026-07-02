<template>
  <div>
    <el-tabs v-model="tab" type="border-card">
      <!-- 飞书 -->
      <el-tab-pane name="feishu">
        <template #label><span class="tl"><el-icon><Bell/></el-icon> 飞书通知</span></template>
        <el-alert :type="fs.connected?'success':'warning'" :closable="false" show-icon
          :title="fs.connected?'飞书 Open API 已连通':'未连通: '+(fs.error||'飞书 APPID/SECRET 未配置')" style="margin-bottom:12px"/>
        <el-form label-width="120" style="max-width:520px">
          <el-form-item label="App ID"><el-input v-model="fscfg.appid" size="small" placeholder="cli_ 开头 / 已配置留空=不改"/></el-form-item>
          <el-form-item label="App Secret"><el-input v-model="fscfg.secret" type="password" show-password size="small" placeholder="留空=不改"  autocomplete="new-password"/></el-form-item>
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
      <el-tab-pane name="email">
        <template #label><span class="tl"><el-icon><Message/></el-icon> 邮件(SMTP)</span></template>
        <el-form label-width="120" style="max-width:520px">
          <el-form-item label="SMTP 主机"><el-input v-model="email.smtp_host" size="small"/></el-form-item>
          <el-form-item label="端口"><el-input-number v-model="email.smtp_port" :min="1" :max="65535" size="small"/></el-form-item>
          <el-form-item label="用户名"><el-input v-model="email.smtp_user" size="small"/></el-form-item>
          <el-form-item label="密码"><el-input v-model="email.smtp_password" type="password" show-password size="small" placeholder="留空=不改"  autocomplete="new-password"/></el-form-item>
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
      <el-tab-pane name="templates">
        <template #label><span class="tl"><el-icon><Document/></el-icon> 通知模板</span></template>
        <div style="margin-bottom:8px"><el-button type="primary" size="small" @click="newTpl">+ 新增模板</el-button>
          <el-button size="small" @click="loadTemplates">刷新</el-button></div>
        <el-table :data="templates" size="small" border>
          <el-table-column prop="template_name" label="名称" width="130"/>
          <el-table-column prop="category" label="分类" width="90"/>
          <el-table-column prop="title_template" label="标题模板"/>
          <el-table-column label="渠道" width="150"><template #default="s">
            <el-tag v-if="s.row.enable_feishu" size="small" type="success" style="margin-right:3px">飞书</el-tag>
            <el-tag v-if="s.row.enable_email" size="small" style="margin-right:3px">邮件</el-tag>
            <el-tag v-if="s.row.enable_marquee" size="small" type="warning">跑马灯</el-tag>
            <el-tag v-if="s.row.sound_key&&s.row.sound_key!=='none'" size="small" type="danger">声音·{{ soundName(s.row.sound_key) }}</el-tag></template></el-table-column>
          <el-table-column label="启用" width="70"><template #default="s"><el-tag size="small" :type="s.row.is_enabled?'success':'info'">{{s.row.is_enabled?'是':'否'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="130"><template #default="s">
            <el-button size="small" @click="editTpl(s.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="delTpl(s.row.id)">删</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 声音人设管理 -->
      <el-tab-pane name="sounds">
        <template #label><span class="tl"><el-icon><Microphone/></el-icon> 声音人设</span></template>
        <div style="margin-bottom:8px">
          <el-button type="primary" size="small" @click="newSound">+ 新增人设</el-button>
          <el-button size="small" @click="loadSounds">刷新</el-button>
          <span style="color:#909399;font-size:12px;margin-left:8px">声音走前端浏览器 TTS 合成(按人设调 语速/音调/挑声关键词);用户端播报时按模板的 sound_key 取对应人设参数朗读。</span>
        </div>
        <el-table :data="sounds" size="small" border>
          <el-table-column prop="key" label="标识" width="90"/>
          <el-table-column prop="name" label="名称" width="80"/>
          <el-table-column label="引擎" width="130"><template #default="s">
            <el-tag size="small" :type="s.row.engine==='edge'?'success':'info'">{{s.row.engine==='edge'?'神经语音':'浏览器TTS'}}</el-tag>
            <div v-if="s.row.engine==='edge'" style="font-size:10px;color:#909399">{{s.row.edge_voice}}</div></template></el-table-column>
          <el-table-column prop="persona" label="人设风格" width="110"/>
          <el-table-column label="调参" width="130"><template #default="s">
            <span v-if="s.row.engine==='edge'">{{s.row.edge_rate}} / {{s.row.edge_pitch}}</span>
            <span v-else>{{s.row.rate}} / {{s.row.pitch}} <span style="color:#909399">{{s.row.voice_hint}}</span></span></template></el-table-column>
          <el-table-column prop="sample_text" label="试听文本"/>
          <el-table-column label="启用" width="56"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'是':'否'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="170" fixed="right"><template #default="s">
            <el-button size="small" link type="primary" @click="tryPlay(s.row)">试听</el-button>
            <el-button size="small" link type="primary" @click="editSound(s.row)">编辑</el-button>
            <el-button size="small" link type="danger" @click="delSound(s.row.key)">删</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 网站通知/跑马灯 -->
      <el-tab-pane name="broadcast">
        <template #label><span class="tl"><el-icon><Promotion/></el-icon> 网站通知(跑马灯)</span></template>
        <el-form label-width="90" style="max-width:520px">
          <el-form-item label="标题"><el-input v-model="bc.title" size="small"/></el-form-item>
          <el-form-item label="内容"><el-input v-model="bc.content" type="textarea" :rows="2"/></el-form-item>
          <el-form-item label="颜色"><el-color-picker v-model="bc.color"/></el-form-item>
          <el-form-item label="闪烁"><el-switch v-model="bc.blink"/></el-form-item>
          <el-form-item label="声音人设"><el-select v-model="bc.sound" style="width:220px">
            <el-option value="none" label="无(静音)"/>
            <el-option v-for="s in sounds" :key="s.key" :value="s.key" :label="s.name+(s.persona?(' · '+s.persona):'')"/></el-select>
            <el-button size="small" style="margin-left:8px" @click="tryPlayKey(bc.sound)">试听</el-button></el-form-item>
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

    <el-dialog :close-on-click-modal="false" v-model="tdlg" :title="tcur.id?'编辑模板':'新增模板'" width="520">
      <el-form label-width="92">
        <el-form-item label="名称"><el-input v-model="tcur.template_name"/></el-form-item>
        <el-form-item label="分类"><el-select v-model="tcur.category"><el-option value="system" label="系统"/><el-option value="trade" label="交易"/><el-option value="risk" label="风险"/><el-option value="marketing" label="营销"/></el-select></el-form-item>
        <el-form-item label="标题模板"><el-input v-model="tcur.title_template" placeholder="支持 {username} {detail} 等变量"/></el-form-item>
        <el-form-item label="内容模板"><el-input v-model="tcur.content_template" type="textarea" :rows="2"/></el-form-item>
        <el-form-item label="渠道">
          <el-checkbox v-model="tcur.enable_feishu">飞书</el-checkbox>
          <el-checkbox v-model="tcur.enable_email">邮件</el-checkbox>
          <el-checkbox v-model="tcur.enable_marquee">跑马灯</el-checkbox>
          <el-checkbox v-model="tcur.enable_sound">声音</el-checkbox>
        </el-form-item>
        <el-form-item label="声音人设" v-if="tcur.enable_sound">
          <el-select v-model="tcur.sound_key" style="width:220px">
            <el-option value="none" label="无(静音)"/>
            <el-option v-for="s in sounds" :key="s.key" :value="s.key" :label="s.name+(s.persona?(' · '+s.persona):'')"/>
          </el-select>
          <el-button size="small" style="margin-left:8px" @click="tryPlayKey(tcur.sound_key)">试听</el-button>
          <span style="color:#909399;font-size:11px;margin-left:8px">人设在「声音人设」页管理(增删改)</span>
        </el-form-item>
        <el-form-item label="跑马灯颜色"><el-color-picker v-model="tcur.marquee_color"/> <el-checkbox v-model="tcur.marquee_blink" style="margin-left:10px">闪烁</el-checkbox></el-form-item>
        <el-form-item label="冷却(秒)"><el-input-number v-model="tcur.cooldown_seconds" :min="0"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="tcur.is_enabled"/></el-form-item>
      </el-form>
      <template #footer><el-button @click="tdlg=false">取消</el-button><el-button type="primary" @click="saveTpl">保存</el-button></template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="sdlg" :title="sedit?'编辑声音人设':'新增声音人设'" width="520">
      <el-form label-width="100">
        <el-form-item label="标识 key"><el-input v-model="scur.key" :disabled="sedit" placeholder="唯一,如 sweet/mature/boss"/></el-form-item>
        <el-form-item label="名称"><el-input v-model="scur.name" placeholder="如 甜妹 / 御姐"/></el-form-item>
        <el-form-item label="人设风格"><el-input v-model="scur.persona" placeholder="如 甜美元气 / 成熟沉稳(仅备注)"/></el-form-item>
        <el-form-item label="合成引擎">
          <el-radio-group v-model="scur.engine" @change="onEngineChange">
            <el-radio value="edge">神经语音(edge-tts·真中文)</el-radio>
            <el-radio value="browser">浏览器TTS(离线兜底)</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="scur.engine==='edge'">
          <el-form-item label="神经语音">
            <el-select v-model="scur.edge_voice" filterable style="width:300px" placeholder="选微软神经语音" @focus="loadEdgeVoices">
              <el-option v-for="v in edgeVoices" :key="v.short_name" :value="v.short_name"
                         :label="v.short_name+' · '+(v.gender==='Female'?'女':'男')"/>
            </el-select>
            <el-button size="small" style="margin-left:6px" @click="loadEdgeVoices">刷新语音列表</el-button>
          </el-form-item>
          <el-form-item label="语速 rate"><el-input v-model="scur.edge_rate" style="width:140px" placeholder="+8% / -6%"/>
            <span style="color:#909399;font-size:11px;margin-left:8px">±百分比,如 +10% 加快</span></el-form-item>
          <el-form-item label="音调 pitch"><el-input v-model="scur.edge_pitch" style="width:140px" placeholder="+12Hz / -10Hz"/>
            <span style="color:#909399;font-size:11px;margin-left:8px">±Hz,如 +20Hz 升调</span></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="语言"><el-select v-model="scur.lang" style="width:160px">
            <el-option value="zh-CN" label="中文(zh-CN)"/><el-option value="zh-TW" label="中文繁(zh-TW)"/><el-option value="en-US" label="英语(en-US)"/></el-select></el-form-item>
          <el-form-item label="语速 rate"><el-slider v-model="scur.rate" :min="0.5" :max="2" :step="0.02" show-input style="max-width:340px"/></el-form-item>
          <el-form-item label="音调 pitch"><el-slider v-model="scur.pitch" :min="0" :max="2" :step="0.02" show-input style="max-width:340px"/></el-form-item>
          <el-form-item label="挑声关键词"><el-input v-model="scur.voice_hint" placeholder="正则,浏览器据此挑声,如 Xiaoxiao|female|女"/></el-form-item>
        </template>

        <el-form-item label="试听文本"><el-input v-model="scur.sample_text" type="textarea" :rows="2" placeholder="试听时朗读的示例文本"/></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="scur.sort" :min="0"/></el-form-item>
        <el-form-item label="启用"><el-switch v-model="scur.enabled"/></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tryPlay(scur)">试听当前</el-button>
        <el-button @click="sdlg=false">取消</el-button><el-button type="primary" @click="saveSound">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
const sounds=ref([]), sdlg=ref(false), scur=ref({}), sedit=ref(false)
const bc=ref({title:'',content:'',color:'#2E8BD6',blink:false,sound:'none'})
const logs=ref([]), logCh=ref('')
async function loadFeishuStatus(){ try{ fs.value=await api.notifyFeishuStatus() }catch(e){ ElMessage.error('状态加载失败(需超管)') } }
async function testFeishu(){ if(!fsRecipient.value)return ElMessage.warning('填测试接收人')
  try{ const r=await api.notifyFeishuTest(fsRecipient.value); r.status==='sent'?ElMessage.success('已发送'):ElMessage.error(r.detail||'失败') }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadEmail(){ try{ const d=await api.notifyEmailGet(); email.value={...email.value,...d,smtp_password:''} }catch(e){} }
async function saveEmail(){ try{ await api.notifyEmailSave(email.value); ElMessage.success('已保存') }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function testEmail(){ try{ const r=await api.notifyEmailTest(); r.status==='sent'?ElMessage.success('已发送'):ElMessage.error(r.detail||'失败') }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadTemplates(){ try{ templates.value=(await api.notifyTemplates()).templates||[] }catch(e){ ElMessage.error('加载失败') } }
function newTpl(){ tcur.value={id:0,template_name:'',category:'system',title_template:'',content_template:'',enable_feishu:true,enable_email:false,enable_marquee:true,enable_sound:false,priority:1,cooldown_seconds:0,marquee_color:'#2E8BD6',marquee_blink:false,sound_key:'none',is_enabled:true}; tdlg.value=true }
function editTpl(r){ tcur.value={...r, enable_sound:(r.sound_key&&r.sound_key!=='none')}; tdlg.value=true }
async function saveTpl(){
  // enable_sound 为 UI 派生: 关→sound_key='none'; 开但未选人设→默认 sweet
  const payload={...tcur.value}
  if(!payload.enable_sound) payload.sound_key='none'
  else if(!payload.sound_key||payload.sound_key==='none') payload.sound_key='sweet'
  delete payload.enable_sound
  try{ await api.notifyTemplateSave(payload); ElMessage.success('已保存'); tdlg.value=false; loadTemplates() }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delTpl(id){ try{ await api.notifyTemplateDel(id); ElMessage.success('已删除'); loadTemplates() }catch(e){ ElMessage.error('失败') } }
// ── 声音人设管理 ──
const edgeVoices=ref([])
let __previewAudio=null
function soundName(k){ const s=sounds.value.find(x=>x.key===k); return s?s.name:k }
async function loadSounds(){ try{ sounds.value=(await api.notifySounds()).sounds||[] }catch(e){ ElMessage.error('声音加载失败') } }
async function loadEdgeVoices(){ if(edgeVoices.value.length)return; try{ edgeVoices.value=(await api.notifyEdgeVoices('zh-CN')).voices||[] }catch(e){ ElMessage.warning('语音列表加载失败(需 edge-tts)') } }
function onEngineChange(v){ if(v==='edge'){ loadEdgeVoices(); if(!scur.value.edge_voice)scur.value.edge_voice='zh-CN-XiaoxiaoNeural'; if(!scur.value.edge_rate)scur.value.edge_rate='+0%'; if(!scur.value.edge_pitch)scur.value.edge_pitch='+0Hz' } }
function newSound(){ scur.value={key:'',name:'',persona:'',engine:'edge',lang:'zh-CN',rate:1.0,pitch:1.0,voice_hint:'',edge_voice:'zh-CN-XiaoxiaoNeural',edge_rate:'+0%',edge_pitch:'+0Hz',sample_text:'这是一条语音播报测试。',enabled:true,sort:0}; sedit.value=false; loadEdgeVoices(); sdlg.value=true }
function editSound(r){ scur.value={engine:'browser',edge_voice:'',edge_rate:'+0%',edge_pitch:'+0Hz',...r}; sedit.value=true; if(scur.value.engine==='edge')loadEdgeVoices(); sdlg.value=true }
async function saveSound(){
  if(!scur.value.key||scur.value.key==='none')return ElMessage.warning('标识 key 不能为空或 none')
  if(!scur.value.name)return ElMessage.warning('填名称')
  if(scur.value.engine==='edge'&&!scur.value.edge_voice)return ElMessage.warning('神经语音引擎需选一个语音')
  try{ await api.notifySoundSave(scur.value); ElMessage.success('已保存'); sdlg.value=false; loadSounds() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') }
}
async function delSound(key){
  try{ await ElMessageBox.confirm('删除声音人设「'+soundName(key)+'」?引用它的模板将回落静音。','确认删除',{type:'warning'}) }catch(e){ return }
  try{ await api.notifySoundDel(key); ElMessage.success('已删除'); loadSounds() }catch(e){ ElMessage.error('删除失败') }
}
// 浏览器 TTS 合成(engine=browser 或 edge 合成失败时兜底)
function ttsSpeakBrowser(cfg, text){
  try{
    if(!('speechSynthesis' in window))return ElMessage.warning('当前浏览器不支持 TTS')
    const u=new SpeechSynthesisUtterance(String(text||cfg.sample_text||'语音播报测试').slice(0,120))
    u.lang=cfg.lang||'zh-CN'; u.rate=Number(cfg.rate)||1; u.pitch=Number(cfg.pitch)||1
    const vs=window.speechSynthesis.getVoices()||[]
    if(cfg.voice_hint){ try{ const re=new RegExp(cfg.voice_hint,'i'); const v=vs.find(x=>re.test(x.name)||re.test(x.lang)); if(v)u.voice=v }catch(e){} }
    if(!u.voice){ const zh=vs.find(x=>/zh|Chinese/i.test(x.lang)); if(zh)u.voice=zh }
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(u)
  }catch(e){ ElMessage.error('试听失败') }
}
// 试听: edge 引擎→拉服务端合成的 MP3 播放(编辑中未保存则用当前文本参数); browser→本地合成
function tryPlay(row){
  const text=row.sample_text||'语音播报测试'
  if(row.engine==='edge'){
    if(!row.key){ ElMessage.info('edge 试听需先保存人设(取 key)'); return }
    try{
      if(__previewAudio){ __previewAudio.pause(); __previewAudio=null }
      __previewAudio=new Audio(api.notifyTtsUrl(row.key, text))
      __previewAudio.play().catch(()=>{ ElMessage.warning('MP3 播放失败, 回落浏览器 TTS'); ttsSpeakBrowser(row,text) })
    }catch(e){ ttsSpeakBrowser(row,text) }
  }else{ ttsSpeakBrowser(row, text) }
}
function tryPlayKey(key){ if(!key||key==='none')return ElMessage.info('该模板静音'); const s=sounds.value.find(x=>x.key===key); if(s)tryPlay(s); else ElMessage.warning('未找到人设') }
async function doBroadcast(){ if(!bc.value.title)return ElMessage.warning('填标题')
  try{ await api.notifyBroadcast(bc.value); ElMessage.success('已广播'); bc.value.content='' }catch(e){ ElMessage.error(e?.response?.data?.detail||'失败') } }
async function loadLogs(){ try{ logs.value=(await api.notifyLogs(logCh.value)).logs||[] }catch(e){} }
onMounted(()=>{ loadFeishuStatus(); loadFsCfgStatus(); loadEmail(); loadTemplates(); loadLogs(); loadSounds() })
</script>
<style scoped>
.tl{display:inline-flex;align-items:center;gap:5px}
.tl .el-icon{color:var(--el-color-primary)}
</style>
