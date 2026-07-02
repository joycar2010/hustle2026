<template>
  <div class="layout">
    <div class="sidebar" :style="{width: collapsed?'64px':'210px'}">
      <div class="logo">
        <img src="/logo-white.png" alt="QH" style="height:26px;vertical-align:middle"/>
        <span v-if="!collapsed" style="margin-left:8px;vertical-align:middle">Quant Hedge</span>
      </div>
      <el-menu :collapse="collapsed" :default-active="$route.path" router
               background-color="#08113A" text-color="#9fb0d6" active-text-color="#fff" :collapse-transition="false">
        <el-menu-item-group v-for="grp in groups" :key="grp.name" :title="collapsed?'':grp.name">
          <el-menu-item v-for="r in grp.items" :key="r.path" :index="'/'+r.path">
            <el-icon><component :is="r.meta.icon"/></el-icon>
            <template #title>{{ t(r.meta.title) }}</template>
          </el-menu-item>
        </el-menu-item-group>
      </el-menu>
    </div>
    <div class="main-wrap">
      <div class="topbar">
        <el-icon style="cursor:pointer;font-size:18px" @click="collapsed=!collapsed"><Fold v-if="!collapsed"/><Expand v-else/></el-icon>
        <span class="sp"></span>
        <el-select v-model="layoutMode" size="small" style="width:110px" @change="noop">
          <el-option label="侧栏布局" value="side"/><el-option label="顶栏布局" value="top"/>
          <el-option label="混合布局" value="mix"/><el-option label="分栏布局" value="column"/>
        </el-select>
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
        <div v-if="!aiMsgs.length" class="ai-empty">您好！我是 Quant Hedge 运维助手，可解答管理后台功能用法与系统监控口径。</div>
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
        <div class="lg-logo">QUANT HEDGE</div>
        <div class="lg-sub">请登录以继续</div>
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
            <div style="color:#909399;font-size:11px;margin-top:8px">超管令牌= systemd QH_ADMIN_TOKEN,校验通过后本地保存。</div>
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
const route=useRoute(), router=useRouter()
const { t, locale } = useI18n()
const collapsed=ref(false), dark=ref(false), layoutMode=ref('side'), clock=ref(''), noop=()=>{}
const menus=router.options.routes[0].children
// tab 标题左侧功能图标: 由路径回查路由 meta.icon(与侧栏同一套扁平图标, 主色随主题)
function tabIcon(path){ const r=menus.find(m=>('/'+m.path)===path); return (r&&r.meta&&r.meta.icon)||'Document' }
// 操作员登录态 + 按权限(perms=逗号分隔模块key, '*'=全部)过滤菜单
const op=ref({operator:'',role:'',perms:''})
const opForm=ref({username:'',password:''})
// 强制登录门控
const authed=ref(false), gateTab=ref('op'), gateToken=ref(''), gateLicense=ref('')
function computeAuthed(){ authed.value = !!op.value.operator || !!localStorage.getItem('qh_admin_token') }
async function gateOpLogin(){
  try{ const r=await api.opLogin(opForm.value.username,opForm.value.password)
    localStorage.setItem('qh_op_token',r.token); op.value={operator:r.operator,role:r.role,perms:r.perms}
    opForm.value={username:'',password:''}; computeAuthed(); ElMessage.success('登录成功: '+r.role) }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'登录失败') }
}
async function gateAdminLogin(){
  if(!gateToken.value) return ElMessage.warning('请输入 Admin Token')
  // 用一个需鉴权的只读端点验证令牌有效性
  const prevT=localStorage.getItem('qh_admin_token'), prevL=localStorage.getItem('qh_key')
  localStorage.setItem('qh_admin_token',gateToken.value); if(gateLicense.value)localStorage.setItem('qh_key',gateLicense.value)
  try{ await api.operators(); computeAuthed(); ElMessage.success('超管进入') }
  catch(e){ // 回滚, 避免存下无效令牌
    if(prevT)localStorage.setItem('qh_admin_token',prevT); else localStorage.removeItem('qh_admin_token')
    if(prevL)localStorage.setItem('qh_key',prevL); ElMessage.error('令牌无效或无权限') }
}
function canSee(name){ const p=op.value.perms||''; if(!op.value.operator)return true; if(p==='*')return true; return p.split(',').map(x=>x.trim()).includes(name) }
const groups=computed(()=>{ const order=['分析','经营','运维']; const m={}; menus.forEach(r=>{ if(!canSee(r.name))return; const g=(r.meta&&r.meta.group)||'其它'; (m[g]=m[g]||[]).push(r) }); return order.filter(g=>m[g]).map(g=>({name:g,items:m[g]})) })
// 退出/更换: 清操作员会话 + 超管令牌, 门控重新弹出可换账号/令牌
async function opLogout(){ try{ await api.opLogout() }catch(e){}; localStorage.removeItem('qh_op_token'); localStorage.removeItem('qh_admin_token'); op.value={operator:'',role:'',perms:''}; computeAuthed(); ElMessage.success('已退出,请重新登录') }
async function restoreOp(){ if(localStorage.getItem('qh_op_token')){ try{ const m=await api.opMe(); op.value={operator:m.operator,role:m.role,perms:m.perms} }catch(e){ localStorage.removeItem('qh_op_token') } } computeAuthed() }
const tabs=ref([{path:'/dashboard',title:'dashboard'}])
const activeTab=ref('/dashboard')
function addTab(){
  const m=route.meta.title; if(!m)return
  if(!tabs.value.find(x=>x.path===route.path)) tabs.value.push({path:route.path,title:m})
  activeTab.value=route.path
}
watch(()=>route.path, addTab, {immediate:true})
function clickTab(p){ router.push(p.props.name) }
function removeTab(p){
  if(tabs.value.length<=1)return
  const i=tabs.value.findIndex(x=>x.path===p); tabs.value.splice(i,1)
  if(activeTab.value===p){ const n=tabs.value[Math.max(0,i-1)]; activeTab.value=n.path; router.push(n.path) }
}
function toggleTheme(){ dark.value=!dark.value; document.documentElement.classList.toggle('dark',dark.value) }
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
onMounted(()=>{ setInterval(()=>{ clock.value=new Date().toTimeString().slice(0,8) },1000); restoreOp() })
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
.login-gate{position:fixed;inset:0;z-index:3000;display:flex;align-items:center;justify-content:center;
  background:rgba(8,17,58,.55);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
.login-card{width:360px;background:#fff;border-radius:12px;padding:28px 26px;box-shadow:0 12px 40px rgba(0,0,0,.3)}
.lg-logo{font-size:18px;font-weight:700;color:#08113A;text-align:center}
.lg-sub{font-size:12px;color:#909399;text-align:center;margin:6px 0 14px}
:global(html.dark) .login-card{background:#0b1428;color:#cfe}
</style>
