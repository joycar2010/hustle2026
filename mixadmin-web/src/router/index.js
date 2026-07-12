import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../layout/Layout.vue'
// 菜单分组顺序: 总控 → 分析(可收缩) → 经营(可收缩) → 运维(可收缩)。ord 控制组内顺序。
const routes = [
  { path:'/', component:Layout, redirect:'/mix/dashboard', children:[
    // ===== Mix 主控(置顶, 不收缩) —— HustleCoin Mix 多策略持股公司 =====
    { path:'mix/dashboard', name:'mix-dashboard', meta:{title:'主控台·Mix',icon:'Odometer',group:'总控',ord:0}, component:()=>import('../views/mix/MixDashboard.vue') },
    { path:'mix/strategies', name:'mix-strategies', meta:{title:'策略总览',icon:'Share',group:'总控',ord:0.1}, component:()=>import('../views/mix/MixStrategies.vue') },
    { path:'mix/strategy/:code', name:'mix-strategy-detail', meta:{title:'策略明细',icon:'Share',group:'总控',hidden:true}, component:()=>import('../views/mix/MixStrategyDetail.vue') },
    { path:'mix/rules', name:'mix-rules', meta:{title:'规则中心',icon:'Setting',group:'总控',ord:0.2}, component:()=>import('../views/mix/MixRules.vue') },
    { path:'mix/accounts', name:'mix-accounts', meta:{title:'账户列表',icon:'CreditCard',group:'总控',ord:0.3}, component:()=>import('../views/mix/MixAccounts.vue') },
    { path:'mix/monitor', name:'mix-monitor', meta:{title:'监控中心',icon:'Monitor',group:'总控',ord:0.35}, component:()=>import('../views/mix/MixMonitor.vue') },
    { path:'mix/blacklist', name:'mix-blacklist', meta:{title:'黑名单',icon:'CircleClose',group:'总控',ord:0.4}, component:()=>import('../views/mix/MixBlacklist.vue') },
    { path:'mix/coins', name:'mix-coins', meta:{title:'币管理',icon:'Coin',group:'总控',ord:0.45}, component:()=>import('../views/mix/MixCoins.vue') },
    { path:'mix/report', name:'mix-report', meta:{title:'资金报表',icon:'TrendCharts',group:'总控',ord:0.5}, component:()=>import('../views/mix/MixReport.vue') },
    { path:'mix/notify', name:'mix-notify', meta:{title:'通知设置',icon:'Bell',group:'总控',ord:0.55}, component:()=>import('../views/mix/MixNotify.vue') },
    // ===== 总控(qh 原有, 待 M3+ 逐模块替换) =====
    { path:'dashboard', name:'dashboard', meta:{hidden:true,title:'总控面板',icon:'Odometer',group:'总控',ord:0.5}, component:()=>import('../views/Dashboard.vue') },
    // ===== 分析 =====
    { path:'bi', name:'bi', meta:{hidden:true,title:'经营分析',icon:'TrendCharts',group:'分析',ord:1}, component:()=>import('../views/Bi.vue') },
    { path:'product', name:'product', meta:{hidden:true,title:'产品分析',icon:'PieChart',group:'分析',ord:2}, component:()=>import('../views/Product.vue') },
    // ===== 经营 =====
    { path:'users', name:'users', meta:{hidden:true,title:'用户管理',icon:'User',group:'经营',ord:1}, component:()=>import('../views/Users.vue') },
    { path:'accounts', name:'accounts', meta:{hidden:true,title:'账户管理',icon:'CreditCard',group:'经营',ord:1.5}, component:()=>import('../views/Accounts.vue') },
    { path:'leads', name:'leads', meta:{hidden:true,title:'线索中台',icon:'ChatDotRound',group:'经营',ord:2}, component:()=>import('../views/Leads.vue') },
    { path:'trials', name:'trials', meta:{hidden:true,title:'试用管理',icon:'Stopwatch',group:'经营',ord:3}, component:()=>import('../views/Trials.vue') },
    { path:'orders', name:'orders', meta:{hidden:true,title:'充值订单',icon:'Wallet',group:'经营',ord:4}, component:()=>import('../views/Orders.vue') },
    { path:'points', name:'points', meta:{hidden:true,title:'会员与积分',icon:'Medal',group:'经营',ord:5}, component:()=>import('../views/Points.vue') },
    { path:'agents', name:'agents', meta:{hidden:true,title:'三级代理',icon:'Share',group:'经营',ord:6}, component:()=>import('../views/Agents.vue') },
    { path:'staff', name:'staff', meta:{hidden:true,title:'员工推广',icon:'UserFilled',group:'经营',ord:7}, component:()=>import('../views/Staff.vue') },
    { path:'coupons', name:'coupons', meta:{hidden:true,title:'折扣券',icon:'Ticket',group:'经营',ord:8}, component:()=>import('../views/Coupons.vue') },
    { path:'campaigns', name:'campaigns', meta:{hidden:true,title:'活动引擎',icon:'MagicStick',group:'经营',ord:9}, component:()=>import('../views/Campaigns.vue') },
    { path:'contests', name:'contests', meta:{hidden:true,title:'冲榜赛',icon:'Trophy',group:'经营',ord:10}, component:()=>import('../views/Contests.vue') },
    { path:'iap', name:'iap', meta:{hidden:true,title:'内购配置',icon:'Goods',group:'经营',ord:11}, component:()=>import('../views/Iap.vue') },
    // AI客服配置已并入「系统设置 › LLM 设置」（/chat）
    // 全渠道看板: 已并入「经营分析」页, 菜单隐藏(路由保留可直达)
    { path:'overview', name:'overview', meta:{title:'全渠道看板',icon:'DataAnalysis',group:'分析',hidden:true}, component:()=>import('../views/Overview.vue') },
    // ===== 系统设置（运维面板/通知模块/操作员管理/系统配置：版本·数据库·SSL/LLM 设置） =====
    { path:'system', name:'system', meta:{title:'运维面板',icon:'Monitor',group:'系统设置',ord:1}, component:()=>import('../views/System.vue') },
    { path:'params', name:'params', meta:{title:'参数下发',icon:'Setting',group:'系统设置',ord:1.5}, component:()=>import('../views/Params.vue') },
    { path:'notify', name:'notify', meta:{title:'通知模块',icon:'Bell',group:'系统设置',ord:2}, component:()=>import('../views/Notify.vue') },
    { path:'sitemgr', name:'sitemgr', meta:{title:'官网管理',icon:'Link',group:'系统设置',ord:2.5}, component:()=>import('../views/SiteMgr.vue') },
    { path:'operators', name:'operators', meta:{title:'操作员管理',icon:'Avatar',group:'系统设置',ord:3}, component:()=>import('../views/Operators.vue') },
    { path:'datamgr', name:'datamgr', meta:{title:'系统配置（版本/数据库/SSL）',icon:'Coin',group:'系统设置',ord:4}, component:()=>import('../views/DataMgr.vue') },
    { path:'chat', name:'llm', meta:{title:'LLM 设置',icon:'Service',group:'系统设置',ord:5}, component:()=>import('../views/Chat.vue') },
    // 保留(功能不丢, 附运维末尾)
    { path:'legs', name:'legs', meta:{hidden:true,title:'双腿监控',icon:'Connection',group:'运维',ord:6}, component:()=>import('../views/Legs.vue') },
    { path:'recon', name:'recon', meta:{hidden:true,title:'跨用户对账',icon:'Files',group:'运维',ord:7}, component:()=>import('../views/Recon.vue') },
    // 成交记录已并入 跨用户对账(/recon 第二页签"成交记录·统计"); 旧 /deals 直达链接重定向兜底
    { path:'deals', redirect:'/recon' },
  ]},
  // ===== 三分屏指挥墙：免登录只读路由（?token= 墙令牌，后端校验），无侧栏壳 =====
  { path:'/wall/market', name:'wall-market', component:()=>import('../views/mix/MixWallMarket.vue') },
  { path:'/wall/risk', name:'wall-risk', component:()=>import('../views/mix/MixWallRisk.vue') },
]
export default createRouter({ history:createWebHistory(), routes })
