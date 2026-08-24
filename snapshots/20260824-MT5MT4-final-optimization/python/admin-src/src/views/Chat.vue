<template>
  <div>
    <el-tabs v-model="tab" type="border-card">
      <!-- 数据概览 -->
      <el-tab-pane name="overview">
        <template #label><span class="tl"><el-icon><DataLine/></el-icon> 数据概览</span></template>
        <div style="margin-bottom:12px">
          <el-select v-model="statSite" size="small" style="width:150px" @change="loadStats">
            <el-option value="" label="全部站点"/><el-option value="qh" label="QH 控制台"/>
            <el-option value="qhwww" label="官网介绍站"/><el-option value="qhadmin" label="管理后台"/></el-select>
          <el-button size="small" @click="loadStats" style="margin-left:8px">刷新</el-button>
        </div>
        <el-row :gutter="12" v-if="stats">
          <el-col :span="6"><el-card class="stat-card"><div class="l">总对话数</div><div class="v">{{stats.total_conversations}}</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="l">总消息数</div><div class="v">{{stats.total_messages}}</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="l">今日消息</div><div class="v">{{stats.today_messages}}</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="l">Token 消耗</div><div class="v">{{(stats.total_tokens||0).toLocaleString()}}</div></el-card></el-col>
        </el-row>
      </el-tab-pane>

      <!-- 对话管理 -->
      <el-tab-pane name="conversations">
        <template #label><span class="tl"><el-icon><ChatLineSquare/></el-icon> 对话管理</span></template>
        <div style="margin-bottom:12px">
          <el-select v-model="convSite" size="small" style="width:150px" @change="loadConvs">
            <el-option value="" label="全部站点"/><el-option value="qh" label="QH 控制台"/>
            <el-option value="qhwww" label="官网介绍站"/><el-option value="qhadmin" label="管理后台"/></el-select>
          <el-button size="small" @click="loadConvs" style="margin-left:8px">刷新</el-button>
        </div>
        <el-row :gutter="12">
          <el-col :span="10">
            <el-table :data="convs" size="small" border max-height="460" @row-click="openConv" highlight-current-row>
              <el-table-column label="站点" width="80"><template #default="s"><el-tag size="small">{{siteLabel(s.row.site)}}</el-tag></template></el-table-column>
              <el-table-column prop="title" label="标题" show-overflow-tooltip/>
              <el-table-column prop="message_count" label="消息" width="60"/>
              <el-table-column prop="token_used" label="Token" width="70"/>
            </el-table>
          </el-col>
          <el-col :span="14">
            <el-card shadow="never" style="min-height:460px">
              <template #header><span style="font-size:13px">{{curConv?('会话 #'+curConv.id+' · '+siteLabel(curConv.site)):'点击左侧会话查看消息'}}</span></template>
              <div v-if="!convMsgs.length" style="color:#909399;font-size:13px;padding:12px">暂无消息</div>
              <div v-else style="max-height:400px;overflow-y:auto">
                <div v-for="(m,i) in convMsgs" :key="i" :style="{textAlign:m.role==='user'?'right':'left',margin:'6px 0'}">
                  <div :class="'bub '+(m.role==='user'?'u':'a')">{{m.content}}</div>
                  <div style="font-size:10px;color:#c0c4cc">{{(m.created_at||'').replace('T',' ').slice(5,19)}}<span v-if="m.tokens"> · {{m.tokens}}tok</span></div>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- 知识库(关键词 KB + 渠道凭证, QH 保留) -->
      <el-tab-pane name="knowledge">
        <template #label><span class="tl"><el-icon><Collection/></el-icon> 知识库</span></template>
        <div style="margin-bottom:10px">
          <el-select v-model="site" size="small" style="width:150px;margin-right:6px" @change="load">
            <el-option value="qh" label="QH 控制台"/><el-option value="qhwww" label="官网介绍站"/>
            <el-option value="app" label="轻应用站"/><el-option value="site" label="落地页"/></el-select>
          <el-button size="small" type="primary" @click="save">保存知识库</el-button></div>
        <el-form label-width="90">
          <el-form-item label="启用(KB)"><el-switch v-model="cfg.enabled"/></el-form-item>
          <el-form-item label="欢迎语"><el-input v-model="cfg.greeting" type="textarea" :rows="2"/></el-form-item>
        </el-form>
        <el-divider>问答知识库(关键词命中即答, LLM 未启用时的回退)</el-divider>
        <el-table :data="cfg.kb" size="small" border>
          <el-table-column label="关键词(q)" width="220"><template #default="s"><el-input v-model="s.row.q" size="small"/></template></el-table-column>
          <el-table-column label="回答(a)"><template #default="s"><el-input v-model="s.row.a" size="small" type="textarea" :rows="1"/></template></el-table-column>
          <el-table-column label="操作" width="70"><template #default="s"><el-button size="small" type="danger" @click="cfg.kb.splice(s.$index,1)">删</el-button></template></el-table-column>
        </el-table>
        <el-button size="small" style="margin-top:8px" @click="cfg.kb.push({q:'',a:''})">+ 增加问答</el-button>
      </el-tab-pane>

      <!-- 服务配置(LLM + 渠道接入, 复刻 coinadmin) -->
      <el-tab-pane name="config">
        <template #label><span class="tl"><el-icon><Setting/></el-icon> 服务配置</span></template>
        <div style="margin-bottom:12px">
          <el-radio-group v-model="aiSite" size="small" @change="loadAi">
            <el-radio-button value="qh">QH 控制台</el-radio-button>
            <el-radio-button value="qhwww">官网介绍站</el-radio-button>
            <el-radio-button value="qhadmin">管理后台</el-radio-button>
          </el-radio-group>
        </div>
        <el-card shadow="never" v-if="ai">
          <template #header><span style="font-size:13px">AI 服务配置 — {{siteLabel(aiSite)}}</span></template>
          <el-form label-width="120">
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="Provider">
                <el-select v-model="ai.provider" style="width:100%"><el-option value="claude" label="Claude (Anthropic)"/><el-option value="openai" label="OpenAI"/></el-select></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="中转地址">
                <el-input v-model="ai.base_url" placeholder="留空=直连官方 API" autocomplete="off"/></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="模型">
                <el-input v-model="ai.model_name" placeholder="如 claude-sonnet-4-6 / gpt-4o" autocomplete="off"/></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="API Key">
                <el-input v-model="ai.api_key" type="password" show-password placeholder="输入即改, 留空=保留原值" autocomplete="new-password"/></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="Temperature">
                <el-input-number v-model="ai.temperature" :step="0.1" :min="0" :max="2" style="width:100%"/></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="Max Tokens">
                <el-input-number v-model="ai.max_tokens" :step="100" :min="1" style="width:100%"/></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="限频(次/分)">
                <el-input-number v-model="ai.rate_limit_per_min" :min="1" style="width:100%"/></el-form-item></el-col>
            </el-row>
            <el-form-item label="System Prompt(知识库)">
              <el-input v-model="ai.system_prompt" type="textarea" :rows="8" placeholder="该站 AI 客服的系统提示词/知识库..."/>
            </el-form-item>
            <el-form-item label="启用 LLM 客服">
              <el-switch v-model="ai.is_enabled"/>
              <span style="color:#909399;font-size:12px;margin-left:10px">关闭时回退到「知识库」tab 的关键词问答</span>
            </el-form-item>
          </el-form>
          <div style="text-align:right"><el-button type="primary" :loading="aiSaving" @click="saveAi">保存配置</el-button></div>
        </el-card>

        <!-- 渠道接入状态 + 凭证(从知识库 tab 迁入) -->
        <el-card shadow="never" style="margin-top:12px">
          <template #header><span style="font-size:13px">渠道接入状态</span></template>
          <el-table :data="channels" size="small" border>
            <el-table-column prop="key" label="渠道键" width="110"/>
            <el-table-column prop="name" label="名称"/>
            <el-table-column label="类型" width="120"><template #default="s">
              <el-tag size="small" :type="{bidirectional:'success',site:'primary',inbound:'warning'}[s.row.kind]">
                {{ {bidirectional:'双向对话',site:'独立站',inbound:'留资引流'}[s.row.kind]||s.row.kind }}</el-tag></template></el-table-column>
            <el-table-column label="状态" width="80"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'未接'}}</el-tag></template></el-table-column>
          </el-table>
          <el-divider>渠道凭证配置 + 平台回调</el-divider>
          <el-table :data="cfgRows" size="small" border>
            <el-table-column prop="name" label="渠道" width="120"/>
            <el-table-column label="回调URL"><template #default="s"><code style="font-size:11px">{{s.row.callback}}</code>
              <el-button size="small" text type="primary" @click="copy(s.row.callback)">复制</el-button></template></el-table-column>
            <el-table-column label="凭证" width="240"><template #default="s">
              <el-tag v-for="(ok,f) in s.row.fields" :key="f" size="small" :type="ok?'success':'info'" style="margin-right:4px">{{fieldLabel(f)}}{{ok?'已配':'未配'}}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="80"><template #default="s"><el-button size="small" type="primary" @click="openCfg(s.row)">配置</el-button></template></el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog :close-on-click-modal="false" v-model="cfgDlg" :title="'配置 '+(cfgCur.name||'')+' 凭证'" width="440">
      <el-form label-width="90">
        <el-form-item label="回调URL"><el-input :model-value="cfgCur.callback" readonly/></el-form-item>
        <el-form-item v-for="f in cfgFields" :key="f" :label="fieldLabel(f)">
          <el-input v-model="cfgForm[f]" :placeholder="cfgCur.fields&&cfgCur.fields[f]?'已配置(留空=不改)':'未配置'" show-password autocomplete="new-password"/>
          <div style="color:#909399;font-size:11px;line-height:1.5;margin-top:2px">从哪取:{{ srcHint(f) }}</div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="cfgDlg=false">取消</el-button><el-button type="primary" @click="saveCfg">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { CHANNEL_FIELD } from '../dicts'
