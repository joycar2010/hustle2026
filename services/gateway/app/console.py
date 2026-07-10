"""DexCexMix 管理控制台(Vue3 + Element Plus,复用 qh_admin 栈)。

单文件 SPA(CDN)由 gateway 托管:登录(X-Op-Token)→ 侧栏多视图 → BFF API。
视图:总览 / 引擎控制(armed 热切换+Kill Switch+武装联锁) / 路由 / 告警历史 / 审计 / 借贷 / coin桥。
所有写操作带 Element Plus 二次确认 + 权限门控(前端提示,后端 RBAC 是真闸)。
迁移路径:结构/组件/api 形态与 qh_admin 一致,可平滑搬进 Vite 多文件工程。
"""

CONSOLE_HTML = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>DexCexMix 控制台</title>
<link rel="stylesheet" href="https://unpkg.com/element-plus@2.7.6/dist/index.css">
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#e6edf3;--dim:#8b949e;--accent:#58a6ff}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
#app{height:100%}.el-container{height:100%}
.el-aside{background:#0d1117;border-right:1px solid var(--border)}
.brand{padding:14px 16px;font-weight:700;font-size:16px;color:var(--accent);border-bottom:1px solid var(--border)}
.el-menu{background:transparent;border:0}.el-menu-item{color:var(--dim)!important}.el-menu-item.is-active{color:var(--accent)!important;background:#161b22!important}
.el-header{background:var(--panel);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
.el-main{background:var(--bg)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:12px}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.kpi{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px 16px;min-width:120px}
.kpi b{font-size:20px;display:block}.kpi span{color:var(--dim);font-size:11px}
.pos{color:#3fb950}.neg{color:#f85149}.dim{color:var(--dim)}.mono{font-family:ui-monospace,Menlo,monospace}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.s-ok{background:#3fb950}.s-stale{background:#d29922}.s-missing{background:#f85149}
h3{margin:0 0 10px;font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
.login{display:flex;height:100%;align-items:center;justify-content:center}
.el-table{background:transparent!important;color:var(--fg)}
.el-table th.el-table__cell{background:#161b22!important;color:var(--dim)!important}
.el-table tr,.el-table td.el-table__cell{background:transparent!important;color:var(--fg)!important;border-color:#21262d!important}
.el-table--enable-row-hover .el-table__body tr:hover>td.el-table__cell{background:#1c2430!important}
</style></head><body><div id="app"></div>
<script src="https://unpkg.com/vue@3.4.31/dist/vue.global.prod.js"></script>
<script src="https://unpkg.com/element-plus@2.7.6/dist/index.full.min.js"></script>
<script>
const {createApp,ref,reactive,onMounted,onUnmounted,computed,h}=Vue
const TOKKEY='dcm_op_token'
function tok(){return localStorage.getItem(TOKKEY)||''}
async function api(path,opts={}){
  const o=Object.assign({headers:{}},opts)
  o.headers['X-Op-Token']=tok()
  if(o.body){o.headers['Content-Type']='application/json';o.body=JSON.stringify(o.body)}
  const r=await fetch(path,o)
  if(r.status===401){localStorage.removeItem(TOKKEY);location.reload()}
  const d=await r.json().catch(()=>({}))
  if(!r.ok){throw {status:r.status,data:d}}
  return d
}
const fmt=(v,d=2)=>v==null?'–':(+v).toFixed(d)
const cls=v=>v==null?'':(v>=0?'pos':'neg')

const Overview={template:`<div>
 <div class="kpis">
  <div class="kpi"><b :class="cls(o.pnl&&o.pnl.net_total)">{{fmt(o.pnl&&o.pnl.net_total)}}</b><span>累计净PnL</span></div>
  <div class="kpi"><b>{{o.reconcile&&o.reconcile.total_equity_usdt}}</b><span>实盘权益</span></div>
  <div class="kpi"><b>{{(o.open_positions||[]).length}}</b><span>在场配对</span></div>
  <div class="kpi"><b :class="o.alerts_this_round?'neg':'pos'">{{o.alerts_this_round}}</b><span>本轮告警</span></div>
  <div class="kpi"><b>{{svcok}}/{{(o.services||[]).length}}</b><span>服务在线</span></div>
  <div class="kpi"><b><el-tag :type="o.mode==='armed'?'danger':'info'">{{o.mode}}</el-tag></b><span>引擎模式</span></div>
 </div>
 <div class="card"><h3>服务健康</h3><el-table :data="o.services" size="small">
  <el-table-column label="服务"><template #default="s"><span class="dot" :class="'s-'+s.row.state"></span>{{s.row.name}}</template></el-table-column>
  <el-table-column prop="state" label="状态" width="90"/><el-table-column prop="age" label="心跳(s)" width="90"/></el-table></div>
 <div class="card"><h3>在场配对 + 风控护栏</h3><el-table :data="(o.guards&&o.guards.pairs)||[]" size="small" empty-text="无在场配对">
  <el-table-column prop="symbol" label="币"/><el-table-column label="venue"><template #default="s">{{s.row.venue_long}}/{{s.row.venue_short}}</template></el-table-column>
  <el-table-column label="多腿距强平%"><template #default="s">{{fmt(s.row.dist_liq&&s.row.dist_liq.long,1)}}</template></el-table-column>
  <el-table-column label="空腿距强平%"><template #default="s">{{fmt(s.row.dist_liq&&s.row.dist_liq.short,1)}}</template></el-table-column>
  <el-table-column label="配对浮亏"><template #default="s"><span :class="cls(s.row.upnl?(+s.row.upnl.long+ +s.row.upnl.short):0)">{{s.row.upnl?fmt(+s.row.upnl.long+ +s.row.upnl.short,4):'–'}}</span></template></el-table-column></el-table></div>
 <div class="card"><h3>各所权益/持仓 + 保证金水位</h3><el-table :data="o.waterline||[]" size="small">
  <el-table-column prop="venue" label="所"/><el-table-column label="权益"><template #default="s">{{fmt(s.row.equity)}}</template></el-table-column>
  <el-table-column label="在场名义"><template #default="s">{{fmt(s.row.pos_notional)}}</template></el-table-column>
  <el-table-column label="有效杠杆"><template #default="s"><span :class="s.row.leverage>4?'neg':''">{{fmt(s.row.leverage,2)}}x</span></template></el-table-column></el-table></div>
 </div>`,
 setup(){const o=ref({});let t;async function tick(){try{o.value=await api('/api/overview')}catch(e){}}
  const svcok=computed(()=>(o.value.services||[]).filter(s=>s.state==='ok').length)
  onMounted(()=>{tick();t=setInterval(tick,5000)});onUnmounted(()=>clearInterval(t));return{o,fmt,cls,svcok}}}

const EngineCtl={template:`<div>
 <el-alert v-if="me.role!=='SUPER_ADMIN'" title="部分操作需 SUPER_ADMIN 权限,当前只读" type="warning" :closable="false" style="margin-bottom:12px"/>
 <div class="card"><h3>引擎控制(dualperp)· 热配置</h3>
  <el-descriptions :column="2" border size="small">
   <el-descriptions-item label="模式"><el-tag :type="cfg.mode==='armed'?'danger':'info'">{{cfg.mode||'shadow'}}</el-tag></el-descriptions-item>
   <el-descriptions-item label="白名单">{{cfg.arm_symbols||'(空)'}}</el-descriptions-item>
   <el-descriptions-item label="单腿硬顶U">{{cfg.max_notional_hard}}</el-descriptions-item>
   <el-descriptions-item label="组合上限U">{{cfg.max_portfolio_notional}}</el-descriptions-item>
   <el-descriptions-item label="自动收敛">{{cfg.auto_converge}}</el-descriptions-item>
  </el-descriptions>
  <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
   <el-button :type="cfg.mode==='armed'?'info':'danger'" @click="toggleArm">{{cfg.mode==='armed'?'解除武装(转shadow)':'武装(armed)'}}</el-button>
   <el-button @click="editSet('arm_symbols','白名单(逗号分隔)')">改白名单</el-button>
   <el-button @click="editSet('max_notional_hard','单腿硬顶U')">改单腿硬顶</el-button>
   <el-button @click="editSet('max_portfolio_notional','组合上限U')">改组合上限</el-button>
   <el-button @click="editSet('auto_converge','自动收敛 true/false')">自动收敛</el-button>
   <el-button type="danger" plain @click="kill" style="margin-left:auto">🛑 Kill Switch</el-button>
  </div>
 </div></div>`,
 setup(){const cfg=reactive({}),me=reactive({role:''});const EP=ElementPlus
  async function load(){const d=await api('/api/admin/config');Object.assign(me,d.me);
   const m={};d.config.filter(c=>c.engine==='dualperp').forEach(c=>m[c.key]=c.val);Object.assign(cfg,m)}
  async function setKey(key,val,extra={}){try{await api('/api/admin/engine_config',{method:'POST',body:{engine:'dualperp',key,val,...extra}});EP.ElMessage.success(key+'='+val);await load()}
   catch(e){if(e.status===409)EP.ElMessage.error('武装联锁:风控未全绿');else if(e.status===403)EP.ElMessage.error('权限不足');else EP.ElMessage.error((e.data&&e.data.error)||'失败')}}
  async function toggleArm(){if(cfg.mode==='armed'){await setKey('mode','shadow');return}
   try{await EP.ElMessageBox.prompt('武装将允许真金下单。确认请输入 ARM','⚠️ 武装确认',{confirmButtonText:'武装',type:'warning',inputValidator:v=>v==='ARM'||'请输入 ARM'})
    await setKey('mode','armed',{confirm:'ARM'})}catch(e){}}
  async function editSet(key,label){try{const {value}=await EP.ElMessageBox.prompt(label,'修改 '+key,{inputValue:cfg[key]||''});await setKey(key,value)}catch(e){}}
  async function kill(){try{await EP.ElMessageBox.confirm('全组合置 shadow + 清空白名单(停止新开仓)。存量仓位需去路由页平仓。','🛑 全局急停',{confirmButtonText:'确认急停',type:'error'})
    await api('/api/admin/kill',{method:'POST',body:{}});EP.ElMessage.warning('已急停');await load()}catch(e){if(e.status)EP.ElMessage.error('需SUPER_ADMIN')}}
  onMounted(load);return{cfg,me,cls,toggleArm,editSet,kill}}}

const Routes={template:`<div class="card"><h3>活跃路由</h3>
  <el-table :data="rows" size="small" empty-text="无活跃路由">
   <el-table-column prop="symbol" label="币"/><el-table-column prop="engine" label="引擎"/>
   <el-table-column prop="venues" label="venue"/><el-table-column prop="target" label="目标U"/>
   <el-table-column prop="by" label="来源"/>
   <el-table-column label="操作" width="120"><template #default="s"><el-button size="small" type="danger" plain @click="off(s.row)">平仓(off)</el-button></template></el-table-column></el-table></div>`,
 setup(){const rows=ref([]);const EP=ElementPlus;async function load(){const o=await api('/api/overview');rows.value=o.routes_active||[]}
  async function off(r){try{await EP.ElMessageBox.confirm('将 '+r.symbol+' 路由置 off(引擎平掉该配对)','确认',{type:'warning'})
   const [vl,vs]=r.venues.split('/');await api('/api/admin/route',{method:'POST',body:{symbol:r.symbol,engine:'dualperp',venue_long:vl,market_long:'perp',venue_short:vs,market_short:'perp',target_notional_usdt:0,state:'off',reason:'admin off'}})
   EP.ElMessage.success('已置off');setTimeout(load,1500)}catch(e){if(e.status===403)EP.ElMessage.error('需OPERATOR')}}
  onMounted(load);return{rows,off}}}

const Alerts={template:`<div class="card"><h3>告警历史</h3><el-table :data="rows" size="small" empty-text="暂无告警">
  <el-table-column label="时间" width="160"><template #default="s">{{s.row.ts.replace('T',' ').slice(5,19)}}</template></el-table-column>
  <el-table-column label="级别" width="80"><template #default="s"><el-tag size="small" :type="s.row.level==='fatal'?'danger':(s.row.level==='warn'?'warning':'info')">{{s.row.level}}</el-tag></template></el-table-column>
  <el-table-column prop="title" label="标题" width="220"/><el-table-column prop="content" label="内容"/></el-table></div>`,
 setup(){const rows=ref([]);onMounted(async()=>{try{rows.value=(await api('/api/admin/alerts?limit=120')).alerts}catch(e){}});return{rows}}}

const Audit={template:`<div class="card"><h3>操作审计</h3><el-table :data="rows" size="small" empty-text="暂无操作">
  <el-table-column label="时间" width="160"><template #default="s">{{s.row.ts.replace('T',' ').slice(5,19)}}</template></el-table-column>
  <el-table-column prop="operator" label="操作员" width="100"/><el-table-column prop="role" label="角色" width="110"/>
  <el-table-column prop="action" label="动作" width="180"/><el-table-column prop="target" label="对象" width="140"/><el-table-column prop="result" label="结果"/></el-table></div>`,
 setup(){const rows=ref([]);onMounted(async()=>{try{rows.value=(await api('/api/admin/audit?limit=120')).audit}catch(e){if(e.status)rows.value=[]}});return{rows}}}

const Lending={template:`<div class="card"><h3>借贷三率净差(日化%)</h3><el-table :data="rows" size="small">
  <el-table-column prop="coin" label="币"/><el-table-column label="净差"><template #default="s"><span class="pos mono">{{fmt(s.row.net_daily_pct,3)}}</span></template></el-table-column>
  <el-table-column label="资金费"><template #default="s">{{fmt(s.row.funding_abs,3)}}</template></el-table-column>
  <el-table-column label="理财"><template #default="s">{{fmt(s.row.earn,3)}}</template></el-table-column>
  <el-table-column label="借币"><template #default="s">{{fmt(s.row.borrow,3)}}</template></el-table-column></el-table></div>`,
 setup(){const rows=ref([]);onMounted(async()=>{const o=await api('/api/overview');rows.value=(o.lending&&o.lending.top)||[]});return{rows,fmt}}}

const CoinBridge={template:`<div class="card"><h3>coin 借币业务(只读桥接)</h3>
  <el-alert title="coin 引擎原地运行,此为旁车只读视图;操作合并见后续里程碑" type="info" :closable="false" style="margin-bottom:12px"/>
  <el-table :data="rows" size="small" empty-text="coin 无在场仓位">
   <el-table-column prop="symbol" label="币"/><el-table-column prop="status" label="状态"/>
   <el-table-column prop="borrow_qty" label="借币量"/><el-table-column prop="futures_long_qty" label="合约多"/>
   <el-table-column prop="hedge_account" label="对冲账户"/></el-table></div>`,
 setup(){const rows=ref([]);onMounted(async()=>{try{const d=await api('/api/coin/positions');rows.value=d.positions||[]}catch(e){}});return{rows}}}

const menus=[['overview','总览',Overview],['engine','引擎控制',EngineCtl],['routes','路由',Routes],
 ['alerts','告警历史',Alerts],['audit','操作审计',Audit],['lending','借贷增强',Lending],['coin','coin借币',CoinBridge]]
const App={template:`<div v-if="!authed" class="login"><div class="card" style="width:340px">
  <h3>DexCexMix 控制台</h3><el-input v-model="t" placeholder="操作令牌 X-Op-Token" show-password @keyup.enter="login"/>
  <el-button type="primary" style="width:100%;margin-top:12px" @click="login">登录</el-button>
  <div class="dim" style="margin-top:8px;font-size:11px">只读可用 dashboard token;操作/管理需 operator 令牌</div></div></div>
 <el-container v-else><el-aside width="180px"><div class="brand">⚡ DexCexMix</div>
   <el-menu :default-active="cur" @select="k=>cur=k"><el-menu-item v-for="m in menus" :key="m[0]" :index="m[0]">{{m[1]}}</el-menu-item></el-menu></el-aside>
  <el-container><el-header><b>{{title}}</b><span class="dim" style="font-size:12px">{{now}}</span>
    <el-button size="small" style="margin-left:auto" @click="logout">退出</el-button></el-header>
   <el-main><component :is="view"/></el-main></el-container></el-container>`,
 setup(){const authed=ref(!!tok()),t=ref(''),cur=ref('overview'),now=ref('')
  const EP=ElementPlus
  async function login(){if(!t.value)return;localStorage.setItem(TOKKEY,t.value.trim());authed.value=true}
  function logout(){localStorage.removeItem(TOKKEY);authed.value=false}
  const view=computed(()=>(menus.find(m=>m[0]===cur.value)||menus[0])[2])
  const title=computed(()=>(menus.find(m=>m[0]===cur.value)||menus[0])[1])
  setInterval(()=>now.value=new Date().toLocaleTimeString(),1000)
  return{authed,t,cur,menus,view,title,now,login,logout}}}
createApp(App).use(ElementPlus).mount('#app')
</script></body></html>"""
