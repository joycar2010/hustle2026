import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../layout/Layout.vue'
// 菜单分组顺序: 总控 → 分析(可收缩) → 经营(可收缩) → 运维(可收缩)。ord 控制组内顺序。
const routes = [
  { path:'/', component:Layout, redirect:'/dashboard', children:[
    // ===== 总控(置顶, 不收缩) =====
    { path:'dashboard', name:'dashboard', meta:{title:'总控面板',icon:'Odometer',group:'总控',ord:0}, component:()=>import('../views/Dashboard.vue') },
    // ===== 分析 =====
    { path:'bi', name:'bi', meta:{title:'经营分析',icon:'TrendCharts',group:'分析',ord:1}, component:()=>import('../views/Bi.vue') },
    { path:'product', name:'product', meta:{title:'产品分析',icon:'PieChart',group:'分析',ord:2}, component:()=>import('../views/Product.vue') },
    // ===== 经营 =====
    { path:'users', name:'users', meta:{title:'用户管理',icon:'User',group:'经营',ord:1}, component:()=>import('../views/Users.vue') },
    { path:'accounts', name:'accounts', meta:{title:'账户管理',icon:'CreditCard',group:'经营',ord:1.5}, component:()=>import('../views/Accounts.vue') },
    { path:'leads', name:'leads', meta:{title:'线索中台',icon:'ChatDotRound',group:'经营',ord:2}, component:()=>import('../views/Leads.vue') },
    { path:'trials', name:'trials', meta:{title:'试用管理',icon:'Stopwatch',group:'经营',ord:3}, component:()=>import('../views/Trials.vue') },
    { path:'orders', name:'orders', meta:{title:'充值订单',icon:'Wallet',group:'经营',ord:4}, component:()=>import('../views/Orders.vue') },
    { path:'points', name:'points', meta:{title:'会员与积分',icon:'Medal',group:'经营',ord:5}, component:()=>import('../views/Points.vue') },
    { path:'agents', name:'agents', meta:{title:'三级代理',icon:'Share',group:'经营',ord:6}, component:()=>import('../views/Agents.vue') },
    { path:'staff', name:'staff', meta:{title:'员工推广',icon:'UserFilled',group:'经营',ord:7}, component:()=>import('../views/Staff.vue') },
    { path:'coupons', name:'coupons', meta:{title:'折扣券',icon:'Ticket',group:'经营',ord:8}, component:()=>import('../views/Coupons.vue') },
    { path:'campaigns', name:'campaigns', meta:{title:'活动引擎',icon:'MagicStick',group:'经营',ord:9}, component:()=>import('../views/Campaigns.vue') },
    { path:'contests', name:'contests', meta:{title:'冲榜赛',icon:'Trophy',group:'经营',ord:10}, component:()=>import('../views/Contests.vue') },
    { path:'iap', name:'iap', meta:{title:'内购配置',icon:'Goods',group:'经营',ord:11}, component:()=>import('../views/Iap.vue') },
    { path:'chat', name:'chat', meta:{title:'AI客服配置',icon:'Service',group:'经营',ord:12}, component:()=>import('../views/Chat.vue') },
    // 全渠道看板: 已并入「经营分析」页, 菜单隐藏(路由保留可直达)
    { path:'overview', name:'overview', meta:{title:'全渠道看板',icon:'DataAnalysis',group:'分析',hidden:true}, component:()=>import('../views/Overview.vue') },
    // ===== 运维 =====
    { path:'system', name:'system', meta:{title:'运维监控',icon:'Monitor',group:'运维',ord:1}, component:()=>import('../views/System.vue') },
    { path:'params', name:'params', meta:{title:'参数下发',icon:'Setting',group:'运维',ord:2}, component:()=>import('../views/Params.vue') },
    { path:'notify', name:'notify', meta:{title:'系统通知',icon:'Bell',group:'运维',ord:3}, component:()=>import('../views/Notify.vue') },
    { path:'sitemgr', name:'sitemgr', meta:{title:'官网管理',icon:'Link',group:'运维',ord:3.5}, component:()=>import('../views/SiteMgr.vue') },
    { path:'datamgr', name:'datamgr', meta:{title:'系统管理',icon:'Coin',group:'运维',ord:4}, component:()=>import('../views/DataMgr.vue') },
    { path:'operators', name:'operators', meta:{title:'操作员',icon:'Avatar',group:'运维',ord:5}, component:()=>import('../views/Operators.vue') },
    // 保留(功能不丢, 附运维末尾)
    { path:'legs', name:'legs', meta:{title:'双腿监控',icon:'Connection',group:'运维',ord:6}, component:()=>import('../views/Legs.vue') },
    { path:'recon', name:'recon', meta:{title:'跨用户对账',icon:'Files',group:'运维',ord:7}, component:()=>import('../views/Recon.vue') },
    { path:'deals', name:'deals', meta:{title:'成交记录',icon:'List',group:'运维',ord:8}, component:()=>import('../views/Deals.vue') },
  ]}
]
export default createRouter({ history:createWebHistory(), routes })
