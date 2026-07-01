<template>
  <div>
    <el-card style="margin-bottom:12px">
      <template #header><span>AI 客服 · 知识库配置</span>
        <span style="float:right">
          <el-select v-model="site" size="small" style="width:110px;margin-right:6px" @change="load">
            <el-option value="qh" label="QH主站"/><el-option value="app" label="App站"/><el-option value="site" label="落地页"/></el-select>
          <el-button size="small" type="primary" @click="save">保存</el-button></span></template>
      <el-form label-width="90">
        <el-form-item label="启用"><el-switch v-model="cfg.enabled"/></el-form-item>
        <el-form-item label="欢迎语"><el-input v-model="cfg.greeting" type="textarea" :rows="2"/></el-form-item>
      </el-form>
      <el-divider>问答知识库(关键词命中即答)</el-divider>
      <el-table :data="cfg.kb" size="small" border>
        <el-table-column label="关键词(q)" width="220"><template #default="s"><el-input v-model="s.row.q" size="small"/></template></el-table-column>
        <el-table-column label="回答(a)"><template #default="s"><el-input v-model="s.row.a" size="small" type="textarea" :rows="1"/></template></el-table-column>
        <el-table-column label="操作" width="70"><template #default="s"><el-button size="small" type="danger" @click="cfg.kb.splice(s.$index,1)">删</el-button></template></el-table-column>
      </el-table>
      <el-button size="small" style="margin-top:8px" @click="cfg.kb.push({q:'',a:''})">+ 增加问答</el-button>
    </el-card>

    <el-card>
      <template #header><span>渠道接入状态</span></template>
      <el-table :data="channels" size="small" border>
        <el-table-column prop="key" label="渠道键" width="110"/>
        <el-table-column prop="name" label="名称"/>
        <el-table-column label="类型" width="120"><template #default="s">
          <el-tag size="small" :type="{bidirectional:'success',site:'primary',inbound:'warning'}[s.row.kind]">
            {{ {bidirectional:'双向对话',site:'独立站',inbound:'留资引流'}[s.row.kind]||s.row.kind }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="80"><template #default="s"><el-tag size="small" :type="s.row.enabled?'success':'info'">{{s.row.enabled?'启用':'未接'}}</el-tag></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:8px">说明: 双向(飞书/企微/公众号/小程序)可实时AI应答; 留资(抖音/快手/视频号/QQ)平台政策下仅引流留资入池; 独立站为自有AI客服入口。</div>
    </el-card>

    <el-card style="margin-top:12px">
      <template #header><span>渠道凭证配置 + 平台回调设置</span>
        <span style="float:right"><el-button size="small" @click="loadStatus">刷新</el-button></span></template>
      <el-table :data="cfgRows" size="small" border>
        <el-table-column prop="name" label="渠道" width="120"/>
        <el-table-column label="回调URL(填到平台后台)"><template #default="s">
          <code style="font-size:11px">{{s.row.callback}}</code>
          <el-button size="small" text type="primary" @click="copy(s.row.callback)">复制</el-button></template></el-table-column>
        <el-table-column label="凭证配置" width="260"><template #default="s">
          <el-tag v-for="(ok,f) in s.row.fields" :key="f" size="small" :type="ok?'success':'info'" style="margin-right:4px">
            {{fieldLabel(f)}}{{ok?'✓':'✗'}}</el-tag></template></el-table-column>
        <el-table-column label="Token缓存" width="90"><template #default="s">
          <el-tag size="small" :type="s.row.cached_token?'success':'info'">{{s.row.cached_token?'已取':'—'}}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="90"><template #default="s">
          <el-button size="small" type="primary" @click="openCfg(s.row)">配置</el-button></template></el-table-column>
      </el-table>
      <div style="color:#909399;font-size:11px;margin-top:8px">凭证存服务端 app 自管文件(600权限,离库,运行时热读改后无需重启);此处只显是否已配,不回显密钥。平台后台把"服务器URL/回调地址"填为上方对应 callback,Token 与此处一致即验签通过。</div>
    </el-card>

    <el-dialog v-model="cfgDlg" :title="'配置 '+(cfgCur.name||'')+' 凭证'" width="440">
      <el-form label-width="90">
        <el-form-item label="回调URL"><el-input :model-value="cfgCur.callback" readonly/></el-form-item>
        <el-form-item v-for="f in cfgFields" :key="f" :label="fieldLabel(f)">
          <el-input v-model="cfgForm[f]" :placeholder="cfgCur.fields&&cfgCur.fields[f]?'已配置(留空=不改)':'未配置'" show-password/>
          <div style="color:#909399;font-size:11px;line-height:1.5;margin-top:2px">从哪取:{{ srcHint(f) }}</div>
        </el-form-item>
      </el-form>
      <div style="color:#909399;font-size:11px">token=平台后台自定义的校验令牌; appid/secret=应用凭证; aeskey=企微消息加密(可选)。留空字段保留原值。</div>
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
const site=ref('qh'),cfg=ref({greeting:'',kb:[],enabled:true}),channels=ref([])
const chStatus=ref({}),cfgDlg=ref(false),cfgCur=ref({}),cfgForm=ref({}),cfgKey=ref('')
const FIELD_MAP={feishu:['token','appid','secret'],wecom:['token','aeskey','secret'],mp_wx:['token','appid','secret'],miniapp:['token','appid','secret']}
// 渠道凭证「从哪取」引导: SRC_HINTS[渠道键][字段]
const SRC_HINTS={
  feishu:{
    token:'飞书开放平台 → 应用 → 事件与回调 → 加密策略 → Verification Token',
    appid:'飞书开放平台 → 应用 → 凭证与基础信息 → App ID',
    secret:'飞书开放平台 → 应用 → 凭证与基础信息 → App Secret',
  },
  wecom:{
    token:'企业微信管理后台 → 应用管理 → 自建应用 → 接收消息 → API接收消息 → Token',
    aeskey:'同上「API接收消息」页 → EncodingAESKey(消息加解密密钥,43位)',
    secret:'企业微信管理后台 → 应用管理 → 自建应用 → 该应用 → Secret(点查看/发送到企业微信)',
  },
  mp_wx:{
    token:'微信公众平台 → 设置与开发 → 基本配置 → 服务器配置 → Token(自定义后填两处一致)',
    appid:'微信公众平台 → 设置与开发 → 基本配置 → 开发者ID(AppID)',
    secret:'微信公众平台 → 设置与开发 → 基本配置 → 开发者密码(AppSecret),需管理员扫码重置查看',
  },
  miniapp:{
    token:'微信公众平台(小程序) → 开发管理 → 开发设置 → 消息推送 → Token(自定义)',
    appid:'微信公众平台(小程序) → 开发管理 → 开发设置 → AppID',
    secret:'微信公众平台(小程序) → 开发管理 → 开发设置 → AppSecret(点生成/重置)',
  },
}
function srcHint(f){ return (SRC_HINTS[cfgKey.value]&&SRC_HINTS[cfgKey.value][f]) || '平台开发者后台 应用凭证页' }
const cfgRows=computed(()=>Object.keys(chStatus.value).map(k=>({key:k,...chStatus.value[k]})))
const cfgFields=computed(()=>FIELD_MAP[cfgKey.value]||['token','appid','secret'])
async function load(){ try{ const d=await api.chatConfig(site.value); cfg.value={greeting:d.greeting||'',kb:d.kb||[],enabled:d.enabled!==false} }catch(e){ ElMessage.error('加载失败') } }
async function save(){ try{ await api.chatConfigSave({site:site.value,greeting:cfg.value.greeting,kb:cfg.value.kb,enabled:cfg.value.enabled}); ElMessage.success('已保存') }catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } }
async function loadCh(){ try{ channels.value=(await api.channels()).channels||[] }catch(e){} }
async function loadStatus(){ try{ chStatus.value=await api.channelStatus() }catch(e){ ElMessage.error('状态加载失败(需超管 token)') } }
function openCfg(row){ cfgKey.value=row.key; cfgCur.value=row; cfgForm.value={}; cfgDlg.value=true }
async function saveCfg(){
  try{ await api.channelConfig({channel:cfgKey.value,...cfgForm.value}); ElMessage.success('已保存(热读生效)'); cfgDlg.value=false; loadStatus() }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(检查 Admin Token)') }
}
function copy(t){ navigator.clipboard&&navigator.clipboard.writeText(t); ElMessage.success('已复制') }
onMounted(()=>{ load(); loadCh(); loadStatus() })
</script>

