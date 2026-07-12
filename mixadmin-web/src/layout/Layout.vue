<template>
  <div class="layout" :class="{'mobile-nav-open':mnav}">
    <div class="nav-mask" @click="mnav=false"></div>
    <div class="sidebar" :class="{'as-drawer':true}" :style="{width: collapsed?'64px':'210px'}">
      <div class="logo">
        <img :src="brand.logo||'/logo-white.png'" alt="Mix" class="brand-icon"/>
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
        <span class="sp"></span>
        <el-select v-model="layoutMode" size="small" style="width:110px" @change="noop">
          <el-option label="侧栏布局" value="side"/><el-option label="顶栏布局" value="top"/>
          <el-option label="混合布局" value="mix"/><el-option label="分栏布局" value="column"/>
        </el-select>
        <el-button size="small" @click="openWall('market')">屏1·机会墙</el-button>
        <el-button size="small" @click="openWall('risk')">屏3·风控墙</el-button>
        <el-button size="small" @click="toggleLang">{{ locale==='zh'?'EN':'中' }}</el-button>
        <el-button size="small" @click="toggleTheme">{{ dark? t('light'):t('dark') }}</el-button>
        <el-dropdown trigger="click" style="margin:0 4px">
          <span style="cursor:pointer;font-size:13px;color:#2E8BD6;font-weight:600;display:inline-flex;align-items:center;gap:4px"><el-icon><Avatar/></el-icon>{{op.operator||'超级管理员'}} ({{op.role||'super'}})<el-icon><ArrowDown/></el-icon></span>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item disabled>权限: {{op.perms||'全部'}}</el-dropdown-item>
            <el-dropdown-item divided @click="opLogout">退出登录 / 更换操作员</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
        <span class="dotok"></span><span style="font-size:12px">{{ clock }}</span>
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

    <!-- AI 运维助手悬浮球(site=qhadmin, 接 qh 后端 LLM, 数据隔离) -->
    <div class="ai-fab" @click="aiToggle" title="AI 运维助手" v-if="authed"><el-icon><Service/></el-icon></div>
    <div class="ai-panel" v-if="aiOpen">
      <div class="ai-hd"><span><el-icon><Service/></el-icon> AI 运维助手</span>
        <span class="ai-hd-acts">
          <span class="ai-cnt" v-if="aiMsgs.length">{{aiMsgs.length}} 条</span>
          <el-icon class="x" @click="aiClear" title="清空对话"><Delete/></el-icon>
          <el-icon class="x" @click="aiToggle" title="关闭"><Close/></el-icon>
        </span></div>
      <div class="ai-body" ref="aiBodyEl">
        <div v-if="!aiMsgs.length" class="ai-empty">您好！我是 HustleCoin Mix 运维助手，可解答管理后台功能用法与系统监控口径。</div>
        <div v-for="(m,i) in aiMsgs" :key="m.id||i" :class="'ab '+m.who">{{m.txt}}<span class="ai-del" @click="aiDel(m.id)" title="删除">×</span></div>
      </div>
      <div class="ai-foot">
        <el-input v-model="aiIn" size="small" placeholder="问运维/功能用法…" @keyup.enter="aiSend" autocomplete="off"/>
        <el-button size="small" type="primary" :loading="aiBusy" @click="aiSend">发送</el-button>
      </div>
    </div>

    <!-- 强制登录门控: 未登录时全屏蒙皮遮挡, 必须登录(操作员账号 或 超管令牌)才能进入 -->
    <div v-if="!authed" class="login-gate">
      <div class="login-card">
        <img class="lg-icon" src="/logo-white.png" alt="Mix" />
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
const route=useRoute(), router=useRouter()
const { t, locale } = useI18n()
const collapsed=ref(false), dark=ref(true), layoutMode=ref('side'), clock=ref(''), noop=()=>{}
document.documentElement.classList.toggle('dark', dark.value)  // 画板=黑金,默认暗色
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
  return order.filter(g=>m[g]).map(g=>({name:g, standalone:(g==='总控'),
    items:m[g].slice().sort((a,b)=>((a.meta&&a.meta.ord)||99)-((b.meta&&b.meta.ord)||99))})) })
// 组收缩状态(localStorage 记忆; 默认全展开)
const closedGroups=ref((()=>{ try{ return JSON.parse(localStorage.getItem('qh_admin_closed_grps')||'[]') }catch(e){ return [] } })())
function isGroupClosed(name){ return closedGroups.value.includes(name) }
function toggleGroup(name){ const i=closedGroups.value.indexOf(name); if(i>=0)closedGroups.value.splice(i,1); else closedGroups.value.push(name)
  try{ localStorage.setItem('qh_admin_closed_grps', JSON.stringify(closedGroups.value)) }catch(e){} }
