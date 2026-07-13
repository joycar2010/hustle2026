<template>
  <div class="layout" :class="{'mobile-nav-open':mnav}">
    <div class="nav-mask" @click="mnav=false"></div>
    <div class="sidebar" :class="{'as-drawer':true}" :style="{width: collapsed?'64px':'210px'}">
      <div class="logo">
        <img :src="brand.logo||'/logo-white.png?v=xau1'" alt="Mix" class="brand-icon"/>
        <span v-if="!collapsed" class="brand-text">
          <template v-if="brand.title">{{ brand.title }}</template>
          <template v-else>HustleCoin <em>Mix</em></template>
        </span>
      </div>
      <el-menu :collapse="collapsed" :default-active="$route.path" router
               background-color="#12151A" text-color="#848E9C" active-text-color="#F0B90B" :collapse-transition="false" class="qh-menu">
        <template v-for="grp in groups" :key="grp.name">
          <!-- 总控: 无组头, 直接一条 -->
          <template v-if="grp.standalone">
            <el-menu-item v-for="r in grp.items" :key="r.path" :index="'/'+r.path">
              <el-icon><component :is="r.meta.icon"/></el-icon>
              <template #title>{{ t(r.meta.title) }}</template>
            </el-menu-item>
          </template>
          <!-- 其它: 可点击收缩的组头 -->
          <template v-else>
            <div v-if="!collapsed" class="grp-head" @click="toggleGroup(grp.name)">
              <span>{{ grp.name }}</span>
              <el-icon class="grp-arrow" :class="{closed:isGroupClosed(grp.name)}"><ArrowDown/></el-icon>
            </div>
            <el-menu-item v-for="r in grp.items" :key="r.path" :index="'/'+r.path"
                          v-show="collapsed || !isGroupClosed(grp.name)">
              <el-icon><component :is="r.meta.icon"/></el-icon>
              <template #title>{{ t(r.meta.title) }}</template>
            </el-menu-item>
          </template>
        </template>
      </el-menu>
    </div>
    <div class="main-wrap">
      <div class="topbar">
        <!-- 手机: 汉堡开抽屉; 桌面: 折叠侧栏 -->
        <el-icon class="hamburger" style="cursor:pointer;font-size:20px" @click="mnav=!mnav"><Expand/></el-icon>
        <el-icon class="fold-pc" style="cursor:pointer;font-size:18px" @click="collapsed=!collapsed"><Fold v-if="!collapsed"/><Expand v-else/></el-icon>
        <!-- 跑马灯（全局 WS marquee 频道,占顶栏左侧余量;emoji 显示层剥离,级别用色点） -->
        <div class="tb-marquee" :class="{quiet:!marqueeText}">
          <span class="mq-dot" :class="{on:wsOn}"></span>
          <div class="mq-clip" v-if="marqueeText"><span class="mq-txt" :title="marqueeText">{{ marqueeText }}</span></div>
          <span v-else class="mq-idle">通知通道待命</span>
        </div>
        <el-button size="small" class="wall-btn" @click="openWall('market')">屏1·机会墙</el-button>
        <el-button size="small" class="wall-btn" @click="openWall('risk')">屏3·风控墙</el-button>
        <el-popover trigger="click" width="320" :teleported="false" popper-class="op-panel-pop" @show="loadPanelHealth">
          <template #reference>
            <span class="op-chip"><el-icon><Avatar/></el-icon>{{op.operator||'超级管理员'}}（{{roleCn(op.role)}}）<el-icon><ArrowDown/></el-icon></span>
          </template>
          <!-- 用户面板(testgo 用户面板模式,适配三轨令牌;中文人性化) -->
          <div class="op-panel">
            <div class="opp-hd">
              <div class="opp-avatar"><el-icon><Avatar/></el-icon></div>
              <div class="opp-id">
                <b>{{ op.operator || '未登录' }}</b>
                <span class="opp-role">{{ roleCn(op.role) }} · {{ tokenKindCn }}</span>
              </div>
            </div>
            <div class="opp-sec">身份</div>
            <div class="opp-kv"><span>角色等级</span><b>{{ roleCn(op.role) }}</b></div>
            <div class="opp-kv"><span>可见权限</span><b>{{ op.perms==='*' ? '全部模块' : (op.perms||'—') }}</b></div>
            <div class="opp-kv"><span>登录方式</span><b>{{ tokenKindCn }}</b></div>
            <div class="opp-sec">系统状态</div>
            <div class="opp-kv"><span>数据源</span>
              <b :class="panelHealth.degraded ? 'warn' : 'ok'">{{ panelHealth.degraded ? '降级(部分不可用)' : '正常' }}</b></div>
            <div class="opp-kv"><span>总线服务</span><b>{{ panelHealth.bus_services_seen ?? '—' }} 个心跳在线</b></div>
            <div class="opp-kv"><span>通知通道</span><b :class="wsOn?'ok':'warn'">{{ wsOn ? 'WS 已连' : '待命/重连中' }}</b></div>
            <div class="opp-sec">飞书通知</div>
            <div class="opp-kv"><span>绑定状态</span>
              <b :class="feishu.open_id?'ok':'warn'">{{ feishu.open_id ? '已绑定' : '未绑定' }}</b></div>
            <div class="opp-acts">
              <el-button size="small" @click="openFeishu">飞书设置</el-button>
              <el-button size="small" @click="refreshIdentity">刷新身份</el-button>
              <el-button size="small" type="danger" plain @click="opLogout">退出 / 更换</el-button>
            </div>
          </div>
        </el-popover>
        <!-- 飞书通知绑定(自助;不含改令牌/改账号——账号治理在操作员管理,权限门控) -->
        <el-dialog v-model="feishuDlg" title="飞书通知设置" width="440" :teleported="true">
          <el-form label-width="110">
            <el-form-item label="飞书 Open ID"><el-input v-model="feishuForm.open_id" placeholder="ou_ 开头，接收通知优先级最高" /></el-form-item>
            <el-form-item label="飞书手机号">
              <el-input v-model="feishuForm.phone" placeholder="含国家码，如 +86199…">
                <template #append><el-button :loading="feishuLooking" @click="lookupFeishu">获取ID</el-button></template>
              </el-input>
            </el-form-item>
            <el-form-item label="飞书 Union ID"><el-input v-model="feishuForm.union_id" placeholder="跨应用唯一标识（可选）" /></el-form-item>
            <el-form-item label="启用飞书通知"><el-switch v-model="feishuForm.enabled" /></el-form-item>
          </el-form>
          <div style="font-size:11px;color:#5E6673;padding:0 8px">仅绑定个人飞书接收通道；账号/令牌治理在「操作员管理」，此处不可改。</div>
          <template #footer>
            <el-button @click="feishuDlg=false">取消</el-button>
            <el-button type="warning" @click="saveFeishu">保存</el-button>
          </template>
        </el-dialog>
        <span class="dotok"></span><span class="tb-clock">{{ clock }}</span>
      </div>
      <div class="tabs-bar">
        <el-tabs v-model="activeTab" type="card" closable @tab-remove="removeTab" @tab-click="clickTab" style="--el-tabs-header-height:32px">
          <el-tab-pane v-for="tab in tabs" :key="tab.path" :name="tab.path">
            <template #label>
              <span class="tab-lbl"><el-icon class="tab-ic"><component :is="tabIcon(tab.path)"/></el-icon>{{ t(tab.title) }}</span>
            </template>
          </el-tab-pane>
        </el-tabs>
      </div>
      <div class="crumb">{{ t($route.meta.title||'dashboard') }}</div>
      <div class="page"><router-view v-slot="{Component}"><keep-alive><component :is="Component"/></keep-alive></router-view></div>
    </div>

    <!-- AI 悬浮球（运维助手 + AI 顾问播报;新发言未读红点） -->
    <div class="ai-fab" @click="aiToggle" title="AI 助手 / 顾问播报" v-if="authed">
      <el-icon><Service/></el-icon>
      <i v-if="advUnread && !aiOpen" class="fab-badge">{{ advUnread }}</i>
    </div>
    <div class="ai-panel" v-if="aiOpen">
      <div class="ai-hd">
        <span class="ai-tabs">
          <b :class="{on:aiTab==='chat'}" @click="aiTab='chat'"><el-icon><Service/></el-icon> 运维助手</b>
          <b :class="{on:aiTab==='adv'}" @click="aiTab='adv'; advUnread=0">💬 顾问播报<i v-if="advUnread" class="tabdot">{{ advUnread }}</i></b>
        </span>
        <span class="ai-hd-acts">
          <el-icon class="x" :class="{muted:advDnd}" @click="toggleDnd" :title="advDnd?'免打扰已开(点击关闭)':'开启免打扰'"><MuteNotification v-if="advDnd"/><Bell v-else/></el-icon>
          <el-icon class="x" @click="aiTab==='chat'?aiClear():null" v-if="aiTab==='chat'" title="清空对话"><Delete/></el-icon>
          <el-icon class="x" @click="aiToggle" title="关闭"><Close/></el-icon>
        </span>
      </div>
      <!-- 运维助手对话 -->
      <div v-show="aiTab==='chat'" class="ai-body" ref="aiBodyEl">
        <div v-if="!aiMsgs.length" class="ai-empty">您好！我是 HustleCoin Mix 运维助手，可解答管理后台功能用法与系统监控口径。</div>
        <div v-for="(m,i) in aiMsgs" :key="m.id||i" :class="'ab '+m.who">{{m.txt}}<span class="ai-del" @click="aiDel(m.id)" title="删除">×</span></div>
      </div>
      <!-- AI 顾问播报（分域顾问最新发言） -->
      <div v-show="aiTab==='adv'" class="ai-body adv">
        <div v-if="!advisors.length" class="ai-empty">顾问播报加载中…</div>
        <div v-for="a in advisors" :key="a.key" class="adv-msg" :class="{off:!a.online}">
          <div class="adv-avatar">{{ a.avatar }}</div>
          <div class="adv-bubble">
            <div class="adv-top"><b>{{ a.name }}</b><span class="adv-cad">{{ a.cadence }}</span>
              <i class="adv-dot" :class="{bad:!a.online}"></i></div>
            <div class="adv-role">{{ a.role }}</div>
            <div class="adv-text">{{ a.text }}</div>
          </div>
        </div>
        <div class="adv-foot">播报每 30s 刷新 · {{ advDnd ? '免打扰已开(不自动弹屏)' : '有新发言自动弹屏' }}</div>
      </div>
      <div v-show="aiTab==='chat'" class="ai-foot">
        <el-input v-model="aiIn" size="small" placeholder="问运维/功能用法…" @keyup.enter="aiSend" autocomplete="off"/>
        <el-button size="small" type="primary" :loading="aiBusy" @click="aiSend">发送</el-button>
      </div>
    </div>

    <!-- 强制登录门控: 未登录时全屏蒙皮遮挡, 必须登录(操作员账号 或 超管令牌)才能进入 -->
    <div v-if="!authed" class="login-gate">
      <div class="login-card">
        <img class="lg-icon" src="/logo-white.png?v=xau1" alt="Mix" />
        <div class="lg-logo">HustleCoin <em>Mix</em></div>
        <div class="lg-sub">多策略持股公司驾驶舱 · 请登录以继续</div>
        <el-tabs v-model="gateTab" stretch>
          <el-tab-pane label="操作员登录" name="op">
            <el-input v-model="opForm.username" placeholder="账号" style="margin-bottom:10px"/>
            <el-input v-model="opForm.password" type="password" placeholder="密码" show-password @keyup.enter="gateOpLogin"  autocomplete="new-password"/>
            <el-button type="primary" style="width:100%;margin-top:14px" @click="gateOpLogin">登 录</el-button>
          </el-tab-pane>
          <el-tab-pane label="超管令牌" name="admin">
            <el-input v-model="gateToken" type="password" placeholder="Admin Token" show-password style="margin-bottom:10px" @keyup.enter="gateAdminLogin"  autocomplete="new-password"/>
            <el-input v-model="gateLicense" placeholder="License(可选, 部分写操作需要)" style="margin-bottom:10px"/>
            <el-button type="primary" style="width:100%;margin-top:4px" @click="gateAdminLogin">进 入</el-button>
            <div style="color:#909399;font-size:11px;margin-top:8px">令牌= dcm operator 令牌（SUPER_ADMIN/OPERATOR）或 Mix 只读令牌；校验通过后本地保存。写操作权限由后端按令牌角色判定。</div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, watch, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { mixApi } from '../api/mix'
