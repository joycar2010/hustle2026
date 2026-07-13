<template>
  <div class="mixnotify">
    <el-tabs v-model="tab" class="ntabs">

      <!-- ① 网站维护/全停 -->
      <el-tab-pane label="网站维护/全停" name="maint">
        <div class="card" style="max-width:640px">
          <div class="banner" :class="mt.enabled?'warn':'ok'">
            {{ mt.enabled ? '⚠ 维护中（用户端已置顶维护公告）' : '✓ 系统正常运行中' }}
          </div>
          <el-form label-width="130">
            <el-form-item label="维护总开关">
              <el-switch v-model="mt.enabled" active-text="维护中" inactive-text="正常运行" inline-prompt />
            </el-form-item>
            <el-form-item label="停自动策略">
              <el-switch v-model="mt.stop_strategy" :disabled="!mt.enabled" />
              <span class="tip">开启维护时执行 gateway Kill Switch（全组合置 shadow + 清白名单，停新开；存量仓位需手动路由 off 平仓）</span>
            </el-form-item>
            <el-form-item label="禁下单交易">
              <el-switch v-model="mt.block_trading" :disabled="!mt.enabled" />
              <span class="tip">拦截开仓/平仓/补腿/规则写（返回维护中提示 423）</span>
            </el-form-item>
            <el-form-item label="禁登录(全站)">
              <el-switch v-model="mt.block_login" :disabled="!mt.enabled" />
              <span class="tip">非操作员挡在门外，用户端显示维护公告（操作后台不受影响）</span>
            </el-form-item>
            <el-form-item label="公告标题"><el-input v-model="mt.title" placeholder="系统维护中" /></el-form-item>
            <el-form-item label="公告内容"><el-input v-model="mt.content" type="textarea" :rows="2" placeholder="例: 系统升级维护, 预计30分钟" /></el-form-item>
            <el-form-item label="预计恢复时间">
              <el-date-picker v-model="mt.until_at" type="datetime" placeholder="可选，到点提示自动解除" style="width:260px" />
            </el-form-item>
            <el-form-item>
              <el-button type="warning" :loading="saving" @click="saveMaint">保存维护设置</el-button>
              <el-button type="danger" @click="allStop">一键维护全停</el-button>
            </el-form-item>
          </el-form>
          <div class="note">维护态存 Redis（重启不丢）；开启即向用户端跑马灯置顶维护公告 + Kill Switch。「一键维护全停」=三档全开。</div>
        </div>
      </el-tab-pane>

      <!-- ② 飞书通知（自建应用 App ID/Secret + 群机器人 Webhook 双通道） -->
      <el-tab-pane label="飞书通知" name="feishu">
        <div class="cards2">
          <div class="card">
            <div class="hd"><b>飞书自建应用凭证</b><span class="sub">用于手机号查 open_id、卡片推送（DexCexMix 自建应用）</span></div>
            <el-alert v-if="!ch.feishuAppConfigured" title="未连通: 飞书 App ID 未配置" type="warning" :closable="false" show-icon style="margin-bottom:12px" />
            <el-alert v-else :title="`已连通：${ch.feishuAppId}`" type="success" :closable="false" show-icon style="margin-bottom:12px" />
            <el-form label-width="110">
              <el-form-item label="App ID"><el-input v-model="feishuApp.app_id" :placeholder="ch.feishuAppId || 'cli_ 开头'" /></el-form-item>
              <el-form-item label="App Secret"><el-input v-model="feishuApp.secret" type="password" show-password placeholder="留空=不改" autocomplete="new-password" /></el-form-item>
              <el-form-item label="接收 Open ID"><el-input v-model="feishuApp.open_id" :placeholder="ch.feishuOpenId || 'ou_ 开头'" /></el-form-item>
              <el-form-item>
                <el-button type="warning" @click="saveFeishuApp">保存凭证</el-button>
                <el-input v-model="testPhone" size="small" style="width:180px;margin-left:8px" placeholder="手机号(含国家码)测试">
                  <template #append><el-button @click="testLookup">获取ID</el-button></template>
                </el-input>
              </el-form-item>
            </el-form>
            <div class="note">获取路径：飞书开放平台 → 应用 → 凭证与基础信息 → App ID / App Secret。存服务端 feishu_conf（600 权限同源）。</div>
          </div>
          <div class="card">
            <div class="hd"><b>群机器人 Webhook</b><span class="sub">备用推送通道</span></div>
            <el-alert v-if="!ch.feishuConfigured" title="未配置 Webhook（选填）" type="info" :closable="false" show-icon style="margin-bottom:12px" />
            <el-form label-width="90">
              <el-form-item label="Webhook"><el-input v-model="ch.feishuWebhook" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/…" /></el-form-item>
              <el-form-item><el-button type="warning" @click="saveChannels">保存 Webhook</el-button></el-form-item>
            </el-form>
            <div class="note">fatal 级绕常规节流（300s/1 硬地板）。</div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ③ 邮件(SMTP) -->
      <el-tab-pane label="邮件(SMTP)" name="email">
        <div class="card" style="max-width:600px">
          <el-alert title="邮件通道配置留位（未接 SMTP 前不真发送）" type="info" :closable="false" show-icon style="margin-bottom:12px" />
          <el-form label-width="120">
            <el-form-item label="SMTP 主机"><el-input v-model="ch.email.host" /></el-form-item>
            <el-form-item label="端口"><el-input v-model="ch.email.port" style="max-width:140px" /></el-form-item>
            <el-form-item label="发件账号"><el-input v-model="ch.email.user" /></el-form-item>
            <el-form-item label="发件人显示"><el-input v-model="ch.email.sender" /></el-form-item>
            <el-form-item><el-button type="warning" @click="saveChannels">保存配置</el-button></el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- ④ 通知模板 -->
      <el-tab-pane label="通知模板" name="templates">
        <div class="card">
          <div class="hd"><b>模板列表</b><span class="sub">正文支持 {var} 占位；模板供手动广播与自动事件套用</span>
            <el-button size="small" type="warning" @click="editTpl()">+ 新增模板</el-button>
            <el-button size="small" @click="loadTpls">刷新</el-button>
          </div>
          <el-table :data="templates" size="small">
            <el-table-column prop="tkey" label="模板键" width="150" />
            <el-table-column prop="category" label="分类" width="90" />
            <el-table-column prop="title" label="标题模板" min-width="130" />
            <el-table-column label="级别" width="72">
              <template #default="{row}"><el-tag :type="{info:'info',warn:'warning',fatal:'danger'}[row.level]" size="small" effect="plain">{{ row.level }}</el-tag></template>
            </el-table-column>
            <el-table-column label="渠道" width="180">
              <template #default="{row}">
                <el-tag v-for="c in row.channels" :key="c" size="small" effect="plain" style="margin:1px">{{ chLabel(c) }}</el-tag>
                <el-tag v-if="row.sound_key" size="small" type="warning" effect="plain">声音·{{ personaName(row.sound_key) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="60">
              <template #default="{row}"><span :class="row.enabled?'up':'dim'">{{ row.enabled?'是':'否' }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="150">
              <template #default="{row}">
                <el-button size="small" link type="warning" @click="editTpl(row)">编辑</el-button>
                <el-button size="small" link @click="useTpl(row)">去广播</el-button>
                <el-button size="small" link type="danger" @click="delTpl(row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ⑤ 声音人设（浏览器端 TTS） -->
      <el-tab-pane label="声音人设" name="personas">
        <div class="card">
          <div class="hd"><b>人设列表</b>
            <span class="sub">试听/播报走后端 edge-tts 真人声（按人设 嗓音/语速/音调,神经音合成）；后端不可用时自动回落浏览器 TTS</span>
            <el-button size="small" type="warning" @click="editPersona()">+ 新增人设</el-button>
          </div>
          <el-table :data="personas" size="small">
            <el-table-column prop="skey" label="标识" width="120" />
            <el-table-column prop="name" label="名称" width="90" />
            <el-table-column prop="voice" label="嗓音" min-width="120" />
            <el-table-column prop="style" label="人设风格" min-width="130" />
            <el-table-column label="调参" width="120">
              <template #default="{row}">{{ row.rate_pct>=0?'+':'' }}{{ row.rate_pct }}% / {{ row.pitch_pct>=0?'+':'' }}{{ row.pitch_pct }}Hz</template>
            </el-table-column>
            <el-table-column label="试听文本" min-width="200" show-overflow-tooltip>
              <template #default="{row}"><span @click="tryTTS(row)" style="cursor:pointer;color:#F0B90B">▶ {{ row.sample }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{row}">
                <el-button size="small" link @click="tryTTS(row)">试听</el-button>
                <el-button size="small" link type="warning" @click="editPersona(row)">编辑</el-button>
                <el-button size="small" link type="danger" @click="delPersona(row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ⑥ 网站通知(跑马灯) 手动广播 -->
      <el-tab-pane label="网站通知(跑马灯)" name="broadcast">
        <div class="card" style="max-width:640px">
          <el-form label-width="90">
            <el-form-item label="标题"><el-input v-model="bc.title" maxlength="120" /></el-form-item>
            <el-form-item label="内容"><el-input v-model="bc.text" type="textarea" :rows="3" maxlength="2000" /></el-form-item>
            <el-form-item label="级别">
              <el-radio-group v-model="bc.level" size="small">
                <el-radio-button value="info">info</el-radio-button>
                <el-radio-button value="warn">warn</el-radio-button>
                <el-radio-button value="fatal">fatal</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="渠道">
              <el-checkbox-group v-model="bc.channels">
                <el-checkbox value="marquee">跑马灯</el-checkbox>
                <el-checkbox value="feishu">飞书</el-checkbox>
                <el-checkbox value="email" disabled>邮件（未接线）</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="声音人设">
              <el-select v-model="bc.sound_key" size="small" clearable placeholder="无（静音）" style="width:200px">
                <el-option v-for="p in personas" :key="p.skey" :label="p.name" :value="p.skey" />
              </el-select>
              <el-button size="small" link @click="tryBroadcastTTS" style="margin-left:8px">试听</el-button>
            </el-form-item>
            <el-form-item>
              <el-button type="warning" :loading="sending" @click="send">立即广播到用户端跑马灯</el-button>
              <span v-if="lastResult" class="lastres">{{ lastResult }}</span>
            </el-form-item>
          </el-form>
          <div class="note">广播即时推送到 Redis + 落发送日志；用户端 WS marquee 频道到端展示。</div>
        </div>
      </el-tab-pane>

      <!-- ⑦ 发送日志 -->
      <el-tab-pane label="发送日志" name="logs">
        <div class="card">
          <div class="hd"><b>mix 主动发送记录</b><el-button size="small" @click="loadLogs">刷新</el-button></div>
          <el-table :data="logs" size="small">
            <el-table-column prop="ts" label="时间" width="130" />
            <el-table-column prop="channel" label="渠道" width="80" />
            <el-table-column prop="title" label="标题" min-width="140" />
            <el-table-column prop="body" label="内容" min-width="200" show-overflow-tooltip />
            <el-table-column label="结果" width="70"><template #default="{row}"><span :class="row.ok?'up':'down'">{{ row.ok?'成功':'失败' }}</span></template></el-table-column>
            <el-table-column prop="detail" label="详情" min-width="140" show-overflow-tooltip />
            <el-table-column prop="operator" label="操作者" width="100" />
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 模板编辑 -->
    <el-dialog v-model="tplDlg" :title="tf.id?'编辑模板':'新增模板'" width="540">
      <el-form label-width="80">
        <el-form-item label="模板键"><el-input v-model="tf.tkey" :disabled="!!tf.id" placeholder="如 singleleg_alert" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tf.category" style="width:160px">
            <el-option v-for="c in ['system','risk','trade','marketing']" :key="c" :value="c" :label="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="tf.title" /></el-form-item>
        <el-form-item label="正文"><el-input v-model="tf.body" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="级别">
          <el-radio-group v-model="tf.level" size="small">
            <el-radio-button value="info">info</el-radio-button><el-radio-button value="warn">warn</el-radio-button><el-radio-button value="fatal">fatal</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="渠道">
          <el-checkbox-group v-model="tf.channels">
            <el-checkbox value="marquee">跑马灯</el-checkbox><el-checkbox value="feishu">飞书</el-checkbox><el-checkbox value="email">邮件</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="声音人设">
          <el-select v-model="tf.sound_key" clearable placeholder="无" style="width:180px">
            <el-option v-for="p in personas" :key="p.skey" :label="p.name" :value="p.skey" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="tplDlg=false">取消</el-button><el-button type="warning" @click="saveTpl">保存</el-button></template>
    </el-dialog>

    <!-- 人设编辑 -->
    <el-dialog v-model="personaDlg" :title="pf.id?'编辑人设':'新增人设'" width="520">
      <el-form label-width="90">
        <el-form-item label="标识"><el-input v-model="pf.skey" :disabled="!!pf.id" placeholder="如 sweet" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="pf.name" placeholder="甜妹 / 御姐" /></el-form-item>
        <el-form-item label="嗓音">
          <el-select v-model="pf.voice" style="width:260px">
            <el-option v-for="v in voices" :key="v" :value="v" :label="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="人设风格"><el-input v-model="pf.style" placeholder="甜美/元气 · 系统营销" /></el-form-item>
        <el-form-item label="语速">
          <el-slider v-model="pf.rate_pct" :min="-50" :max="50" style="width:220px" /><span class="tip">{{ pf.rate_pct }}%</span>
        </el-form-item>
        <el-form-item label="音调">
          <el-slider v-model="pf.pitch_pct" :min="-50" :max="50" style="width:220px" /><span class="tip">{{ pf.pitch_pct }}Hz</span>
        </el-form-item>
        <el-form-item label="试听文本"><el-input v-model="pf.sample" type="textarea" :rows="2" /></el-form-item>
        <el-form-item><el-button size="small" @click="tryTTS(pf)">▶ 试听当前设置</el-button></el-form-item>
      </el-form>
      <template #footer><el-button @click="personaDlg=false">取消</el-button><el-button type="warning" @click="savePersona">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const tab = ref('maint')
const saving = ref(false), sending = ref(false), lastResult = ref('')
const mt = reactive({ enabled: false, stop_strategy: true, block_trading: true, block_login: false, title: '系统维护中', content: '', until_at: null })
const ch = ref({ feishuWebhook: '', feishuConfigured: false, feishuAppId: '', feishuAppConfigured: false, feishuOpenId: '', email: { host: '', port: '', user: '', sender: '' } })
const feishuApp = ref({ app_id: '', secret: '', open_id: '' })
const testPhone = ref('')
async function saveFeishuApp() {
  try { await mixApi.channelsPut({ feishuConf: { ...feishuApp.value } }); ElMessage.success('飞书应用凭证已保存'); feishuApp.value.secret = ''; loadChannels() }
  catch (e) { ElMessage.error(e?.detail || '保存失败') }
}
async function testLookup() {
  if (!testPhone.value) return ElMessage.warning('填手机号(含国家码)')
  try { const r = await mixApi.feishuLookup(testPhone.value); ElMessage.success('查到 open_id: ' + (r.open_id || '').slice(0, 14) + '…') }
  catch (e) { ElMessage.error(e?.detail || '查询失败(手机号需在飞书通讯录)') }
}
const templates = ref([]), personas = ref([]), logs = ref([])
const bc = reactive({ title: '', text: '', level: 'info', channels: ['marquee'], sound_key: '' })
const tplDlg = ref(false)
const tf = reactive({ id: null, tkey: '', category: 'system', title: '', body: '', level: 'info', channels: ['marquee'], sound_key: '' })
const personaDlg = ref(false)
const pf = reactive({ id: null, skey: '', name: '', voice: 'zh-CN-XiaoxiaoNeural', style: '', rate_pct: 0, pitch_pct: 0, sample: '' })
const voices = ['zh-CN-XiaoxiaoNeural', 'zh-CN-XiaoyiNeural', 'zh-CN-YunxiNeural', 'zh-CN-YunyangNeural', 'zh-CN-XiaohanNeural']
const chLabel = c => ({ marquee: '跑马灯', feishu: '飞书', email: '邮件' }[c] || c)
const personaName = k => personas.value.find(p => p.skey === k)?.name || k

async function loadMaint() { try { Object.assign(mt, await mixApi.maintenanceGet()) } catch (e) { /* 降级 */ } }
async function saveMaint() {
  saving.value = true
  try { const r = await mixApi.maintenancePut({ ...mt }); ElMessage.success('维护设置已保存' + (r.kill_switch ? '（Kill Switch 已触发）' : '')) }
  catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') } finally { saving.value = false }
}
async function allStop() {
  await ElMessageBox.confirm('一键维护全停=开启维护 + Kill Switch 停全部自动策略 + 禁下单。确认？', '危险操作', { type: 'warning' })
  const r = await mixApi.maintenanceAllStop({ block_login: mt.block_login, title: mt.title, content: mt.content })
  Object.assign(mt, r.state || {}); mt.enabled = true
  ElMessage.warning('已一键全停：' + (r.kill_switch?.message || 'Kill Switch 已执行'))
}
async function loadChannels() { try { ch.value = { ...ch.value, ...(await mixApi.channelsGet()) } } catch (e) { /* */ } }
async function saveChannels() {
  try { await mixApi.channelsPut({ feishuWebhook: ch.value.feishuWebhook, email: ch.value.email }); ElMessage.success('已保存'); loadChannels() }
  catch (e) { ElMessage.error(e?.detail || '保存失败') }
}
async function loadTpls() { try { templates.value = await mixApi.templates() } catch (e) { templates.value = [] } }
function editTpl(row) {
  Object.assign(tf, row ? { id: row.id, tkey: row.tkey, category: row.category || 'system', title: row.title, body: row.body, level: row.level, channels: [...(row.channels || [])], sound_key: row.sound_key || '' }
    : { id: null, tkey: '', category: 'system', title: '', body: '', level: 'info', channels: ['marquee'], sound_key: '' })
  tplDlg.value = true
}
async function saveTpl() {
  if (!tf.tkey) return ElMessage.warning('模板键必填')
  try { await mixApi.templatePut({ ...tf }); ElMessage.success('已保存'); tplDlg.value = false; loadTpls() }
  catch (e) { ElMessage.error(e?.detail || '保存失败') }
}
async function delTpl(row) { await ElMessageBox.confirm(`删除模板 ${row.tkey}？`, '删除', { type: 'warning' }); await mixApi.templateDel(row.id); loadTpls() }
function useTpl(row) { Object.assign(bc, { title: row.title, text: row.body, level: row.level, channels: (row.channels || ['marquee']).filter(c => c !== 'email'), sound_key: row.sound_key || '' }); tab.value = 'broadcast' }

async function loadPersonas() { try { personas.value = await mixApi.personas() } catch (e) { personas.value = [] } }
function editPersona(row) {
  Object.assign(pf, row ? { ...row } : { id: null, skey: '', name: '', voice: 'zh-CN-XiaoxiaoNeural', style: '', rate_pct: 0, pitch_pct: 0, sample: '' })
  personaDlg.value = true
}
async function savePersona() {
  if (!pf.skey) return ElMessage.warning('标识必填')
  try { await mixApi.personaPut({ ...pf }); ElMessage.success('已保存'); personaDlg.value = false; loadPersonas() }
  catch (e) { ElMessage.error(e?.detail || '保存失败') }
}
async function delPersona(row) { await ElMessageBox.confirm(`删除人设 ${row.name}？`, '删除', { type: 'warning' }); await mixApi.personaDel(row.id); loadPersonas() }
// 真人声优先(后端 edge-tts 神经音,甜妹/御姐真嗓);失败自动回落浏览器 speechSynthesis
let ttsAudio = null
async function speak(text, rate_pct, pitch_pct, opts = {}) {
  const t = text || '测试语音'
  try {
    const blob = await mixApi.ttsBlob(t, opts.persona || '', {
      ...(opts.voice ? { voice: opts.voice } : {}),
      ...(rate_pct != null ? { rate_pct } : {}),
      ...(pitch_pct != null ? { pitch_pct } : {}),
    })
    const url = URL.createObjectURL(blob)
    if (ttsAudio) { try { ttsAudio.pause() } catch (e) { /* noop */ } }
    ttsAudio = new Audio(url)
    ttsAudio.onended = () => URL.revokeObjectURL(url)
    await ttsAudio.play()
    return
  } catch (e) { /* 后端 TTS 不可用,回落浏览器 */ }
  if (!window.speechSynthesis) return ElMessage.warning('浏览器不支持语音合成')
  const u = new SpeechSynthesisUtterance(t)
  u.lang = 'zh-CN'; u.rate = 1 + (rate_pct || 0) / 100; u.pitch = 1 + (pitch_pct || 0) / 100
  window.speechSynthesis.cancel(); window.speechSynthesis.speak(u)
}
function tryTTS(p) { speak(p.sample || '亲，这是一条测试播报', p.rate_pct, p.pitch_pct, { voice: p.voice, persona: p.skey }) }
function tryBroadcastTTS() { const p = personas.value.find(x => x.skey === bc.sound_key); speak(bc.text || bc.title || '测试', p?.rate_pct, p?.pitch_pct, { persona: bc.sound_key }) }

async function loadLogs() { try { logs.value = await mixApi.notifyLogs() } catch (e) { logs.value = [] } }
async function send() {
  if (!bc.text) return ElMessage.warning('内容必填')
  sending.value = true
  try {
    const r = await mixApi.notifyBroadcast({ ...bc })
    lastResult.value = Object.entries(r.results || {}).map(([k, v]) => `${k}:${v}`).join('  ')
    if (bc.sound_key) tryBroadcastTTS()
    ElMessage.success('已广播'); loadLogs()
  } catch (e) { ElMessage.error(e?.detail || '发送失败') } finally { sending.value = false }
}
onMounted(() => { loadMaint(); loadChannels(); loadTpls(); loadPersonas(); loadLogs() })
</script>

<style scoped lang="scss">
.mixnotify { display: flex; flex-direction: column; gap: 12px; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 14px 16px; background: var(--mix-card, #181B21);
  .hd { display: flex; gap: 10px; align-items: baseline; margin-bottom: 12px;
    b { font-size: 13px; } .sub { flex: 1; color: var(--el-text-color-secondary); font-size: 11px; } } }
.banner { padding: 8px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; margin-bottom: 14px;
  &.ok { background: rgba(14,203,129,.12); color: #0ECB81; } &.warn { background: rgba(240,185,11,.14); color: #F0B90B; } }
.tip { margin-left: 10px; font-size: 11px; color: var(--el-text-color-placeholder); }
.note { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 10px; }
.lastres { margin-left: 10px; font-size: 11px; color: var(--el-text-color-secondary); }
.up { color: #0ECB81; font-weight: 700; } .down { color: #F6465D; font-weight: 700; } .dim { color: var(--el-text-color-placeholder); }
.ntabs :deep(.el-tabs__item) { color: var(--el-text-color-secondary); font-weight: 600; }
.ntabs :deep(.el-tabs__item.is-active) { color: #F0B90B; }
.ntabs :deep(.el-tabs__active-bar) { background: #F0B90B; }
</style>
