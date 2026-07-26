import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../layout/Layout.vue'
// 菜单分组顺序: 总控 → 分析(可收缩) → 经营(可收缩) → 运维(可收缩)。ord 控制组内顺序。
const routes = [
  // PATCH-02 §3.1:默认入口=今日工作总览(中控台退役中,路由保留可直达)
  { path:'/', component:Layout, redirect:{ path:'/mix/work', query:{ view:'overview' } }, children:[
    // ===== V6.1 最终菜单(§2):今日工作/研究与测试/风险与资金/管理设置(折叠)/系统(折叠) =====
    // ═══ V6.2 §三 四入口(N3):今日工作/风险与账务/管理设置/LAB;低频进右上系统管理;旧URL全保留 ═══
    // ① 今日工作(合体页=唯一日常入口)
    { path:'mix/today', name:'mix-today', meta:{title:'今日工作',icon:'Calendar',group:'今日工作',ord:-1}, component:()=>import('../views/mix/MixToday.vue') },
    { path:'mix/training', name:'mix-training', meta:{title:'训练模式',icon:'Reading',group:'今日工作',ord:-0.5}, component:()=>import('../views/mix/MixTraining.vue') },
    // R5 Phase 2(2026-07-26):旧中控已删除,引用已修复指向 /mix/work
    // N3 收敛曾把下面两项 hidden——用户 07-16 反馈「AiCoin工作台/人工双合约(新建手动计划)不见了」,恢复常驻菜单
    { path:'mix/workbench', name:'mix-workbench', meta:{title:'策略工作台（手动开仓）',icon:'Operation',group:'今日工作',ord:0.1}, component:()=>import('../views/mix/MixV6Workbench.vue') },
    { path:'mix/aicoin', name:'mix-aicoin', meta:{title:'AiCoin 研判工作台',icon:'DataAnalysis',group:'今日工作',ord:0.2}, component:()=>import('../views/mix/MixAiCoin.vue') },
    // ② 风险与账务
    { path:'mix/venuerisk', name:'mix-venuerisk', meta:{title:'风险事件',icon:'Warning',group:'风险与账务',ord:2.0}, component:()=>import('../views/mix/MixRiskCenter.vue') },
    { path:'mix/report', name:'mix-report', meta:{title:'资产收益',icon:'TrendCharts',group:'风险与账务',ord:2.1}, component:()=>import('../views/mix/MixReport.vue') },
    { path:'mix/history', name:'mix-history', meta:{title:'交易与核对',icon:'History',group:'风险与账务',ord:2.2}, component:()=>import('../views/mix/MixHistory.vue') },
    // REV2 §4A.6:客户与份额(从操作员管理切开——客户资金权益≠操作权限)
    { path:'mix/clients', name:'mix-clients', meta:{title:'客户与份额',icon:'User',group:'风险与账务',ord:2.3}, component:()=>import('../views/mix/MixClients.vue') },
    // ③ 管理设置(默认折叠):两项
    { path:'mix/rules', name:'mix-rules', meta:{title:'策略与额度',icon:'Setting',group:'管理设置',ord:3.0}, component:()=>import('../views/mix/MixRules.vue') },
    { path:'mix/accounts', name:'mix-accounts', meta:{title:'账户、币种与路由',icon:'CreditCard',group:'管理设置',ord:3.1}, component:()=>import('../views/mix/MixAccountsPlatform.vue') },
    { path:'mix/blacklist', name:'mix-blacklist', meta:{hidden:true,title:'准入与隔离',icon:'CircleClose',group:'管理设置',ord:3.2}, component:()=>import('../views/mix/MixBlacklist.vue') },
    { path:'mix/coins', name:'mix-coins', meta:{hidden:true,title:'标的与路由',icon:'Coin',group:'管理设置',ord:3.3}, component:()=>import('../views/mix/MixCoins.vue') },
    // R5 退役(2026-07-26):C3 旧页 3 路由已删除,功能已并入今日工作统一工作台
    { path:'mix/maintenance', name:'mix-maintenance', meta:{hidden:true,title:'网站维护排空(并入通知模块)',icon:'Tools',group:'管理设置',ord:3.7}, component:()=>import('../views/mix/MixMaintenance.vue') },
    { path:'mix/strategies', name:'mix-strategies', meta:{hidden:true,title:'持仓与执行(旧)',icon:'Share',group:'管理设置',ord:3.8}, component:()=>import('../views/mix/MixStrategies.vue') },
    // ④ LAB(独立入口)
    { path:'mix/lab', name:'mix-lab', meta:{title:'DEX/Onchain LAB',icon:'Cpu',group:'LAB',ord:4.0}, component:()=>import('../views/mix/MixV6Lab.vue') },
    // V6.2 PATCH-01 §6.1 统一权威路由别名:/mix/work(query 透传;今日工作=唯一日常外壳)
    { path:'mix/work', redirect: to => ({ path:'/mix/today', query: to.query }) },
    // V6.1 §5 唯一生产写路由别名(旧 C3 别名已随主路由退役)
    { path:'v6.1/strategy-workbench', redirect:'/mix/workbench' },
    { path:'mix/strategy/:code', name:'mix-strategy-detail', meta:{title:'策略明细',icon:'Share',group:'总控',hidden:true}, component:()=>import('../views/mix/MixStrategyDetail.vue') },
    { path:'mix/venue/:venue', name:'mix-venue-detail', meta:{title:'平台详情',icon:'Warning',group:'总控',hidden:true}, component:()=>import('../views/mix/MixVenueDetail.vue') },
    // ⑤ 系统(默认折叠)
    { path:'mix/notify', name:'mix-notify', meta:{hidden:true,title:'通知模块',icon:'Bell',group:'系统',ord:4.2}, component:()=>import('../views/mix/MixNotifyCenter.vue') },
    { path:'mix/site', name:'mix-site', meta:{hidden:true,title:'网站设置',icon:'Link',group:'系统',ord:4.5}, component:()=>import('../views/mix/MixSite.vue') },
    { path:'mix/operators', name:'mix-operators', meta:{hidden:true,title:'操作员管理',icon:'Avatar',group:'系统',ord:4.3}, component:()=>import('../views/mix/MixOperators.vue') },
    { path:'mix/system', name:'mix-system', meta:{hidden:true,title:'系统配置',icon:'Coin',group:'系统',ord:4.4}, component:()=>import('../views/mix/MixSystem.vue') },
    { path:'mix/llm', name:'mix-llm', meta:{hidden:true,title:'LLM设置',icon:'Service',group:'系统',ord:5}, component:()=>import('../views/mix/MixLLM.vue') },
    // ===== R5 退役(2026-07-26):QH 经营壳 24 路由已删除,功能已并入 Mix 系统 =====
    // 保留:/system(→MixOps活组件) + /deals(→/recon兼容redirect)
    { path:'system', name:'system', meta:{hidden:true,title:'系统状态',icon:'Monitor',group:'系统',ord:4.1}, component:()=>import('../views/mix/MixOps.vue') },
    { path:'deals', redirect:'/recon' },
  ]},
  // ===== 三分屏指挥墙：免登录只读路由（?token= 墙令牌，后端校验），无侧栏壳 =====
  { path:'/wall/market', name:'wall-market', component:()=>import('../views/mix/MixWallMarket.vue') },
  { path:'/wall/risk', name:'wall-risk', component:()=>import('../views/mix/MixWallRisk.vue') },
  { path:'/wall/exec', name:'wall-exec', component:()=>import('../views/mix/MixWallExec.vue') },
  // PATCH-02 §3.2 语义别名(query 透传:?token= 墙令牌)
  { path:'/wall/opportunity', redirect: to => ({ path:'/wall/market', query: to.query }) },
  { path:'/wall/position', redirect: to => ({ path:'/wall/exec', query: to.query }) },
  { path:'/mobile', name:'mobile', component:()=>import('../views/mix/MixMobile.vue') },
  // V6.1 §8.3 手机操作员专属壳(OPERATOR_MOBILE_LIMITED,底部五页签,服务端白名单动作)
  { path:'/m', name:'phone', component:()=>import('../views/mix/MixPhone.vue') },
]
const router = createRouter({ history:createWebHistory(), routes })
// V6.2 移动端强制跳 /m(2026-07-17 用户拍板):手机访问桌面壳一律进手机专属壳。
// 逃生口: 任意路由带 ?desktop=1 → 本次会话(sessionStorage)留在桌面版;墙/平板壳(/wall,/mobile)不拦。
const PHONE_EXEMPT = /^\/(m|mobile|wall)(\/|$)/
router.beforeEach((to) => {
  try {
    if (to.query.desktop === '1') { sessionStorage.setItem('mix_force_desktop', '1'); return true }
    if (sessionStorage.getItem('mix_force_desktop') === '1') return true
    const phoneUa = /Android.*Mobile|iPhone|iPod/i.test(navigator.userAgent)
    const narrow = Math.min(window.innerWidth, window.innerHeight) < 820
    if (phoneUa && narrow && !PHONE_EXEMPT.test(to.path)) return { path: '/m', replace: true }
  } catch (e) { /* 检测失败不拦路由 */ }
  return true
})
export default router