import { connectStream } from '../api/mixWs'
const route=useRoute(), router=useRouter()
const { t } = useI18n()
const collapsed=ref(false), clock=ref('')
document.documentElement.classList.add('dark')  // 币安黑金,固定暗色(明亮/布局/语言切换已随qh壳退役)
const mnav=ref(false)   // 手机侧栏抽屉开合
// 侧栏品牌自定义(官网管理 site=qhadmin 配置; localStorage 缓存防首屏闪默认值; 公开只读端点未登录也可取)
const brand=ref((()=>{ try{ return JSON.parse(localStorage.getItem('qha_brand')||'{}') }catch(e){ return {} } })())
function applyBrand(b){ brand.value=b||{}; if(brand.value.docTitle)document.title=brand.value.docTitle
  try{ localStorage.setItem('qha_brand',JSON.stringify(brand.value)) }catch(e){} }
async function loadBrand(){ try{ applyBrand(await mixApi.siteBrand()||{}) }catch(e){} }
// SiteMgr 保存后广播即时热生效(同页免刷新)
window.addEventListener('qha-brand-updated', e=>applyBrand(e.detail||{}))
const menus=router.options.routes[0].children
// tab 标题左侧功能图标: 由路径回查路由 meta.icon(与侧栏同一套扁平图标, 主色随主题)
function tabIcon(path){ const r=menus.find(m=>('/'+m.path)===path); return (r&&r.meta&&r.meta.icon)||'Document' }
// 操作员登录态 + 按权限(perms=逗号分隔模块key, '*'=全部)过滤菜单
const op=ref({operator:'',role:'',perms:''})
const opForm=ref({username:'',password:''})
// 强制登录门控
const authed=ref(false), gateTab=ref('op'), gateToken=ref(''), gateLicense=ref('')
// Mix 登录门：三轨令牌(operator/只读/用户JWT)统一存 mix_token(与 api/mix.js 请求头同源)
function computeAuthed(){ authed.value = !!op.value.operator || !!localStorage.getItem('mix_token') }
async function gateOpLogin(){
  try{ const r=await mixApi.login(opForm.value.username,opForm.value.password)
    localStorage.setItem('mix_token', r.access_token)
    op.value={operator:r.username,role:'USER',perms:'*'}
    opForm.value={username:'',password:''}; computeAuthed(); ElMessage.success('登录成功: '+r.username) }
  catch(e){ ElMessage.error(e?.detail||e?.error||'登录失败') }
}
async function gateAdminLogin(){
  if(!gateToken.value) return ElMessage.warning('请输入令牌')
  try{
    const w=await mixApi.whoamiWith(gateToken.value.trim())
    localStorage.setItem('mix_token', gateToken.value.trim())
    op.value={operator:w.operator,role:w.role,perms:'*'}
    computeAuthed(); ElMessage.success(`进入: ${w.operator} (${w.role})`)
  }catch(e){ ElMessage.error('令牌无效（operator 令牌 / 只读令牌均可）') }
}
function canSee(name){ const p=op.value.perms||''; if(!op.value.operator)return true; if(p==='*')return true; return p.split(',').map(x=>x.trim()).includes(name) }
// 分组: 总控(置顶不收缩) → 分析 → 经营 → 运维; 隐藏 meta.hidden; 组内按 ord 排序
const groups=computed(()=>{ const order=['总控','系统设置','分析','经营','运维']; const m={}
  menus.forEach(r=>{ if(!canSee(r.name))return; if(r.meta&&r.meta.hidden)return; const g=(r.meta&&r.meta.group)||'其它'; (m[g]=m[g]||[]).push(r) })
  // 注意 ord:0 是合法值——不能用 ||99(falsy 坑,曾把主控台 ord:0 排到组尾)
  const ordOf=r=>(r.meta&&r.meta.ord!=null)?r.meta.ord:99
  return order.filter(g=>m[g]).map(g=>({name:g, standalone:(g==='总控'),
    items:m[g].slice().sort((a,b)=>ordOf(a)-ordOf(b))})) })