// 退出/更换: 清操作员会话 + 超管令牌, 门控重新弹出可换账号/令牌
async function opLogout(){ localStorage.removeItem('mix_token'); localStorage.removeItem('qh_op_token'); localStorage.removeItem('qh_admin_token'); op.value={operator:'',role:'',perms:''}; computeAuthed(); ElMessage.success('已退出,请重新登录') }
async function restoreOp(){ if(localStorage.getItem('mix_token')){ try{ const w=await mixApi.whoami(); op.value={operator:w.operator,role:w.role,perms:'*'} }catch(e){ localStorage.removeItem('mix_token') } } computeAuthed() }
const tabs=ref([{path:'/mix/dashboard',title:'主控台·Mix'}])
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
function toggleTheme(){ dark.value=!dark.value; document.documentElement.classList.toggle('dark',dark.value) }
// 三分屏指挥墙（免登录只读路由,带墙令牌新开窗;屏2=本主控台）
function openWall(which){ const t=localStorage.getItem('mix_token')||''; window.open(`/wall/${which}?token=${encodeURIComponent(t)}`,'_blank') }
// API 层 401（令牌失效/被清）→ 重新弹登录门,不再用 window.prompt
window.addEventListener('mix-auth-required', ()=>{ op.value={operator:'',role:'',perms:''}; authed.value=false })
function toggleLang(){ locale.value = locale.value==='zh'?'en':'zh' }
// AI 运维助手悬浮球(site=qhadmin, 接 qh 后端 LLM; 未配置则后端回退; localStorage 保存/删除/清空对齐 qh)
import { nextTick } from 'vue'
const aiOpen=ref(false),aiIn=ref(''),aiBusy=ref(false),aiConvId=ref(null),aiBodyEl=ref(null)
const aiMsgs=ref((()=>{ try{ return JSON.parse(localStorage.getItem('qha_history')||'[]') }catch(e){ return [] } })())
try{ aiConvId.value=localStorage.getItem('qha_conv_id')||null }catch(e){}
function aiSave(){ try{ localStorage.setItem('qha_history', JSON.stringify(aiMsgs.value.slice(-200))); if(aiConvId.value)localStorage.setItem('qha_conv_id',aiConvId.value) }catch(e){} }
function aiId(){ return 'm'+Date.now()+Math.random().toString(36).slice(2,5) }
function aiToggle(){ aiOpen.value=!aiOpen.value }
function aiDel(id){ aiMsgs.value=aiMsgs.value.filter(m=>m.id!==id); aiSave() }
function aiClear(){ if(!aiMsgs.value.length)return; if(!confirm('确定清空所有对话记录？此操作不可撤销。'))return; aiMsgs.value=[]; aiConvId.value=null; try{localStorage.removeItem('qha_conv_id')}catch(e){}; aiSave() }
async function aiSend(){
  const t=(aiIn.value||'').trim(); if(!t)return; aiIn.value=''; aiMsgs.value.push({id:aiId(),who:'me',txt:t}); aiSave(); aiBusy.value=true
  await nextTick(()=>{ if(aiBodyEl.value)aiBodyEl.value.scrollTop=aiBodyEl.value.scrollHeight })
  try{
    const r=await api.aiChat({site:'qhadmin',conversation_id:aiConvId.value,message:t,user_id:'admin'})
    if(r.conversation_id)aiConvId.value=r.conversation_id
    aiMsgs.value.push({id:aiId(),who:'ai',txt:r.reply||r.detail||'暂不可用'}); aiSave()
  }catch(e){ aiMsgs.value.push({id:aiId(),who:'ai',txt:'AI 服务调用失败: '+(e?.response?.data?.detail||'请稍后重试')}); aiSave() }
  finally{ aiBusy.value=false; await nextTick(()=>{ if(aiBodyEl.value)aiBodyEl.value.scrollTop=aiBodyEl.value.scrollHeight }) }
}
onMounted(()=>{ setInterval(()=>{ clock.value=new Date().toTimeString().slice(0,8) },1000); restoreOp(); loadBrand() })
</script>
<style scoped>
.ai-fab{position:fixed;right:24px;bottom:24px;width:52px;height:52px;border-radius:50%;background:var(--el-color-primary);color:#fff;
  display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:2000;box-shadow:0 6px 20px rgba(8,17,58,.3);font-size:22px}
.ai-fab:hover{filter:brightness(1.1)}
.ai-panel{position:fixed;right:24px;bottom:88px;width:340px;height:480px;background:var(--el-bg-color);border:1px solid var(--el-border-color);
  border-radius:14px;z-index:2001;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 12px 40px rgba(8,17,58,.28)}
.ai-hd{background:var(--el-color-primary);color:#fff;padding:12px 14px;font-weight:700;font-size:14px;display:flex;align-items:center;justify-content:space-between;gap:6px}
.ai-hd span{display:flex;align-items:center;gap:6px}
.ai-hd .ai-hd-acts{gap:10px}
.ai-hd .ai-cnt{font-size:10px;opacity:.75;font-weight:400}
.ai-hd .x{cursor:pointer;opacity:.85}
.ai-hd .x:hover{opacity:1}
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