function fieldLabel(f){ return CHANNEL_FIELD[f] ? `${CHANNEL_FIELD[f]}(${f})` : f }
function siteLabel(s){ return {qh:'QH 控制台',qhwww:'官网介绍站',qhadmin:'管理后台',app:'轻应用站',site:'落地页'}[s]||s||'—' }
const tab=ref('overview')
// 数据概览
const stats=ref(null),statSite=ref('')
async function loadStats(){ try{ stats.value=await api.aiStats(statSite.value) }catch(e){ ElMessage.error('统计加载失败') } }
// 对话管理
const convs=ref([]),convSite=ref(''),curConv=ref(null),convMsgs=ref([])
async function loadConvs(){ try{ convs.value=(await api.aiConversations(convSite.value,80)).conversations||[] }catch(e){} }
async function openConv(row){ curConv.value=row; try{ convMsgs.value=(await api.aiConvMessages(row.id)).messages||[] }catch(e){ convMsgs.value=[] } }
// 服务配置(LLM)
const ai=ref(null),aiSite=ref('qh'),aiSaving=ref(false)
async function loadAi(){ try{ ai.value=await api.aiConfig(aiSite.value) }catch(e){ ElMessage.error('配置加载失败') } }
async function saveAi(){ aiSaving.value=true; try{ await api.aiConfigSave({site:aiSite.value,...ai.value}); ElMessage.success('AI 服务配置已保存') }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } finally{ aiSaving.value=false } }
// 知识库(关键词 KB + 渠道, 沿用原逻辑)
const site=ref('qh'),cfg=ref({greeting:'',kb:[],enabled:true}),channels=ref([])
const chStatus=ref({}),cfgDlg=ref(false),cfgCur=ref({}),cfgForm=ref({}),cfgKey=ref('')
const FIELD_MAP={feishu:['token','appid','secret'],wecom:['token','aeskey','secret'],mp_wx:['token','appid','secret'],miniapp:['token','appid','secret']}
const SRC_HINTS={
  feishu:{token:'飞书开放平台 → 应用 → 事件与回调 → 加密策略 → Verification Token',appid:'飞书开放平台 → 应用 → 凭证与基础信息 → App ID',secret:'飞书开放平台 → 应用 → 凭证与基础信息 → App Secret'},
  wecom:{token:'企业微信管理后台 → 应用管理 → 自建应用 → 接收消息 → API接收消息 → Token',aeskey:'同上「API接收消息」页 → EncodingAESKey(43位)',secret:'企业微信管理后台 → 应用管理 → 自建应用 → 该应用 → Secret'},
  mp_wx:{token:'微信公众平台 → 设置与开发 → 基本配置 → 服务器配置 → Token',appid:'微信公众平台 → 设置与开发 → 基本配置 → 开发者ID(AppID)',secret:'微信公众平台 → 设置与开发 → 基本配置 → 开发者密码(AppSecret)'},
  miniapp:{token:'微信公众平台(小程序) → 开发管理 → 开发设置 → 消息推送 → Token',appid:'微信公众平台(小程序) → 开发管理 → 开发设置 → AppID',secret:'微信公众平台(小程序) → 开发管理 → 开发设置 → AppSecret'},
}
function srcHint(f){ return (SRC_HINTS[cfgKey.value]&&SRC_HINTS[cfgKey.value][f]) || '平台开发者后台 应用凭证页' }
const cfgRows=computed(()=>Object.keys(chStatus.value).map(k=>({key:k,...chStatus.value[k]})))
const cfgFields=computed(()=>FIELD_MAP[cfgKey.value]||['token','appid','secret'])
async function load(){ try{ const d=await api.chatConfig(site.value); cfg.value={greeting:d.greeting||'',kb:d.kb||[],enabled:d.enabled!==false} }catch(e){ ElMessage.error('加载失败') } }
async function save(){ try{ await api.chatConfigSave({site:site.value,greeting:cfg.value.greeting,kb:cfg.value.kb,enabled:cfg.value.enabled}); ElMessage.success('已保存') }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function loadCh(){ try{ channels.value=(await api.channels()).channels||[] }catch(e){} }
async function loadStatus(){ try{ chStatus.value=await api.channelStatus() }catch(e){} }
function openCfg(row){ cfgKey.value=row.key; cfgCur.value=row; cfgForm.value={}; cfgDlg.value=true }
async function saveCfg(){ try{ await api.channelConfig({channel:cfgKey.value,...cfgForm.value}); ElMessage.success('已保存(热读生效)'); cfgDlg.value=false; loadStatus() }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
function copy(t){ navigator.clipboard&&navigator.clipboard.writeText(t); ElMessage.success('已复制') }
onMounted(()=>{ loadStats(); loadConvs(); loadAi(); load(); loadCh(); loadStatus() })
</script>
<style scoped>
.tl{display:inline-flex;align-items:center;gap:5px}
.bub{display:inline-block;max-width:88%;padding:8px 11px;border-radius:9px;font-size:13px;line-height:1.5;text-align:left;white-space:pre-wrap}
.bub.u{background:var(--el-color-primary);color:#fff}
.bub.a{background:var(--el-fill-color-light);color:var(--el-text-color-primary)}
</style>