// 组收缩状态(localStorage 记忆; 默认全展开)
const closedGroups=ref((()=>{ try{ return JSON.parse(localStorage.getItem('qh_admin_closed_grps')||'[]') }catch(e){ return [] } })())
function isGroupClosed(name){ return closedGroups.value.includes(name) }
function toggleGroup(name){ const i=closedGroups.value.indexOf(name); if(i>=0)closedGroups.value.splice(i,1); else closedGroups.value.push(name)
  try{ localStorage.setItem('qh_admin_closed_grps', JSON.stringify(closedGroups.value)) }catch(e){} }
// 退出/更换: 清操作员会话 + 超管令牌, 门控重新弹出可换账号/令牌
async function opLogout(){ localStorage.removeItem('mix_token'); localStorage.removeItem('qh_op_token'); localStorage.removeItem('qh_admin_token'); op.value={operator:'',role:'',perms:''}; computeAuthed(); ElMessage.success('已退出,请重新登录') }
async function restoreOp(){ if(localStorage.getItem('mix_token')){ try{ const w=await mixApi.whoami(); op.value={operator:w.operator,role:w.role,perms:'*'} }catch(e){ localStorage.removeItem('mix_token') } } computeAuthed() }
const tabs=ref([{path:'/mix/dashboard',title:'中控台·Mix'}])
const activeTab=ref('/mix/dashboard')
function addTab(){
  const m=route.meta.title; if(!m)return
  if(!tabs.value.find(x=>x.path===route.path)) tabs.value.push({path:route.path,title:m})
  activeTab.value=route.path
}
watch(()=>route.path, ()=>{ addTab(); mnav.value=false; }, {immediate:true})
function clickTab(p){ router.push(p.props.name) }
function removeTab(p){
  if(tabs.value.length<=1)return
  const i=tabs.value.findIndex(x=>x.path===p); tabs.value.splice(i,1)
  if(activeTab.value===p){ const n=tabs.value[Math.max(0,i-1)]; activeTab.value=n.path; router.push(n.path) }
}
// 三分屏指挥墙（免登录只读路由,带墙令牌新开窗;屏2=本主控台）
function openWall(which){ const t=localStorage.getItem('mix_token')||''; window.open(`/wall/${which}?token=${encodeURIComponent(t)}`,'_blank') }
// API 层 401（令牌失效/被清）→ 重新弹登录门,不再用 window.prompt
window.addEventListener('mix-auth-required', ()=>{ op.value={operator:'',role:'',perms:''}; authed.value=false })
// 用户面板(testgo 模式): 身份+令牌轨道+数据源健康;令牌轨道按存储形态判别
const tokenKind = computed(()=>{
  const t = localStorage.getItem('mix_token')||''
  if(!t) return '未登录'
  if(t.split('.').length===3) return '用户 JWT'
  return op.value.role==='VIEWER' ? '只读令牌' : 'operator 令牌'
})
const panelHealth = ref({})
async function loadPanelHealth(){ try{ panelHealth.value = await mixApi.datasources() }catch(e){ panelHealth.value={degraded:true} } }
async function refreshIdentity(){ await restoreOp(); ElMessage.success('身份已刷新: '+(op.value.operator||'未登录')) }
// 角色中文人性化
const ROLE_CN = { SUPER_ADMIN:'超级管理员', OPERATOR:'操作员', VIEWER:'只读', USER:'用户', owner:'所有者', admin:'管理员', user:'用户' }
function roleCn(r){ return ROLE_CN[r] || r || '超级管理员' }
const tokenKindCn = computed(()=>{ const k=tokenKind.value; return ({'用户 JWT':'用户账号登录','operator 令牌':'操作员令牌','只读令牌':'只读令牌','未登录':'未登录'})[k] || k })
// 飞书自助绑定(个人接收通道;不含账号/令牌治理)
const feishu = ref((()=>{ try{ return JSON.parse(localStorage.getItem('mix_feishu')||'{}') }catch(e){ return {} } })())
const feishuDlg = ref(false), feishuLooking = ref(false)
const feishuForm = ref({ open_id:'', phone:'', union_id:'', enabled:true })
function openFeishu(){ feishuForm.value = { ...feishu.value }; feishuDlg.value = true }
async function lookupFeishu(){
  if(!feishuForm.value.phone) return ElMessage.warning('请填手机号(含国家码)')
  feishuLooking.value = true
  try{ const r = await mixApi.feishuLookup(feishuForm.value.phone)
    if(r.open_id) feishuForm.value.open_id = r.open_id
    if(r.union_id) feishuForm.value.union_id = r.union_id
    ElMessage.success('已获取飞书ID') }
  catch(e){ ElMessage.error(e?.detail || e?.error || '获取失败(手机号需在飞书通讯录)') }
  finally{ feishuLooking.value = false }
}
async function saveFeishu(){
  try{ await mixApi.feishuBind({ ...feishuForm.value })
    feishu.value = { ...feishuForm.value }
    localStorage.setItem('mix_feishu', JSON.stringify(feishu.value))
    ElMessage.success('飞书通知设置已保存'); feishuDlg.value = false }
  catch(e){ ElMessage.error(e?.detail || e?.error || '保存失败') }
}
// 全局跑马灯（Layout 自持一条 WS,所有页面可见;emoji 属消息文本,显示层剥离改用色点分级）
const marqueeText=ref(''), wsOn=ref(false)
const EMOJI_RE=/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu
let wsClose=null
function startMarquee(){
  if(wsClose) return
  wsClose=connectStream(msg=>{ wsOn.value=true
    if(msg.channel==='marquee'){ const d=msg.data||msg
      const raw=d.text||d.title||d.content||''
      marqueeText.value=String(raw).replace(EMOJI_RE,'').replace(/\s+/g,' ').trim() } })
}
// AI 运维助手悬浮球(site=qhadmin, 接 qh 后端 LLM; 未配置则后端回退; localStorage 保存/删除/清空对齐 qh)
import { nextTick } from 'vue'
const aiOpen=ref(false),aiIn=ref(''),aiBusy=ref(false),aiConvId=ref(null),aiBodyEl=ref(null)
const aiMsgs=ref((()=>{ try{ return JSON.parse(localStorage.getItem('qha_history')||'[]') }catch(e){ return [] } })())
try{ aiConvId.value=localStorage.getItem('qha_conv_id')||null }catch(e){}
function aiSave(){ try{ localStorage.setItem('qha_history', JSON.stringify(aiMsgs.value.slice(-200))); if(aiConvId.value)localStorage.setItem('qha_conv_id',aiConvId.value) }catch(e){} }
function aiId(){ return 'm'+Date.now()+Math.random().toString(36).slice(2,5) }
const aiTab=ref('chat')
function aiToggle(){ aiOpen.value=!aiOpen.value; if(aiOpen.value && aiTab.value==='adv') advUnread.value=0 }
// AI 顾问播报（分域顾问最新发言;有新发言自动弹屏,可免打扰）
const advisors=ref([]), advUnread=ref(0)
const advDnd=ref(localStorage.getItem('mix_adv_dnd')==='1')
let advSig=''
function toggleDnd(){ advDnd.value=!advDnd.value; localStorage.setItem('mix_adv_dnd', advDnd.value?'1':'0'); ElMessage.info(advDnd.value?'顾问播报免打扰已开':'免打扰已关，有新发言会自动弹屏') }
async function loadAdvisors(){
  try{
    const list=await mixApi.monitor.advisorsChat()
    const sig=list.map(a=>a.key+':'+a.text).join('|')
    const changed = advSig && sig!==advSig   // 首次加载不算新发言,不弹屏
    advisors.value=list
    if(changed){
      if(!aiOpen.value || aiTab.value!=='adv') advUnread.value=Math.min(9,advUnread.value+1)
      if(!advDnd.value && !aiOpen.value){ aiOpen.value=true; aiTab.value='adv'; advUnread.value=0 }  // 自动弹屏
    }
    advSig=sig
  }catch(e){ /* 降级 */ }
}
function aiDel(id){ aiMsgs.value=aiMsgs.value.filter(m=>m.id!==id); aiSave() }
function aiClear(){ if(!aiMsgs.value.length)return; if(!confirm('确定清空所有对话记录？此操作不可撤销。'))return; aiMsgs.value=[]; aiConvId.value=null; try{localStorage.removeItem('qha_conv_id')}catch(e){}; aiSave() }
async function aiSend(){
  const t=(aiIn.value||'').trim(); if(!t)return; aiIn.value=''; aiMsgs.value.push({id:aiId(),who:'me',txt:t}); aiSave(); aiBusy.value=true
  await nextTick(()=>{ if(aiBodyEl.value)aiBodyEl.value.scrollTop=aiBodyEl.value.scrollHeight })
  try{
    // 走 mix 后端 /ai/chat(新 LLM 中转站链路:主备自动降级+用量落账+实时系统上下文)
    const r=await mixApi.aiChat({conversation_id:aiConvId.value,message:t})
    if(r.conversation_id)aiConvId.value=r.conversation_id
    const tail=r.model?`\n—— ${r.model}${r.degraded?'(备用站)':''}`:''
    aiMsgs.value.push({id:aiId(),who:'ai',txt:(r.reply||r.detail||'暂不可用')+tail}); aiSave()
  }catch(e){ aiMsgs.value.push({id:aiId(),who:'ai',txt:'AI 服务调用失败: '+(e?.detail||e?.error||'请稍后重试')}); aiSave() }
  finally{ aiBusy.value=false; await nextTick(()=>{ if(aiBodyEl.value)aiBodyEl.value.scrollTop=aiBodyEl.value.scrollHeight }) }
}
onMounted(()=>{ setInterval(()=>{ clock.value=new Date().toTimeString().slice(0,8) },1000); restoreOp(); loadBrand(); startMarquee(); loadAdvisors(); setInterval(loadAdvisors, 30000) })
</script>
<style scoped>
.ai-fab{position:fixed;right:24px;bottom:24px;width:52px;height:52px;border-radius:50%;background:var(--el-color-primary);color:#fff;
  display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:2000;box-shadow:0 6px 20px rgba(8,17,58,.3);font-size:22px}
.ai-fab:hover{filter:brightness(1.1)}
.ai-fab .fab-badge{position:absolute;top:-2px;right:-2px;min-width:18px;height:18px;border-radius:9px;background:#F6465D;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;padding:0 4px;box-shadow:0 0 0 2px var(--el-bg-color)}
.ai-panel{position:fixed;right:24px;bottom:88px;width:360px;height:500px;background:var(--el-bg-color);border:1px solid var(--el-border-color);
  border-radius:14px;z-index:2001;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 12px 40px rgba(8,17,58,.28)}
.ai-hd{background:var(--el-color-primary);color:#0B0E11;padding:10px 12px;font-weight:700;font-size:14px;display:flex;align-items:center;justify-content:space-between;gap:6px}
.ai-hd .ai-tabs{display:flex;gap:4px}
.ai-hd .ai-tabs b{display:inline-flex;align-items:center;gap:4px;font-size:12.5px;font-weight:600;opacity:.6;cursor:pointer;padding:3px 8px;border-radius:7px}
.ai-hd .ai-tabs b.on{opacity:1;background:rgba(0,0,0,.14)}
.ai-hd .ai-tabs .tabdot{font-style:normal;background:#F6465D;color:#fff;font-size:9px;border-radius:8px;padding:0 4px;min-width:14px;text-align:center}
.ai-hd .ai-hd-acts{display:flex;gap:8px;align-items:center}
.ai-hd .x{cursor:pointer;opacity:.85}
.ai-hd .x:hover{opacity:1}
.ai-hd .x.muted{color:#F6465D}
/* 顾问播报气泡 */
.ai-body.adv{padding:10px}
.adv-msg{display:flex;gap:8px;margin-bottom:12px;align-items:flex-start}
.adv-msg.off{opacity:.55}
.adv-avatar{width:34px;height:34px;border-radius:50%;background:var(--el-fill-color);display:flex;align-items:center;justify-content:center;font-size:19px;flex:none;box-shadow:0 0 0 1px var(--el-border-color)}
.adv-bubble{flex:1;min-width:0;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:10px;border-top-left-radius:2px;padding:7px 10px}
.adv-top{display:flex;align-items:center;gap:6px}
.adv-top b{font-size:12.5px;color:var(--el-text-color-primary)}
.adv-top .adv-cad{font-size:10px;color:var(--el-text-color-placeholder)}
.adv-top .adv-dot{width:6px;height:6px;border-radius:50%;background:#0ECB81;margin-left:auto}
.adv-top .adv-dot.bad{background:#F6465D}
.adv-role{font-size:10.5px;color:var(--el-text-color-placeholder);margin:1px 0 4px}
.adv-text{font-size:12.5px;line-height:1.55;color:var(--el-text-color-regular);word-break:break-word}
.adv-foot{text-align:center;font-size:10px;color:var(--el-text-color-placeholder);padding:4px 0}
.ai-body{flex:1;overflow-y:auto;padding:12px;background:var(--el-fill-color-lighter);font-size:13px}
.ai-body .ai-empty{text-align:center;color:var(--el-text-color-secondary);font-size:12px;padding:26px 10px}
.ai-body .ab{position:relative;max-width:86%;padding:8px 11px;border-radius:9px;margin:6px 0;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.ai-body .ab.me{background:var(--el-color-primary);color:#fff;margin-left:auto}
.ai-body .ab.ai{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);color:var(--el-text-color-primary)}
.ai-body .ai-del{display:none;position:absolute;top:-7px;width:18px;height:18px;border-radius:50%;background:var(--el-bg-color);border:1px solid var(--el-border-color);color:var(--el-text-color-secondary);font-size:12px;line-height:16px;text-align:center;cursor:pointer}
.ai-body .ab:hover .ai-del{display:block}
.ai-body .ab.me .ai-del{left:-7px} .ai-body .ab.ai .ai-del{right:-7px}
.ai-foot{display:flex;gap:8px;padding:10px;border-top:1px solid var(--el-border-color-lighter)}
/* tab 标题左侧扁平图标: 与文字基线对齐, 颜色继承(未激活=次要色, 激活=主色, 随主题自适应) */
.tab-lbl{display:inline-flex;align-items:center;gap:5px}
.tab-ic{font-size:14px;vertical-align:-2px}
/* 页签币安金风: 金边+金字,激活态亮金底衬 */
.tabs-bar :deep(.el-tabs--card>.el-tabs__header){border-bottom:1px solid rgba(240,185,11,.35)}
.tabs-bar :deep(.el-tabs--card>.el-tabs__header .el-tabs__nav){border:1px solid rgba(240,185,11,.3);border-bottom:none;border-radius:8px 8px 0 0}
.tabs-bar :deep(.el-tabs--card>.el-tabs__header .el-tabs__item){border-left-color:rgba(240,185,11,.22);color:rgba(240,185,11,.62);font-weight:600}
.tabs-bar :deep(.el-tabs--card>.el-tabs__header .el-tabs__item:hover){color:#FCD535}
.tabs-bar :deep(.el-tabs--card>.el-tabs__header .el-tabs__item.is-active){color:#F0B90B;background:rgba(240,185,11,.1);border-bottom-color:transparent}
/* 顶栏跑马灯: 占余量宽度,超长文本匀速滚动(hover 暂停);无消息=安静待命态 */
.tb-marquee{flex:1;min-width:0;display:flex;align-items:center;gap:8px;margin:0 12px;padding:4px 12px;
  border:1px solid rgba(240,185,11,.25);border-radius:14px;background:rgba(240,185,11,.06);font-size:12px;color:#F0B90B;overflow:hidden}
.tb-marquee.quiet{border-color:var(--el-border-color);background:transparent}
.mq-dot{width:7px;height:7px;border-radius:50%;background:#5E6673;flex:none}
.mq-dot.on{background:#0ECB81;box-shadow:0 0 6px rgba(14,203,129,.8)}
.mq-clip{flex:1;min-width:0;overflow:hidden;white-space:nowrap}
.mq-txt{display:inline-block;white-space:nowrap;min-width:100%;animation:mq-roll 22s linear infinite;will-change:transform}
.mq-clip:hover .mq-txt{animation-play-state:paused}
@keyframes mq-roll{0%{transform:translateX(100%)}100%{transform:translateX(-100%)}}
.mq-idle{color:#5E6673;font-size:11px}
/* 用户区/时钟: 币安金风(白字+金图标) */
.op-chip{cursor:pointer;font-size:13px;color:#EAECEF;font-weight:600;display:inline-flex;align-items:center;gap:4px}
.op-chip .el-icon{color:#F0B90B}
.op-chip:hover{color:#F0B90B}
.tb-clock{font-size:12px;color:#848E9C;font-variant-numeric:tabular-nums}
.wall-btn{border-color:rgba(240,185,11,.35);color:#F0B90B;background:transparent}
.wall-btn:hover{border-color:#F0B90B;background:rgba(240,185,11,.1);color:#FCD535}
/* 用户面板(testgo 模式) */
.op-panel{font-size:12px;color:#EAECEF}
.opp-hd{display:flex;gap:10px;align-items:center;padding-bottom:10px;border-bottom:1px solid #262B33}
.opp-avatar{width:38px;height:38px;border-radius:50%;background:rgba(240,185,11,.14);color:#F0B90B;display:flex;align-items:center;justify-content:center;font-size:19px}
.opp-id{display:flex;flex-direction:column;gap:2px}
.opp-id b{font-size:14px}
.opp-role{font-size:11px;color:#848E9C}
.opp-sec{margin:10px 0 4px;font-size:10px;font-weight:800;color:#5E6673;letter-spacing:1px}
.opp-kv{display:flex;justify-content:space-between;padding:2.5px 0;color:#848E9C}
.opp-kv b{color:#EAECEF;font-weight:600}
.opp-kv b.ok{color:#0ECB81}
.opp-kv b.warn{color:#F0B90B}
.opp-acts{display:flex;gap:8px;margin-top:12px;justify-content:flex-end}
/* 品牌区：画板金柱 LOGO + 双色文字（HustleCoin 白 / Mix 金）+ 金辉光 */
.brand-icon{height:28px;width:28px;border-radius:7px;object-fit:contain;vertical-align:middle;
  filter:drop-shadow(0 0 10px rgba(240,185,11,.5))}
.brand-text{margin-left:9px;vertical-align:middle;font-weight:800;font-size:15px;color:#EAECEF;letter-spacing:.2px}
.brand-text em{font-style:normal;color:#F0B90B}
/* Mix 黑金登录门（与 mix.hustle2026.xyz/login 同款视觉） */
.login-gate{position:fixed;inset:0;z-index:3000;display:flex;align-items:center;justify-content:center;
  background:rgba(11,14,17,.94);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
.login-card{width:380px;background:#181B21;border:1px solid #262B33;border-radius:14px;padding:30px 28px;
  box-shadow:0 16px 48px rgba(0,0,0,.6);color:#EAECEF;text-align:center}
.lg-icon{width:56px;height:56px;border-radius:12px;margin:0 auto 12px;display:block;
  filter:drop-shadow(0 0 14px rgba(240,185,11,.45))}
.lg-logo{font-size:22px;font-weight:800;color:#EAECEF;text-align:center}
.lg-logo em{font-style:normal;color:#F0B90B}
.lg-sub{font-size:12px;color:#848E9C;text-align:center;margin:6px 0 16px}
.login-card :deep(.el-tabs__item){color:#848E9C}
.login-card :deep(.el-tabs__item.is-active){color:#F0B90B}
.login-card :deep(.el-tabs__active-bar){background:#F0B90B}
.login-card :deep(.el-input__wrapper){background:#12151A;box-shadow:0 0 0 1px #262B33 inset}
.login-card :deep(.el-input__inner){color:#EAECEF}
.login-card :deep(.el-button--primary){background:#F0B90B;border-color:#F0B90B;color:#0B0E11;font-weight:700}
.login-card :deep(.el-button--primary:hover){background:#FCD535;border-color:#FCD535}
</style>
